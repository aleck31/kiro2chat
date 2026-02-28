"""Strands Agents integration for kiro2chat.

Provides an AI agent backed by kiro2chat's OpenAI-compatible API, with MCP tool support. 
"""

import json
import logging
from pathlib import Path
from typing import Any
from strands import Agent
from strands.models.openai import OpenAIModel
from strands.tools.mcp import MCPClient
from strands_tools import calculator, file_read, file_write, http_request, shell
from .config import config as _config

logger = logging.getLogger(__name__)

MCP_CONFIG_PATH = Path.home() / ".config" / "kiro2chat" / "mcp.json"

# Built-in tools from strands-agents-tools
BUILTIN_TOOLS = [calculator, file_read, file_write, http_request, shell]

DEFAULT_SYSTEM_PROMPT = """\
You are Kiro, an AI assistant powered by Claude. You are running as a chatbot (Telegram or Web UI) with real tools at your disposal, including shell execution capabilities.

You talk like a human, not like a bot. You reflect the user's input style in your responses.

## How you work
- Be concise and direct. Lose the fluff. Prioritize actionable information over explanations.
- When a task can be done with your tools, just do it — don't ask permission for routine operations.
- For maximum efficiency, invoke independent tools simultaneously rather than sequentially.
- Show results, not just descriptions of what you did.
- If a tool call fails, explain what went wrong and try alternatives.
- Adapt to the user's language (Chinese or English).
- When generating files (images, documents, etc.), save them to {output_dir} directory.
"""


def get_enabled_server_names() -> list[str]:
    """Get list of enabled MCP server names from config.toml [mcp] section."""
    from .config_manager import load_config_file
    cfg = load_config_file()
    return cfg.get("enabled_mcp_servers", [])


def set_enabled_mcp_servers(names: list[str]) -> None:
    """Save enabled MCP server names to config.toml [mcp] section."""
    from .config_manager import load_config_file, save_config_file
    cfg = load_config_file()
    cfg["enabled_mcp_servers"] = names
    save_config_file(cfg)


def get_enabled_servers() -> dict[str, Any]:
    """Return server configs for enabled MCP servers.

    Reads available servers from Kiro CLI + kiro2chat's own mcp.json,
    filters by enabled list in config.toml. Opt-in model.
    """
    from .config_manager import load_mcp_config as load_kiro_mcp

    # Merge all available servers: Kiro CLI + kiro2chat own
    all_servers: dict[str, Any] = {}
    kiro_cfg = load_kiro_mcp()
    all_servers.update(kiro_cfg.get("mcpServers", {}))
    if MCP_CONFIG_PATH.exists():
        try:
            own_cfg = json.loads(MCP_CONFIG_PATH.read_text())
            all_servers.update(own_cfg.get("mcpServers", {}))
        except Exception as e:
            logger.error(f"Failed to load {MCP_CONFIG_PATH}: {e}")

    enabled = get_enabled_server_names()
    if not enabled:
        return {}

    return {name: cfg for name, cfg in all_servers.items() if name in enabled}


def create_mcp_clients(servers: dict[str, Any] | None = None) -> list[MCPClient]:
    """Create MCPClient instances from enabled servers (stdio, http, sse)."""
    from mcp.client.stdio import StdioServerParameters, stdio_client  # lazy to avoid circular import with gradio

    if servers is None:
        servers = get_enabled_servers()

    clients: list[MCPClient] = []

    for name, server_cfg in servers.items():
        server_type = server_cfg.get("type", "stdio")

        try:
            if server_type in ("http", "sse"):
                url = server_cfg.get("url", "")
                if not url:
                    logger.warning(f"⏭️ Skipping MCP server '{name}' (type={server_type}, no url)")
                    continue
                if server_type == "http":
                    from mcp.client.streamable_http import streamablehttp_client
                    client = MCPClient(lambda url=url: streamablehttp_client(url=url))
                else:
                    from mcp.client.sse import sse_client
                    client = MCPClient(lambda url=url: sse_client(url=url))
                clients.append(client)
                logger.debug(f"✅ MCP server configured: {name} ({server_type} → {url})")
                continue

            # stdio type
            command = server_cfg.get("command", "")
            if not command:
                logger.warning(f"⏭️ Skipping MCP server '{name}' (no command specified)")
                continue

            args = server_cfg.get("args", [])
            env = server_cfg.get("env") or None
            params = StdioServerParameters(command=command, args=args, env=env)
            client = MCPClient(lambda params=params: stdio_client(params))
            clients.append(client)
            logger.debug(f"✅ MCP server configured: {name} ({command} {' '.join(args)})")
        except Exception as e:
            logger.error(f"❌ Failed to configure MCP server '{name}': {e}")

    return clients


def create_model(
    api_base: str = "http://localhost:8000/v1",
    model_id: str = _config.default_model,
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
    model_id: str = _config.default_model,
    servers: dict[str, Any] | None = None,
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
        mcp_clients = create_mcp_clients(servers)
        # Start MCP clients and collect tools
        for client in mcp_clients:
            try:
                client.start()
                tools.extend(client.list_tools_sync())
            except Exception as e:
                logger.error(f"❌ Failed to start MCP client: {e}")

    # Resolve output directory in system prompt
    output_dir = _config.data_dir / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    resolved_prompt = system_prompt.format(output_dir=output_dir)

    from strands.agent.conversation_manager.sliding_window_conversation_manager import SlidingWindowConversationManager
    agent = Agent(
        model=model,
        system_prompt=resolved_prompt,
        tools=tools if tools else None,
        conversation_manager=SlidingWindowConversationManager(window_size=20),
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


