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


def _snapshot_loaded_tools(mcp_config: dict, mcp_clients: list) -> list[dict]:
    """Build a snapshot of actually loaded MCP tools from running clients."""
    servers = mcp_config.get("mcpServers", {})
    # Only include stdio servers (matching the filter in create_mcp_clients)
    stdio_names = [
        name for name, cfg in servers.items()
        if cfg.get("type", "stdio") not in ("http", "sse") and cfg.get("command", "")
    ]
    result = []
    for i, client in enumerate(mcp_clients):
        name = stdio_names[i] if i < len(stdio_names) else f"server-{i}"
        cfg = servers.get(name, {})
        try:
            tools = client.list_tools_sync()
            result.append({
                "server": name,
                "command": cfg.get("command", ""),
                "args": cfg.get("args", []),
                "tools": [t.tool_name for t in tools],
                "tool_count": len(tools),
                "status": "ok",
            })
        except Exception as e:
            result.append({
                "server": name,
                "command": cfg.get("command", ""),
                "args": cfg.get("args", []),
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


async def _stream_agent_sse(message: str) -> AsyncIterator[str]:
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
        async for event in _agent.stream_async(message):
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

            # Tool result
            if "current_tool_use_result" in event:
                result = event["current_tool_use_result"]
                sse = json.dumps({
                    "type": "tool_end",
                    "result": str(result)[:500],  # Truncate long results
                }, ensure_ascii=False)
                yield f"data: {sse}\n\n"

            # Final result
            if "result" in event:
                agent_result = event["result"]
                stop_reason = getattr(agent_result, "stop_reason", "end_turn")
                latency_ms = (time.time() - t0) * 1000

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
    if _agent is None:
        raise HTTPException(status_code=503, detail="Agent not initialized")

    body = await request.json()
    message = body.get("message", "")
    stream = body.get("stream", False)
    model_id = body.get("model")

    if not message:
        raise HTTPException(status_code=400, detail="message is required")

    if model_id:
        from ..agent import create_model
        _agent.model = create_model(model_id=model_id)

    if stream:
        return StreamingResponse(
            _stream_agent_sse(message),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    # Non-streaming: use async to avoid blocking the event loop
    try:
        result = await _agent.invoke_async(message)

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
    """Reload MCP tools from config."""
    from ..agent import create_mcp_clients, cleanup_mcp_clients
    from ..config_manager import load_mcp_config

    global _mcp_clients, _mcp_config, _loaded_mcp_tools

    cleanup_mcp_clients(_mcp_clients)

    _mcp_config = load_mcp_config()
    _mcp_clients = create_mcp_clients(_mcp_config)

    tools = []
    for client in _mcp_clients:
        try:
            client.start()
            tools.extend(client.list_tools_sync())
        except Exception as e:
            logger.error(f"Failed to start MCP client on reload: {e}")

    if _agent is not None:
        _agent.tool_registry.process_tools(tools)

    _loaded_mcp_tools = _snapshot_loaded_tools(_mcp_config, _mcp_clients)

    return {
        "status": "ok",
        "servers": list(_mcp_config.get("mcpServers", {}).keys()),
        "tool_count": len(tools),
    }
