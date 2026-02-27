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
from ..core.client import KiroClient
from ..core.sanitizer import sanitize_text
from ..stats import stats

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1")

# Shared instances (initialized in app lifespan)
token_manager: TokenManager = None  # type: ignore[assignment]
kiro_client: KiroClient = None  # type: ignore[assignment]


def init_services(tm: TokenManager, kiro: KiroClient):
    global token_manager, kiro_client
    token_manager = tm
    kiro_client = kiro


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

    from ..log_context import user_tag
    client_tag = request.headers.get("x-user-tag")
    if not client_tag:
        client_ip = request.client.host if request.client else "unknown"
        client_tag = f"api:{client_ip}"
    user_tag.set(client_tag)

    body = await request.json()
    messages = body.get("messages", [])
    logger.info(f"📥 chat_completions request: model={body.get('model')}, messages={len(messages)}, tools={len(body.get('tools', []) or [])}, stream={body.get('stream')}")
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


def _accumulate_tool_use_event(
    buffers: dict,
    payload: dict,
    tool_call_index: int,
) -> dict | None:
    """Accumulate streaming toolUseEvent chunks; return completed tool call when stop=True."""
    tool_use_id = payload.get("toolUseId", "")
    tool_name = payload.get("name", "")
    input_chunk = payload.get("input", "")
    is_stop = payload.get("stop", False)

    if tool_use_id not in buffers:
        buffers[tool_use_id] = {"name": tool_name, "input_chunks": [], "index": tool_call_index}

    if input_chunk:
        buffers[tool_use_id]["input_chunks"].append(input_chunk)

    if is_stop:
        buf = buffers.pop(tool_use_id)
        arguments = "".join(buf["input_chunks"])
        name = buf["name"] or tool_name
        return _build_tool_call_openai(buf["index"], tool_use_id, name, arguments)

    return None


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
    tool_calls_seen: list[dict] = []
    tool_call_index = 0
    tool_use_buffers: dict = {}  # toolUseId -> {name, input_chunks, index}

    try:
        async for event in kiro_client.generate_stream(
            access_token=access_token,
            messages=messages,
            model=model,
            profile_arn=profile_arn,
            tools=tools,
        ):
            if event.event_type == "assistantResponseEvent":
                content = event.payload.get("content", "")
                if content:
                    content = sanitize_text(content, is_chunk=True)
                if content:
                    yield _make_chunk(chat_id, created, model, {"content": content})

            elif event.event_type == "toolUseEvent":
                # Kiro streams tool calls incrementally; accumulate until stop=True
                tc = _accumulate_tool_use_event(tool_use_buffers, event.payload, tool_call_index)
                if tc is not None:
                    tool_calls_seen.append(tc)
                    tool_call_index += 1
                    yield _make_chunk(chat_id, created, model, {"tool_calls": [tc]})

            elif event.event_type in ("supplementaryWebLinksEvent", "contextUsageEvent"):
                pass

            elif event.event_type == "exception":
                error_msg = event.payload.get("message", str(event.payload))
                yield _make_chunk(
                    chat_id, created, model,
                    {"content": f"\n\n[Error: {error_msg}]"},
                    finish_reason="stop",
                )

            else:
                logger.debug(f"🔍 Unhandled Kiro event: type={event.event_type!r}, payload={str(event.payload)[:200]}")

        # Final chunk: finish_reason depends on whether tools were called
        finish_reason = "tool_calls" if tool_calls_seen else "stop"
        latency_ms = (time.time() - t0) * 1000
        logger.info(f"📥 chat_completions response: finish={finish_reason}, tool_calls={len(tool_calls_seen)}, latency={latency_ms:.0f}ms")
        yield _make_chunk(chat_id, created, model, {}, finish_reason=finish_reason)
        yield "data: [DONE]\n\n"
        stats.record(model=model, latency_ms=latency_ms, status="ok")

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
    tool_use_buffers: dict = {}

    async for event in kiro_client.generate_stream(
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

        elif event.event_type == "toolUseEvent":
            tc = _accumulate_tool_use_event(tool_use_buffers, event.payload, tool_call_index)
            if tc is not None:
                tool_calls.append(tc)
                tool_call_index += 1

        elif event.event_type == "exception":
            error_msg = event.payload.get("message", str(event.payload))
            raise HTTPException(status_code=502, detail=f"Kiro error: {error_msg}")

    full_text = sanitize_text("".join(text_parts))
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
