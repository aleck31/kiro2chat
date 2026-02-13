"""OpenAI-compatible API routes."""

import json
import time
import uuid
import logging
from typing import AsyncIterator

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import StreamingResponse, JSONResponse

from ..config import config
from ..core import TokenManager
from ..core.client import CodeWhispererClient
from ..stats import stats

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1")

# Shared instances (initialized in app lifespan)
token_manager: TokenManager | None = None
cw_client: CodeWhispererClient | None = None


def init_services(tm: TokenManager, cw: CodeWhispererClient):
    global token_manager, cw_client
    token_manager = tm
    cw_client = cw


def _check_auth(authorization: str | None = None, x_api_key: str | None = None):
    """Validate API key if configured."""
    if not config.api_key:
        return

    key = None
    if authorization and authorization.startswith("Bearer "):
        key = authorization[7:]
    elif x_api_key:
        key = x_api_key

    if key != config.api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")


@router.get("/models")
async def list_models(
    authorization: str | None = Header(None),
    x_api_key: str | None = Header(None, alias="x-api-key"),
):
    _check_auth(authorization, x_api_key)

    models = []
    for model_name in config.model_map:
        models.append({
            "id": model_name,
            "object": "model",
            "created": 1700000000,
            "owned_by": "aws-kiro",
        })

    return {"object": "list", "data": models}


@router.post("/chat/completions")
async def chat_completions(
    request: Request,
    authorization: str | None = Header(None),
    x_api_key: str | None = Header(None, alias="x-api-key"),
):
    _check_auth(authorization, x_api_key)

    body = await request.json()
    messages = body.get("messages", [])
    model = body.get("model", config.default_model)
    stream = body.get("stream", False)
    tools = body.get("tools")

    if not messages:
        raise HTTPException(status_code=400, detail="messages is required")

    if model not in config.model_map:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown model: {model}. Available: {list(config.model_map.keys())}",
        )

    t0 = time.time()
    access_token = await token_manager.get_access_token()
    profile_arn = token_manager.profile_arn

    if stream:
        return StreamingResponse(
            _stream_response(access_token, messages, model, profile_arn, tools, t0),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
    else:
        resp = await _non_stream_response(
            access_token, messages, model, profile_arn, tools
        )
        latency = (time.time() - t0) * 1000
        stats.record(model=model, latency_ms=latency, status="ok")
        return resp


def _make_chunk(chat_id: str, created: int, model: str, delta: dict, finish_reason: str | None = None) -> str:
    """Build an SSE chunk string in OpenAI format."""
    chunk = {
        "id": chat_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [
            {
                "index": 0,
                "delta": delta,
                "finish_reason": finish_reason,
            }
        ],
    }
    return f"data: {json.dumps(chunk)}\n\n"


def _build_tool_call_openai(index: int, tool_use_id: str, name: str, arguments: str) -> dict:
    """Build an OpenAI-format tool_call object."""
    return {
        "index": index,
        "id": tool_use_id,
        "type": "function",
        "function": {
            "name": name,
            "arguments": arguments,
        },
    }


async def _stream_response(
    access_token: str,
    messages: list[dict],
    model: str,
    profile_arn: str,
    tools: list[dict] | None,
    t0: float = 0,
) -> AsyncIterator[str]:
    """Generate SSE stream in OpenAI format with tool_calls support."""
    chat_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
    created = int(time.time())
    tool_calls_seen: list[dict] = []  # Track tool calls for finish_reason
    tool_call_index = 0

    try:
        async for event in cw_client.generate_stream(
            access_token=access_token,
            messages=messages,
            model=model,
            profile_arn=profile_arn,
            tools=tools,
        ):
            if event.event_type == "assistantResponseEvent":
                content = event.payload.get("content", "")
                if content:
                    yield _make_chunk(chat_id, created, model, {"content": content})

            elif event.event_type == "toolUse":
                # CodeWhisperer toolUse event -> OpenAI tool_calls chunk
                payload = event.payload
                tool_use_id = payload.get("toolUseId", f"call_{uuid.uuid4().hex[:24]}")
                tool_name = payload.get("name", "")
                tool_input = payload.get("input", {})

                # Convert input to JSON string
                if isinstance(tool_input, str):
                    arguments = tool_input
                else:
                    arguments = json.dumps(tool_input)

                tc = _build_tool_call_openai(tool_call_index, tool_use_id, tool_name, arguments)
                tool_calls_seen.append(tc)
                tool_call_index += 1

                # Emit tool_calls delta chunk
                yield _make_chunk(chat_id, created, model, {"tool_calls": [tc]})

            elif event.event_type == "supplementaryWebLinksEvent":
                pass

            elif event.event_type == "exception":
                error_msg = event.payload.get("message", str(event.payload))
                yield _make_chunk(
                    chat_id, created, model,
                    {"content": f"\n\n[Error: {error_msg}]"},
                    finish_reason="stop",
                )

        # Final chunk: finish_reason depends on whether tools were called
        finish_reason = "tool_calls" if tool_calls_seen else "stop"
        yield _make_chunk(chat_id, created, model, {}, finish_reason=finish_reason)
        yield "data: [DONE]\n\n"
        stats.record(model=model, latency_ms=(time.time() - t0) * 1000, status="ok")

    except Exception as e:
        logger.error(f"Stream error: {e}")
        stats.record(model=model, latency_ms=(time.time() - t0) * 1000, status="error", error=str(e))
        yield _make_chunk(chat_id, created, model, {"content": f"\n\n[Error: {e}]"}, finish_reason="stop")
        yield "data: [DONE]\n\n"


async def _non_stream_response(
    access_token: str,
    messages: list[dict],
    model: str,
    profile_arn: str,
    tools: list[dict] | None,
) -> JSONResponse:
    """Collect full response and return as single JSON, including tool_calls."""
    chat_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
    created = int(time.time())
    text_parts: list[str] = []
    tool_calls: list[dict] = []
    tool_call_index = 0

    async for event in cw_client.generate_stream(
        access_token=access_token,
        messages=messages,
        model=model,
        profile_arn=profile_arn,
        tools=tools,
    ):
        if event.event_type == "assistantResponseEvent":
            content = event.payload.get("content", "")
            if content:
                text_parts.append(content)

        elif event.event_type == "toolUse":
            payload = event.payload
            tool_use_id = payload.get("toolUseId", f"call_{uuid.uuid4().hex[:24]}")
            tool_name = payload.get("name", "")
            tool_input = payload.get("input", {})

            if isinstance(tool_input, str):
                arguments = tool_input
            else:
                arguments = json.dumps(tool_input)

            tool_calls.append(_build_tool_call_openai(tool_call_index, tool_use_id, tool_name, arguments))
            tool_call_index += 1

        elif event.event_type == "exception":
            error_msg = event.payload.get("message", str(event.payload))
            raise HTTPException(status_code=502, detail=f"CodeWhisperer error: {error_msg}")

    full_text = "".join(text_parts)
    finish_reason = "tool_calls" if tool_calls else "stop"

    message: dict = {
        "role": "assistant",
        "content": full_text or None,
    }
    if tool_calls:
        message["tool_calls"] = tool_calls

    return JSONResponse({
        "id": chat_id,
        "object": "chat.completion",
        "created": created,
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": message,
                "finish_reason": finish_reason,
            }
        ],
        "usage": {
            "prompt_tokens": -1,
            "completion_tokens": -1,
            "total_tokens": -1,
        },
    })
