"""Strands Agents integration for kiro2chat.

Provides an AI agent backed by kiro2chat's OpenAI-compatible API,
with MCP tool support loaded from ~/.config/kiro2chat/mcp.json.
"""

import json
from loguru import logger
from pathlib import Path
from typing import Any
from mcp.client.stdio import StdioServerParameters, stdio_client
from strands import Agent
from strands.models.openai import OpenAIModel
from strands.tools.mcp import MCPClient
from strands_tools import calculator, file_read, file_write, http_request, shell


MCP_CONFIG_PATH = Path.home() / ".config" / "kiro2chat" / "mcp.json"

# Built-in tools from strands-agents-tools
BUILTIN_TOOLS = [calculator, file_read, file_write, http_request, shell]

DEFAULT_SYSTEM_PROMPT = """\
You are kiro2chat, an AI assistant powered by Claude via Kiro/CodeWhisperer.

You have real tools at your disposal — check your tool specifications to see what's available, and use them proactively when they'd help.

## How you work
- Be concise and direct. Prioritize actionable information.
- When a task can be done with your tools, just do it — don't ask permission for routine operations.
- Show results, not just descriptions of what you did.
- If a tool call fails, explain what went wrong and try alternatives.
- Adapt to the user's language (Chinese or English).

## Important
- Only use tools that are actually available in your tool specifications.
- Do NOT hallucinate tool names or capabilities you don't have.
- Do NOT output raw XML, function_calls tags, or other markup — use tools through the proper tool calling mechanism.
"""


def load_mcp_config() -> dict[str, Any]:
    """Load MCP server configuration from ~/.config/kiro2chat/mcp.json."""
    if not MCP_CONFIG_PATH.exists():
        return {"mcpServers": {}}
    try:
        return json.loads(MCP_CONFIG_PATH.read_text())
    except Exception as e:
        logger.error(f"Failed to load MCP config: {e}")
        return {"mcpServers": {}}


def save_mcp_config(config: dict[str, Any]) -> None:
    """Save MCP server configuration to ~/.config/kiro2chat/mcp.json."""
    MCP_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    MCP_CONFIG_PATH.write_text(json.dumps(config, indent=2, ensure_ascii=False))


def create_mcp_clients(mcp_config: dict[str, Any] | None = None) -> list[MCPClient]:
    """Create MCPClient instances from config."""
    if mcp_config is None:
        mcp_config = load_mcp_config()

    clients: list[MCPClient] = []
    servers = mcp_config.get("mcpServers", {})

    for name, server_cfg in servers.items():
        # Only stdio-based servers are supported; skip http/sse types
        server_type = server_cfg.get("type", "stdio")
        if server_type in ("http", "sse"):
            logger.info(f"⏭️ Skipping MCP server '{name}' (type={server_type}, not supported)")
            continue

        command = server_cfg.get("command", "")
        if not command:
            logger.warning(f"⏭️ Skipping MCP server '{name}' (no command specified)")
            continue

        args = server_cfg.get("args", [])
        env = server_cfg.get("env") or None

        try:
            params = StdioServerParameters(command=command, args=args, env=env)
            client = MCPClient(lambda params=params: stdio_client(params))
            clients.append(client)
            logger.info(f"✅ MCP server configured: {name} ({command} {' '.join(args)})")
        except Exception as e:
            logger.error(f"❌ Failed to configure MCP server '{name}': {e}")

    return clients


def create_model(
    api_base: str = "http://localhost:8000/v1",
    model_id: str = "claude-sonnet-4-20250514",
) -> OpenAIModel:
    """Create an OpenAI-compatible model pointing at kiro2chat's API."""
    return OpenAIModel(
        model_id=model_id,
        client_args={
            "api_key": "not-needed",
            "base_url": api_base,
        },
    )


def create_agent(
    system_prompt: str = DEFAULT_SYSTEM_PROMPT,
    api_base: str = "http://localhost:8000/v1",
    model_id: str = "claude-sonnet-4-20250514",
    mcp_config: dict[str, Any] | None = None,
    load_tools: bool = True,
) -> tuple[Agent, list[MCPClient]]:
    """Create a Strands Agent with OpenAI-compatible model and MCP tools.

    Returns:
        Tuple of (agent, mcp_clients) — caller must manage MCP client lifecycle.
    """
    model = create_model(api_base=api_base, model_id=model_id)

    mcp_clients: list[MCPClient] = []
    tools: list[Any] = list(BUILTIN_TOOLS)  # Start with built-in tools

    if load_tools:
        mcp_clients = create_mcp_clients(mcp_config)
        # Start MCP clients and collect tools
        for client in mcp_clients:
            try:
                client.start()
                tools.extend(client.list_tools_sync())
            except Exception as e:
                logger.error(f"❌ Failed to start MCP client: {e}")

    agent = Agent(
        model=model,
        system_prompt=system_prompt,
        tools=tools if tools else None,
        callback_handler=None,  # Use stream_async() for streaming
    )

    return agent, mcp_clients


def cleanup_mcp_clients(clients: list[MCPClient]) -> None:
    """Cleanup MCP client connections."""
    for client in clients:
        try:
            client.stop(None, None, None)
        except Exception as e:
            logger.error(f"Error cleaning up MCP client: {e}")


