"""Strands Agents integration for kiro2chat.

Provides an AI agent backed by kiro2chat's OpenAI-compatible API,
with MCP tool support loaded from ~/.config/kiro2chat/mcp.json.
"""

import json
import logging
from pathlib import Path
from typing import Any, Generator

from strands import Agent
from strands.models.litellm import LiteLLMModel
from strands.tools.mcp import MCPClient
from strands_tools import calculator, file_read, file_write, http_request, shell

logger = logging.getLogger(__name__)

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
        command = server_cfg.get("command", "")
        args = server_cfg.get("args", [])
        env = server_cfg.get("env", {})

        try:
            client = MCPClient(
                command=command,
                args=args,
                env=env if env else None,
            )
            clients.append(client)
            logger.info(f"✅ MCP server configured: {name} ({command} {' '.join(args)})")
        except Exception as e:
            logger.error(f"❌ Failed to configure MCP server '{name}': {e}")

    return clients


def create_model(
    api_base: str = "http://localhost:8000/v1",
    model_id: str = "openai/claude-sonnet-4-20250514",
) -> LiteLLMModel:
    """Create a LiteLLM model pointing at kiro2chat's API."""
    return LiteLLMModel(
        model_id=model_id,
        client_args={
            "api_key": "not-needed",
            "base_url": api_base,
        },
    )


def create_agent(
    system_prompt: str = DEFAULT_SYSTEM_PROMPT,
    api_base: str = "http://localhost:8000/v1",
    model_id: str = "openai/claude-sonnet-4-20250514",
    mcp_config: dict[str, Any] | None = None,
    load_tools: bool = True,
) -> tuple[Agent, list[MCPClient]]:
    """Create a Strands Agent with LiteLLM model and MCP tools.

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
                client.__enter__()
                tools.extend(client.list_tools())
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
            client.__exit__(None, None, None)
        except Exception as e:
            logger.error(f"Error cleaning up MCP client: {e}")


def interactive_chat(
    system_prompt: str = DEFAULT_SYSTEM_PROMPT,
    api_base: str = "http://localhost:8000/v1",
    model_id: str = "openai/claude-sonnet-4-20250514",
) -> None:
    """Run an interactive terminal chat session with the agent."""
    mcp_config = load_mcp_config()
    servers = mcp_config.get("mcpServers", {})

    print("🤖 kiro2chat Agent — Interactive Mode")
    print(f"   Model: {model_id}")
    print(f"   API: {api_base}")
    print(f"   Built-in tools: {', '.join(t.__name__ if hasattr(t, '__name__') else str(t) for t in BUILTIN_TOOLS)}")

    if servers:
        print(f"   MCP Servers: {', '.join(servers.keys())}")
    else:
        print("   MCP Servers: (none configured)")

    print("   Type 'quit' or 'exit' to stop.\n")

    agent, mcp_clients = create_agent(
        system_prompt=system_prompt,
        api_base=api_base,
        model_id=model_id,
        mcp_config=mcp_config,
    )

    try:
        while True:
            try:
                user_input = input("\n👤 You: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n\n👋 Bye!")
                break

            if not user_input:
                continue
            if user_input.lower() in ("quit", "exit"):
                print("👋 Bye!")
                break

            print("\n🤖 Agent: ", end="", flush=True)
            try:
                result = agent(user_input)
                # If streaming didn't print inline, print the result
                if hasattr(result, "message") and result.message:
                    content = result.message.get("content", "")
                    if isinstance(content, list):
                        for block in content:
                            if isinstance(block, dict) and block.get("text"):
                                print(block["text"], end="")
                    elif isinstance(content, str):
                        print(content, end="")
                print()
            except Exception as e:
                print(f"\n❌ Error: {e}")
    finally:
        cleanup_mcp_clients(mcp_clients)
