"""Agent API routes for kiro2chat — Strands Agent endpoints."""

import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/agent")

# Shared agent state
_agent: Any = None
_mcp_clients: list = []
_mcp_config: dict = {}


def init_agent_routes(agent: Any, mcp_clients: list, mcp_config: dict) -> None:
    """Initialize agent routes with shared agent instance."""
    global _agent, _mcp_clients, _mcp_config
    _agent = agent
    _mcp_clients = mcp_clients
    _mcp_config = mcp_config


@router.post("/chat")
async def agent_chat(request: Request):
    """Send a message to the Strands agent and get a response."""
    if _agent is None:
        raise HTTPException(status_code=503, detail="Agent not initialized")

    body = await request.json()
    message = body.get("message", "")
    if not message:
        raise HTTPException(status_code=400, detail="message is required")

    try:
        result = _agent(message)

        # Extract text content from result
        content = ""
        if hasattr(result, "message") and result.message:
            msg_content = result.message.get("content", "")
            if isinstance(msg_content, list):
                parts = []
                for block in msg_content:
                    if isinstance(block, dict) and block.get("text"):
                        parts.append(block["text"])
                content = "".join(parts)
            elif isinstance(msg_content, str):
                content = msg_content

        # Extract tool usage info
        tool_uses = []
        if hasattr(result, "message") and result.message:
            msg_content = result.message.get("content", "")
            if isinstance(msg_content, list):
                for block in msg_content:
                    if isinstance(block, dict) and block.get("toolUse"):
                        tool_uses.append({
                            "name": block["toolUse"].get("name", ""),
                            "input": block["toolUse"].get("input", {}),
                        })

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
    """List loaded MCP tools."""
    servers = _mcp_config.get("mcpServers", {})
    tools_info: list[dict] = []

    for name, cfg in servers.items():
        tools_info.append({
            "server": name,
            "command": cfg.get("command", ""),
            "args": cfg.get("args", []),
        })

    return {"servers": tools_info}


@router.post("/reload")
async def reload_tools():
    """Reload MCP tools from config."""
    from ..agent import load_mcp_config, create_mcp_clients, cleanup_mcp_clients

    global _agent, _mcp_clients, _mcp_config

    # Cleanup old clients
    cleanup_mcp_clients(_mcp_clients)

    # Reload
    _mcp_config = load_mcp_config()
    _mcp_clients = create_mcp_clients(_mcp_config)

    tools = []
    for client in _mcp_clients:
        try:
            client.__enter__()
            tools.extend(client.list_tools())
        except Exception as e:
            logger.error(f"Failed to start MCP client on reload: {e}")

    # Update agent tools
    if _agent is not None:
        _agent.tool_registry.process_tools(tools)

    return {
        "status": "ok",
        "servers": list(_mcp_config.get("mcpServers", {}).keys()),
        "tool_count": len(tools),
    }
