"""Agent API routes for kiro2chat — Strands Agent streaming endpoints."""

import json
import logging
import time
from typing import Any, AsyncIterator

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/agent")

# Shared agent state
_agent: Any = None
_mcp_clients: list = []
_mcp_config: dict = {}
_loaded_mcp_tools: list[dict] = []  # Actual loaded tools per server


def _snapshot_loaded_tools(servers: dict, mcp_clients: list) -> list[dict]:
    """Build a snapshot of actually loaded MCP tools from running clients."""
    names = list(servers.keys())
    result = []
    for i, client in enumerate(mcp_clients):
        name = names[i] if i < len(names) else f"server-{i}"
        cfg = servers.get(name, {})
        server_type = cfg.get("type", "stdio")
        try:
            tools = client.list_tools_sync()
            result.append({
                "server": name,
                "type": server_type,
                "tools": [t.tool_name for t in tools],
                "tool_count": len(tools),
                "status": "ok",
            })
        except Exception as e:
            result.append({
                "server": name,
                "type": server_type,
                "tools": [],
                "tool_count": 0,
                "status": f"error: {e}",
            })
    return result


def init_agent_routes(agent: Any, mcp_clients: list, mcp_config: dict) -> None:
    """Initialize agent routes with shared agent instance."""
    global _agent, _mcp_clients, _mcp_config, _loaded_mcp_tools
    _agent = agent
    _mcp_clients = mcp_clients
    _mcp_config = mcp_config
    _loaded_mcp_tools = _snapshot_loaded_tools(mcp_config, mcp_clients)


async def _stream_agent_sse(prompt) -> AsyncIterator[str]:
    """Stream agent response as SSE events.

    Event types:
      - data: text chunk from model
      - tool_start: tool invocation started (name, input)
      - tool_end: tool invocation completed (name, result summary)
      - done: final result with metadata
      - error: error occurred
    """
    text_buffer = ""
    tool_uses: list[dict] = []
    t0 = time.time()

    try:
        async for event in _agent.stream_async(prompt):
            if not isinstance(event, dict):
                continue

            # Text chunk from model
            if "data" in event:
                chunk = event["data"]
                text_buffer += chunk
                sse = json.dumps({"type": "data", "content": chunk}, ensure_ascii=False)
                yield f"data: {sse}\n\n"

            # Tool use detection
            if "current_tool_use" in event:
                tool_info = event["current_tool_use"]
                if isinstance(tool_info, dict):
                    name = tool_info.get("name", "")
                    tool_input = tool_info.get("input", {})
                    if name:
                        tool_uses.append({"name": name, "input": tool_input})
                        sse = json.dumps({
                            "type": "tool_start",
                            "name": name,
                            "input": tool_input,
                        }, ensure_ascii=False)
                        yield f"data: {sse}\n\n"

            # Tool result — extracted from message events with role=user containing toolResult
            if "message" in event:
                msg = event["message"]
                if isinstance(msg, dict) and msg.get("role") == "user":
                    for block in msg.get("content", []):
                        if isinstance(block, dict) and "toolResult" in block:
                            tr = block["toolResult"]
                            sse = json.dumps({
                                "type": "tool_end",
                                "tool_use_id": tr.get("toolUseId", ""),
                                "status": tr.get("status", ""),
                                "content": tr.get("structuredContent") or str(tr.get("content", ""))[:500],
                            }, ensure_ascii=False)
                            yield f"data: {sse}\n\n"

            # Final result
            if "result" in event:
                agent_result = event["result"]
                stop_reason = getattr(agent_result, "stop_reason", "end_turn")
                latency_ms = (time.time() - t0) * 1000
                logger.info(f"🤖 Agent response: stop={stop_reason}, tools_used={[t['name'] for t in tool_uses]}, text_len={len(text_buffer)}, latency={latency_ms:.0f}ms")

                sse = json.dumps({
                    "type": "done",
                    "stop_reason": stop_reason,
                    "tool_uses": tool_uses,
                    "latency_ms": round(latency_ms, 1),
                }, ensure_ascii=False)
                yield f"data: {sse}\n\n"

    except Exception as e:
        logger.error(f"Agent stream error: {e}")
        sse = json.dumps({"type": "error", "message": str(e)}, ensure_ascii=False)
        yield f"data: {sse}\n\n"

    yield "data: [DONE]\n\n"


@router.post("/chat")
async def agent_chat(request: Request):
    """Send a message to the Strands agent.

    Supports both streaming (SSE) and non-streaming responses.
    Set stream=true in the request body for SSE streaming.
    """
    from ..log_context import user_tag
    # Set user tag for logging context
    client_tag = request.headers.get("x-user-tag")
    if not client_tag:
        client_ip = request.client.host if request.client else "unknown"
        client_tag = f"api:{client_ip}"
    user_tag.set(client_tag)

    if _agent is None:
        raise HTTPException(status_code=503, detail="Agent not initialized")

    body = await request.json()
    message = body.get("message", "")
    stream = body.get("stream", False)
    model_id = body.get("model")
    images = body.get("images", [])  # list of {"data": base64, "format": "png"|"jpeg"}

    if not message and not images:
        raise HTTPException(status_code=400, detail="message or images required")

    # Build prompt: string or ContentBlock list for multimodal
    if images:
        import base64
        prompt: list[dict] = []
        if message:
            prompt.append({"text": message})
        for img in images:
            prompt.append({
                "image": {
                    "format": img.get("format", "jpeg"),
                    "source": {"bytes": base64.b64decode(img["data"])},
                }
            })
    else:
        prompt = message

    if model_id:
        from ..agent import create_model
        _agent.model = create_model(model_id=model_id)

    if stream:
        return StreamingResponse(
            _stream_agent_sse(prompt),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    # Non-streaming: use async to avoid blocking the event loop
    try:
        result = await _agent.invoke_async(prompt)

        content = ""
        tool_uses = []

        if hasattr(result, "message") and result.message:
            msg_content = result.message.get("content", "")
            if isinstance(msg_content, list):
                for block in msg_content:
                    if isinstance(block, dict):
                        if block.get("text"):
                            content += block["text"]
                        if block.get("toolUse"):
                            tool_uses.append({
                                "name": block["toolUse"].get("name", ""),
                                "input": block["toolUse"].get("input", {}),
                            })
            elif isinstance(msg_content, str):
                content = msg_content

        return {
            "content": content,
            "tool_uses": tool_uses,
            "stop_reason": getattr(result, "stop_reason", "end_turn"),
        }

    except Exception as e:
        logger.error(f"Agent chat error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tools")
async def list_tools():
    """List actually loaded tools (built-in + MCP)."""
    from .._tool_names import BUILTIN_TOOL_NAMES

    builtin = [{"name": n, "source": "builtin"} for n in BUILTIN_TOOL_NAMES]

    return {
        "builtin": builtin,
        "mcp": _loaded_mcp_tools,
        "total_mcp_tools": sum(s.get("tool_count", 0) for s in _loaded_mcp_tools),
    }


@router.post("/reload")
async def reload_tools():
    """Reload MCP tools from config, preserving agent conversation history."""
    from ..agent import cleanup_mcp_clients, get_enabled_servers, create_mcp_clients
    from .._tool_names import BUILTIN_TOOL_NAMES

    global _mcp_clients, _mcp_config, _loaded_mcp_tools

    cleanup_mcp_clients(_mcp_clients)

    _mcp_config = get_enabled_servers()
    _mcp_clients = create_mcp_clients(_mcp_config)

    # Collect new MCP tools
    new_mcp_tools = []
    for client in _mcp_clients:
        try:
            client.start()
            new_mcp_tools.extend(client.list_tools_sync())
        except Exception as e:
            logger.error(f"Failed to start MCP client on reload: {e}")

    # Rebuild agent tool registry: keep builtins, replace MCP tools
    builtin_names = set(BUILTIN_TOOL_NAMES)
    registry = _agent.tool_registry.registry
    # Remove old MCP tools
    for name in list(registry.keys()):
        if name not in builtin_names:
            del registry[name]
    # Register new MCP tools
    for tool in new_mcp_tools:
        _agent.tool_registry.register_tool(tool)

    _loaded_mcp_tools = _snapshot_loaded_tools(_mcp_config, _mcp_clients)

    return {
        "status": "ok",
        "servers": list(_mcp_config.keys()),
        "tool_count": len(new_mcp_tools),
    }
