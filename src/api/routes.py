"""OpenAI-compatible API routes."""

import json
import time
import uuid
from loguru import logger
from typing import AsyncIterator

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import StreamingResponse, JSONResponse

from ..config import config
from ..core import TokenManager
from ..core.client import CodeWhispererClient
from ..core.sanitizer import sanitize_text, KIRO_BUILTIN_TOOLS
from ..core.token_counter import estimate_tokens, estimate_messages_tokens
from ..stats import stats
from ..metrics import TOKENS_INPUT, TOKENS_OUTPUT, TOOL_CALLS, ERRORS


router = APIRouter(prefix="/v1", tags=["OpenAI"])

token_manager: TokenManager | None = None
cw_client: CodeWhispererClient | None = None


def init_services(tm: TokenManager, cw: CodeWhispererClient):
    global token_manager, cw_client
    token_manager = tm
    cw_client = cw


def _check_auth(authorization: str | None = None, x_api_key: str | None = None):
    if not config.api_key:
        return
    key = None
    if authorization and authorization.startswith("Bearer "):
        key = authorization[7:]
    elif x_api_key:
        key = x_api_key
    if key != config.api_key:
        raise HTTPException(status_code=401, detail={"error": {"message": "Invalid API key", "type": "authentication_error"}})


def _is_valid_tool(tool: dict) -> bool:
    """Check if a tool definition has required non-empty fields."""
    fn = tool.get("function")
    if fn and isinstance(fn, dict):
        return bool(fn.get("name")) and bool(fn.get("description"))
    if tool.get("name") and tool.get("description"):
        return True
    return False


def _filter_valid_tools(tools: list[dict]) -> list[dict]:
    """Filter out tools with empty/missing name or description."""
    return [t for t in tools if _is_valid_tool(t)]


@router.get("/models")
async def list_models(
    authorization: str | None = Header(None),
    x_api_key: str | None = Header(None, alias="x-api-key"),
):
    _check_auth(authorization, x_api_key)
    now = int(time.time())
    models = []
    for name in config.model_map:
        models.append({
            "id": name, "object": "model", "created": now, "owned_by": "anthropic",
            "root": "claude-opus-4.6-1m", "parent": None,
            "capabilities": {"vision": True, "function_calling": True},
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
    tool_choice = body.get("tool_choice")
    stream_options = body.get("stream_options") or {}

    if not messages:
        raise HTTPException(status_code=400, detail={"error": {"message": "messages is required"}})

    # Filter and validate tools
    if tools:
        tools = _filter_valid_tools(tools)
        # tool_choice=none means don't use tools
        if tool_choice == "none":
            tools = None
            tool_choice = None
        if not tools:
            tools = None

    logger.info(f"chat_completions: model={model}, messages={len(messages)}, tools={len(tools or [])}, stream={stream}")

    t0 = time.time()
    access_token = await token_manager.get_access_token()
    profile_arn = token_manager.profile_arn

    # Build extra kwargs for converter (temperature, top_p, stop, etc.)
    extra = {}
    for key in ("temperature", "top_p", "stop", "presence_penalty", "frequency_penalty"):
        if key in body and body[key] is not None:
            extra[key] = body[key]

    if stream:
        return StreamingResponse(
            _stream_response(access_token, messages, model, profile_arn, tools, t0,
                             include_usage=stream_options.get("include_usage", False)),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
        )
    else:
        return await _non_stream_response(access_token, messages, model, profile_arn, tools, t0)


def _make_chunk(chat_id: str, created: int, model: str, delta: dict,
                finish_reason: str | None = None, usage: dict | None = None) -> str:
    chunk = {
        "id": chat_id, "object": "chat.completion.chunk", "created": created, "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
    }
    if usage is not None:
        chunk["usage"] = usage
    return f"data: {json.dumps(chunk)}\n\n"


MAX_CONTINUATIONS = 5  # Auto-continue up to 5 times on truncation


async def _stream_response(
    access_token: str, messages: list[dict], model: str, profile_arn: str,
    tools: list[dict] | None, t0: float, include_usage: bool = False,
) -> AsyncIterator[str]:
    chat_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
    created = int(time.time())
    tool_calls_seen: list[dict] = []
    tool_call_index = 0
    stream_text_buf = ""
    # Track streaming toolUseEvent aggregation
    _active_tool: dict | None = None  # {id, name, input_buf}
    output_truncated = False
    continuation_count = 0
    current_messages = messages

    try:
        async for event in cw_client.generate_stream(
            access_token=access_token, messages=messages, model=model,
            profile_arn=profile_arn, tools=tools,
        ):
            if event.event_type == "assistantResponseEvent":
                content = event.payload.get("content", "")
                if content:
                    content = sanitize_text(content, is_chunk=True)
                    if content:
                        stream_text_buf += content
                        yield _make_chunk(chat_id, created, model, {"content": content})

            elif event.event_type in ("toolUse", "toolUseEvent"):
                payload = event.payload
                name = payload.get("name", "")
                tool_use_id = payload.get("toolUseId", "")
                is_stop = payload.get("stop", False)

                # toolUseEvent comes in streaming chunks: first has name+id, subsequent have input fragments, last has stop=true
                if event.event_type == "toolUseEvent":
                    if is_stop:
                        # Finalize the active tool
                        if _active_tool and _active_tool["name"] not in KIRO_BUILTIN_TOOLS:
                            try:
                                input_obj = json.loads(_active_tool["input_buf"]) if _active_tool["input_buf"] else {}
                            except json.JSONDecodeError:
                                input_obj = {"raw": _active_tool["input_buf"]}
                            arguments = json.dumps(input_obj)
                            # Emit name chunk
                            tc_base = {"index": tool_call_index, "id": _active_tool["id"], "type": "function",
                                       "function": {"name": _active_tool["name"], "arguments": ""}}
                            yield _make_chunk(chat_id, created, model, {"tool_calls": [tc_base]})
                            # Emit arguments in incremental chunks (~40 chars each)
                            for i in range(0, len(arguments), 40):
                                tc_args = {"index": tool_call_index, "function": {"arguments": arguments[i:i+40]}}
                                yield _make_chunk(chat_id, created, model, {"tool_calls": [tc_args]})
                            tool_calls_seen.append(_active_tool["name"])
                            tool_call_index += 1
                        _active_tool = None
                        continue

                    if name and tool_use_id and _active_tool is None:
                        # First chunk — start tracking
                        _active_tool = {"id": tool_use_id, "name": name, "input_buf": ""}
                    if "input" in payload and _active_tool:
                        _active_tool["input_buf"] += payload["input"]
                    continue

                # Legacy toolUse (single event with complete data)
                if name in KIRO_BUILTIN_TOOLS:
                    continue
                tool_input = payload.get("input", {})
                arguments = json.dumps(tool_input) if not isinstance(tool_input, str) else tool_input
                tc_id = tool_use_id or f"call_{uuid.uuid4().hex[:24]}"
                tc_base = {"index": tool_call_index, "id": tc_id, "type": "function",
                           "function": {"name": name, "arguments": ""}}
                yield _make_chunk(chat_id, created, model, {"tool_calls": [tc_base]})
                for i in range(0, len(arguments), 40):
                    tc_args = {"index": tool_call_index, "function": {"arguments": arguments[i:i+40]}}
                    yield _make_chunk(chat_id, created, model, {"tool_calls": [tc_args]})
                tool_calls_seen.append(name)
                tool_call_index += 1

            elif event.event_type in ("supplementaryWebLinksEvent", "meteringEvent"):
                pass

            elif event.event_type == "contextUsageEvent":
                pct = event.payload.get("contextUsagePercentage", 0)
                if pct > 0.95:
                    output_truncated = True

            elif event.event_type == "exception":
                error_msg = event.payload.get("message", str(event.payload))
                yield _make_chunk(chat_id, created, model, {"content": f"\n\n[Error: {error_msg}]"}, finish_reason="stop")

        # Auto-continue if truncated and no tool calls
        if output_truncated and not tool_calls_seen and continuation_count < MAX_CONTINUATIONS:
            continuation_count += 1
            logger.info(f"Auto-continuing ({continuation_count}/{MAX_CONTINUATIONS}), accumulated {len(stream_text_buf)} chars")
            output_truncated = False
            _active_tool = None
            
            # Build continuation request with accumulated text as history
            cont_messages = [
                {"role": "user", "content": current_messages[0].get("content", "") if current_messages else ""},
                {"role": "assistant", "content": stream_text_buf[-4000:]},
                {"role": "user", "content": "Your previous output was cut off mid-stream. Continue EXACTLY from the last character. Do not repeat anything. Do not add commentary. Just continue the code/text output until it is complete."},
            ]
            # Prepend system messages
            sys_msgs = [m for m in current_messages if m.get("role") in ("system", "developer")]
            cont_messages = sys_msgs + cont_messages
            
            async for event in cw_client.generate_stream(
                access_token=access_token, messages=cont_messages, model=model,
                profile_arn=profile_arn, tools=None,
            ):
                if event.event_type == "assistantResponseEvent":
                    content = event.payload.get("content", "")
                    if content:
                        content = sanitize_text(content, is_chunk=True)
                        if content:
                            stream_text_buf += content
                            yield _make_chunk(chat_id, created, model, {"content": content})
                elif event.event_type == "contextUsageEvent":
                    if event.payload.get("contextUsagePercentage", 0) > 0.95:
                        output_truncated = True

            # If still truncated after this continuation, loop will catch it next time
            # But we need to recurse — for simplicity, just check once more
            if output_truncated and continuation_count < MAX_CONTINUATIONS:
                # One more round
                continuation_count += 1
                logger.info(f"Auto-continuing again ({continuation_count}/{MAX_CONTINUATIONS})")
                output_truncated = False
                cont_messages[-2] = {"role": "assistant", "content": stream_text_buf[-4000:]}
                async for event in cw_client.generate_stream(
                    access_token=access_token, messages=cont_messages, model=model,
                    profile_arn=profile_arn, tools=None,
                ):
                    if event.event_type == "assistantResponseEvent":
                        content = event.payload.get("content", "")
                        if content:
                            content = sanitize_text(content, is_chunk=True)
                            if content:
                                stream_text_buf += content
                                yield _make_chunk(chat_id, created, model, {"content": content})
                    elif event.event_type == "contextUsageEvent":
                        if event.payload.get("contextUsagePercentage", 0) > 0.95:
                            output_truncated = True

        finish_reason = "tool_calls" if tool_calls_seen else ("length" if output_truncated else "stop")
        yield _make_chunk(chat_id, created, model, {}, finish_reason=finish_reason)

        # Usage chunk if requested
        if include_usage:
            prompt_tokens = estimate_messages_tokens(messages)
            completion_tokens = estimate_tokens(stream_text_buf)
            yield _make_chunk(chat_id, created, model, {}, usage={
                "prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            })

        yield "data: [DONE]\n\n"
        stats.record(model=model, latency_ms=(time.time() - t0) * 1000, status="ok")

    except Exception as e:
        logger.error(f"Stream error: {e}")
        stats.record(model=model, latency_ms=(time.time() - t0) * 1000, status="error", error=str(e))
        yield _make_chunk(chat_id, created, model, {"content": f"\n\n[Error: {e}]"}, finish_reason="stop")
        yield "data: [DONE]\n\n"


async def _non_stream_response(
    access_token: str, messages: list[dict], model: str, profile_arn: str,
    tools: list[dict] | None, t0: float,
) -> JSONResponse:
    chat_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
    created = int(time.time())
    text_parts: list[str] = []
    tool_calls: list[dict] = []
    tool_call_index = 0
    _active_tool: dict | None = None
    output_truncated = False

    async for event in cw_client.generate_stream(
        access_token=access_token, messages=messages, model=model,
        profile_arn=profile_arn, tools=tools,
    ):
        if event.event_type == "assistantResponseEvent":
            content = event.payload.get("content", "")
            if content:
                text_parts.append(content)
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
                        tool_calls.append({
                            "index": tool_call_index, "id": _active_tool["id"], "type": "function",
                            "function": {"name": _active_tool["name"], "arguments": json.dumps(input_obj)},
                        })
                        tool_call_index += 1
                    _active_tool = None
                    continue
                if name and tool_use_id and _active_tool is None:
                    _active_tool = {"id": tool_use_id, "name": name, "input_buf": ""}
                if "input" in payload and _active_tool:
                    _active_tool["input_buf"] += payload["input"]
                continue

            # Legacy toolUse
            if name in KIRO_BUILTIN_TOOLS:
                continue
            tool_input = payload.get("input", {})
            arguments = json.dumps(tool_input) if not isinstance(tool_input, str) else tool_input
            tool_calls.append({
                "index": tool_call_index, "id": tool_use_id or f"call_{uuid.uuid4().hex[:24]}", "type": "function",
                "function": {"name": name, "arguments": arguments},
            })
            tool_call_index += 1
        elif event.event_type == "contextUsageEvent":
            if event.payload.get("contextUsagePercentage", 0) > 0.95:
                output_truncated = True
        elif event.event_type == "exception":
            raise HTTPException(status_code=502, detail={"error": {"message": event.payload.get("message", ""), "type": "upstream_error"}})

    full_text = sanitize_text("".join(text_parts))
    finish_reason = "tool_calls" if tool_calls else ("length" if output_truncated else "stop")

    message: dict = {"role": "assistant", "content": full_text or None}
    if tool_calls:
        message["tool_calls"] = tool_calls

    # Token estimation
    prompt_tokens = estimate_messages_tokens(messages)
    completion_tokens = estimate_tokens(full_text or "")
    if tool_calls:
        for tc in tool_calls:
            completion_tokens += estimate_tokens(tc["function"]["name"]) + estimate_tokens(tc["function"]["arguments"])

    latency = (time.time() - t0) * 1000
    stats.record(model=model, latency_ms=latency, status="ok")
    TOKENS_INPUT.inc(prompt_tokens)
    TOKENS_OUTPUT.inc(completion_tokens)

    return JSONResponse({
        "id": chat_id, "object": "chat.completion", "created": created, "model": model,
        "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
        "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens, "total_tokens": prompt_tokens + completion_tokens},
    })
