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
        return  # No auth required

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

    # Resolve model
    if model not in config.model_map:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown model: {model}. Available: {list(config.model_map.keys())}",
        )

    access_token = await token_manager.get_access_token()
    profile_arn = token_manager.profile_arn

    if stream:
        return StreamingResponse(
            _stream_response(access_token, messages, model, profile_arn, tools),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
    else:
        return await _non_stream_response(
            access_token, messages, model, profile_arn, tools
        )


async def _stream_response(
    access_token: str,
    messages: list[dict],
    model: str,
    profile_arn: str,
    tools: list[dict] | None,
) -> AsyncIterator[str]:
    """Generate SSE stream in OpenAI format."""
    chat_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
    created = int(time.time())

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
                    chunk = {
                        "id": chat_id,
                        "object": "chat.completion.chunk",
                        "created": created,
                        "model": model,
                        "choices": [
                            {
                                "index": 0,
                                "delta": {"content": content},
                                "finish_reason": None,
                            }
                        ],
                    }
                    yield f"data: {json.dumps(chunk)}\n\n"

            elif event.event_type == "supplementaryWebLinksEvent":
                pass  # Ignore web links

            elif event.event_type == "exception":
                error_msg = event.payload.get("message", str(event.payload))
                error_chunk = {
                    "id": chat_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": model,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"content": f"\n\n[Error: {error_msg}]"},
                            "finish_reason": "stop",
                        }
                    ],
                }
                yield f"data: {json.dumps(error_chunk)}\n\n"

        # Send final chunk
        final_chunk = {
            "id": chat_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "delta": {},
                    "finish_reason": "stop",
                }
            ],
        }
        yield f"data: {json.dumps(final_chunk)}\n\n"
        yield "data: [DONE]\n\n"

    except Exception as e:
        logger.error(f"Stream error: {e}")
        error_chunk = {
            "id": chat_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "delta": {"content": f"\n\n[Error: {e}]"},
                    "finish_reason": "stop",
                }
            ],
        }
        yield f"data: {json.dumps(error_chunk)}\n\n"
        yield "data: [DONE]\n\n"


async def _non_stream_response(
    access_token: str,
    messages: list[dict],
    model: str,
    profile_arn: str,
    tools: list[dict] | None,
) -> JSONResponse:
    """Collect full response and return as single JSON."""
    chat_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
    created = int(time.time())
    text_parts: list[str] = []

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
        elif event.event_type == "exception":
            error_msg = event.payload.get("message", str(event.payload))
            raise HTTPException(status_code=502, detail=f"CodeWhisperer error: {error_msg}")

    full_text = "".join(text_parts)

    return JSONResponse({
        "id": chat_id,
        "object": "chat.completion",
        "created": created,
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": full_text,
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": -1,  # Not available from CW
            "completion_tokens": -1,
            "total_tokens": -1,
        },
    })
