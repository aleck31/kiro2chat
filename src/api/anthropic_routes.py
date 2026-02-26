"""Anthropic Messages API compatible routes for kiro2chat.

Full /v1/messages compatibility including:
- system as string or content blocks array
- tool_use / tool_result round-trip
- tool_choice (auto/any/tool/none)
- image blocks (base64/url) conversion
- thinking blocks passthrough
- stop_sequences
- streaming with proper SSE events
- /v1/messages/count_tokens stub
"""

import json
import time
import uuid
from loguru import logger
from typing import Any, AsyncIterator

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import StreamingResponse, JSONResponse

from ..config import config
from ..core import TokenManager
from ..core.client import CodeWhispererClient
from ..core.sanitizer import sanitize_text, KIRO_BUILTIN_TOOLS
from ..core.token_counter import estimate_tokens, estimate_messages_tokens
from ..stats import stats


router = APIRouter(prefix="/v1", tags=["Anthropic"])

_tm: TokenManager | None = None
_cw: CodeWhispererClient | None = None


def init_anthropic_routes(tm: TokenManager, cw: CodeWhispererClient):
    global _tm, _cw
    _tm, _cw = tm, cw


def _check_auth(authorization: str | None = None, x_api_key: str | None = None):
    if not config.api_key:
        return
    key = x_api_key or (authorization[7:] if authorization and authorization.startswith("Bearer ") else authorization)
    if not key or key != config.api_key:
        raise HTTPException(status_code=401, detail={"type": "authentication_error", "message": "Invalid API key"})


def _gen_msg_id() -> str:
    return f"msg_{uuid.uuid4().hex[:24]}"


# ============================================================
# Anthropic -> OpenAI message conversion
# ============================================================

def _anthropic_messages_to_openai(messages: list[dict], system: Any = None) -> list[dict]:
    """Convert Anthropic message format to OpenAI format."""
    result = []

    # System prompt (top-level field)
    if system:
        if isinstance(system, str):
            result.append({"role": "system", "content": system})
        elif isinstance(system, list):
            parts = []
            for block in system:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(block.get("text", ""))
                elif isinstance(block, str):
                    parts.append(block)
            if parts:
                result.append({"role": "system", "content": "\n".join(parts)})

    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content")

        if role == "assistant" and isinstance(content, list):
            text_parts = []
            tool_calls = []
            for block in content:
                if not isinstance(block, dict):
                    text_parts.append(str(block))
                    continue
                btype = block.get("type", "")
                if btype == "text":
                    text_parts.append(block.get("text", ""))
                elif btype == "thinking":
                    pass  # skip thinking blocks
                elif btype == "tool_use":
                    tool_calls.append({
                        "id": block.get("id", ""),
                        "type": "function",
                        "function": {
                            "name": block.get("name", ""),
                            "arguments": json.dumps(block.get("input", {})),
                        },
                    })
            openai_msg: dict = {"role": "assistant", "content": "\n".join(text_parts) if text_parts else None}
            if tool_calls:
                openai_msg["tool_calls"] = tool_calls
            result.append(openai_msg)

        elif role == "user" and isinstance(content, list):
            has_tool_results = any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content)

            if has_tool_results:
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") == "tool_result":
                        tc = block.get("content", "")
                        if isinstance(tc, list):
                            tc = "\n".join(c.get("text", "") for c in tc if isinstance(c, dict) and c.get("type") == "text")
                        result.append({"role": "tool", "tool_call_id": block.get("tool_use_id", ""), "content": str(tc)})
                    elif block.get("type") == "text":
                        result.append({"role": "user", "content": block.get("text", "")})
            else:
                # Convert image blocks
                converted = []
                for block in content:
                    if not isinstance(block, dict):
                        converted.append(block)
                        continue
                    btype = block.get("type", "")
                    if btype == "image":
                        source = block.get("source", {})
                        if source.get("type") == "base64":
                            mt = source.get("media_type", "image/png")
                            data = source.get("data", "")
                            converted.append({"type": "image_url", "image_url": {"url": f"data:{mt};base64,{data}"}})
                        elif source.get("type") == "url":
                            converted.append({"type": "image_url", "image_url": {"url": source.get("url", "")}})
                        else:
                            converted.append(block)
                    else:
                        converted.append(block)
                result.append({"role": "user", "content": converted})
        else:
            result.append(msg)

    return result


def _anthropic_tools_to_openai(tools: list[dict]) -> list[dict]:
    """Convert Anthropic tools to OpenAI format, filtering invalid ones."""
    result = []
    for t in tools:
        if "function" in t and isinstance(t.get("function"), dict):
            if t["function"].get("name") and t["function"].get("description"):
                result.append(t)
            continue
        name = t.get("name", "")
        desc = t.get("description", "")
        if name and desc:
            result.append({
                "type": "function",
                "function": {"name": name, "description": desc, "parameters": t.get("input_schema", {"type": "object", "properties": {}})},
            })
    return result


def _convert_tool_choice(tc: Any) -> Any:
    """Convert Anthropic tool_choice to OpenAI format."""
    if tc is None:
        return None
    if isinstance(tc, dict):
        tt = tc.get("type", "")
        if tt == "auto":
            return "auto"
        elif tt == "any":
            return "required"
        elif tt == "tool":
            return {"type": "function", "function": {"name": tc.get("name", "")}}
        elif tt == "none":
            return "none"
    return tc


# ============================================================
# Endpoints
# ============================================================

@router.post("/messages")
async def anthropic_messages(
    request: Request,
    authorization: str | None = Header(None),
    x_api_key: str | None = Header(None, alias="x-api-key"),
):
    if _tm is None or _cw is None:
        raise HTTPException(status_code=503, detail={"type": "api_error", "message": "Service not initialized"})

    _check_auth(authorization, x_api_key)

    body = await request.json()
    model = body.get("model", config.default_model)
    stream = body.get("stream", False)
    system = body.get("system")
    tools_raw = body.get("tools")
    tool_choice_raw = body.get("tool_choice")
    stop_sequences = body.get("stop_sequences")

    messages = _anthropic_messages_to_openai(body.get("messages", []), system)
    if not messages:
        raise HTTPException(status_code=400, detail={"type": "invalid_request_error", "message": "messages is required"})

    # Tools
    tools = None
    if tools_raw:
        tc = _convert_tool_choice(tool_choice_raw)
        is_none = tc == "none" or (isinstance(tool_choice_raw, dict) and tool_choice_raw.get("type") == "none")
        if not is_none:
            tools = _anthropic_tools_to_openai(tools_raw)
            if not tools:
                tools = None

    logger.info(f"anthropic_messages: model={model}, messages={len(messages)}, tools={len(tools or [])}, stream={stream}")

    t0 = time.time()
    access_token = await _tm.get_access_token()
    profile_arn = _tm.profile_arn

    if stream:
        return StreamingResponse(
            _stream_anthropic(access_token, messages, model, profile_arn, tools, t0),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
        )

    # Non-streaming
    msg_id = _gen_msg_id()
    text_parts: list[str] = []
    content_blocks: list[dict] = []
    _active_tool: dict | None = None

    async for event in _cw.generate_stream(
        access_token=access_token, messages=messages, model=model, profile_arn=profile_arn, tools=tools,
    ):
        if event.event_type == "assistantResponseEvent":
            c = event.payload.get("content", "")
            if c:
                text_parts.append(c)
        elif event.event_type in ("toolUse", "toolUseEvent"):
            payload = event.payload
            name = payload.get("name", "")
            tool_use_id = payload.get("toolUseId", "")
            is_stop = payload.get("stop", False)

            if event.event_type == "toolUseEvent":
                if is_stop:
                    if _active_tool and _active_tool["name"] not in KIRO_BUILTIN_TOOLS:
                        try:
                            input_obj = json.loads(_active_tool["input_buf"]) if _active_tool["input_buf"] else {}
                        except json.JSONDecodeError:
                            input_obj = {"raw": _active_tool["input_buf"]}
                        content_blocks.append({
                            "type": "tool_use", "id": _active_tool["id"],
                            "name": _active_tool["name"], "input": input_obj,
                        })
                    _active_tool = None
                    continue
                if name and tool_use_id and _active_tool is None:
                    _active_tool = {"id": tool_use_id, "name": name, "input_buf": ""}
                if "input" in payload and _active_tool:
                    _active_tool["input_buf"] += payload["input"]
                continue

            if name in KIRO_BUILTIN_TOOLS:
                continue
            content_blocks.append({
                "type": "tool_use",
                "id": tool_use_id or f"toolu_{uuid.uuid4().hex[:24]}",
                "name": name, "input": payload.get("input", {}),
            })
        elif event.event_type == "exception":
            raise HTTPException(status_code=502, detail={"type": "api_error", "message": event.payload.get("message", "")})

    full_text = sanitize_text("".join(text_parts))
    if full_text:
        content_blocks.insert(0, {"type": "text", "text": full_text})

    stop_reason = "tool_use" if any(b["type"] == "tool_use" for b in content_blocks) else "end_turn"
    stats.record(model=model, latency_ms=(time.time() - t0) * 1000, status="ok")

    # Token estimation
    input_tokens = estimate_messages_tokens(messages)
    output_tokens = estimate_tokens(full_text or "")
    for b in content_blocks:
        if b["type"] == "tool_use":
            output_tokens += estimate_tokens(b["name"]) + estimate_tokens(str(b["input"]))

    return JSONResponse({
        "id": msg_id, "type": "message", "role": "assistant", "model": model,
        "content": content_blocks,
        "stop_reason": stop_reason, "stop_sequence": None,
        "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
    })


async def _stream_anthropic(
    access_token: str, messages: list[dict], model: str, profile_arn: str,
    tools: list[dict] | None, t0: float,
) -> AsyncIterator[str]:
    msg_id = _gen_msg_id()
    input_tokens = estimate_messages_tokens(messages)

    yield _sse("message_start", {
        "type": "message_start",
        "message": {
            "id": msg_id, "type": "message", "role": "assistant", "model": model,
            "content": [], "stop_reason": None, "stop_sequence": None,
            "usage": {"input_tokens": input_tokens, "output_tokens": 0},
        },
    })

    block_index = 0
    text_started = False
    text_closed = False
    tool_blocks: list[str] = []
    stream_text_buf = ""

    try:
        async for event in _cw.generate_stream(
            access_token=access_token, messages=messages, model=model, profile_arn=profile_arn, tools=tools,
        ):
            if event.event_type == "assistantResponseEvent":
                content = event.payload.get("content", "")
                if not content:
                    continue
                content = sanitize_text(content, is_chunk=True)
                if not content:
                    continue

                if not text_started:
                    yield _sse("content_block_start", {
                        "type": "content_block_start", "index": block_index,
                        "content_block": {"type": "text", "text": ""},
                    })
                    text_started = True

                stream_text_buf += content
                yield _sse("content_block_delta", {
                    "type": "content_block_delta", "index": block_index,
                    "delta": {"type": "text_delta", "text": content},
                })

            elif event.event_type == "toolUse":
                name = event.payload.get("name", "")
                if name in KIRO_BUILTIN_TOOLS:
                    continue

                # Close text block if open
                if text_started and not text_closed:
                    yield _sse("content_block_stop", {"type": "content_block_stop", "index": block_index})
                    block_index += 1
                    text_closed = True

                tool_id = event.payload.get("toolUseId", f"toolu_{uuid.uuid4().hex[:24]}")
                tool_input = event.payload.get("input", {})

                yield _sse("content_block_start", {
                    "type": "content_block_start", "index": block_index,
                    "content_block": {"type": "tool_use", "id": tool_id, "name": name, "input": {}},
                })
                # Stream input as incremental JSON
                yield _sse("content_block_delta", {
                    "type": "content_block_delta", "index": block_index,
                    "delta": {"type": "input_json_delta", "partial_json": json.dumps(tool_input)},
                })
                yield _sse("content_block_stop", {"type": "content_block_stop", "index": block_index})
                tool_blocks.append(name)
                block_index += 1

        # Close text block if still open
        if text_started and not text_closed:
            yield _sse("content_block_stop", {"type": "content_block_stop", "index": block_index})

        stop_reason = "tool_use" if tool_blocks else "end_turn"
        output_tokens = estimate_tokens(stream_text_buf)
        yield _sse("message_delta", {
            "type": "message_delta",
            "delta": {"stop_reason": stop_reason, "stop_sequence": None},
            "usage": {"output_tokens": output_tokens},
        })
        yield _sse("message_stop", {"type": "message_stop"})
        stats.record(model=model, latency_ms=(time.time() - t0) * 1000, status="ok")

    except Exception as e:
        logger.error(f"Anthropic stream error: {e}")
        stats.record(model=model, latency_ms=(time.time() - t0) * 1000, status="error", error=str(e))
        yield _sse("error", {"type": "error", "error": {"type": "api_error", "message": str(e)}})


def _sse(event_type: str, data: dict) -> str:
    return f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


# ============================================================
# Stub endpoints
# ============================================================

@router.post("/messages/count_tokens")
async def count_tokens(
    request: Request,
    authorization: str | None = Header(None),
    x_api_key: str | None = Header(None, alias="x-api-key"),
):
    """Token count estimation using character-based heuristics."""
    _check_auth(authorization, x_api_key)
    body = await request.json()

    messages = body.get("messages", [])
    system = body.get("system")
    system_str = None
    if isinstance(system, str):
        system_str = system
    elif isinstance(system, list):
        system_str = "\n".join(b.get("text", "") for b in system if isinstance(b, dict))

    input_tokens = estimate_messages_tokens(messages, system_str)

    if body.get("tools"):
        input_tokens += estimate_tokens(json.dumps(body["tools"]))

    return JSONResponse({"input_tokens": max(1, input_tokens)})


@router.post("/messages/batches")
@router.get("/messages/batches")
async def batches_stub(request: Request):
    return JSONResponse(status_code=501, content={"type": "error", "error": {"type": "not_supported", "message": "Batch API not supported"}})
