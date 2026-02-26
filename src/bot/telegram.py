"""Telegram bot for kiro2chat — powered by Strands Agent."""

import asyncio
import os
import json
import logging
import re
from collections import defaultdict
from typing import Optional

import httpx
from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message, BotCommand
from aiogram.filters import Command
from aiogram.enums import ParseMode

logger = logging.getLogger(__name__)

API_BASE = "http://localhost:8000"
EDIT_INTERVAL = 15  # edit message every N chunks to avoid rate limits
MAX_HISTORY = 20  # max messages per session in history

router = Router()

# Session key = (chat_id, user_id) for group isolation
SessionKey = tuple[int, int]

# Per-session state
session_models: dict[SessionKey, str] = {}
session_histories: dict[SessionKey, list[dict]] = defaultdict(list)

# Per-session locks to prevent message ordering issues
session_locks: dict[SessionKey, asyncio.Lock] = defaultdict(asyncio.Lock)

def _session_key(message: Message) -> SessionKey:
    """Get session key: (chat_id, user_id) for group isolation."""
    return (message.chat.id, message.from_user.id)


def _get_models() -> list[str]:
    try:
        resp = httpx.get(f"{API_BASE}/v1/models", timeout=5)
        resp.raise_for_status()
        return [m["id"] for m in resp.json()["data"]]
    except Exception:
        return ["claude-sonnet-4-5"]


def _clean_response(text: str) -> str:
    """Remove raw tool call XML/markup from response text for display."""
    text = re.sub(r"<function_calls>.*?</function_calls>", "", text, flags=re.DOTALL)
    text = re.sub(r"<invoke.*?</invoke>", "", text, flags=re.DOTALL)
    text = re.sub(r"<tool_call>.*?</tool_call>", "", text, flags=re.DOTALL)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _brief_tool_input(name: str, inp) -> str:
    """Return a short one-line summary of tool input for status display."""
    if isinstance(inp, str):
        try:
            inp = __import__("json").loads(inp)
        except Exception:
            return inp[:80]
    if not isinstance(inp, dict):
        return str(inp)[:80]
    if name == "shell":
        cmd = inp.get("command", "")
        if isinstance(cmd, list):
            cmd = cmd[0] if cmd else ""
        return f"`{str(cmd)[:80]}`"
    if name in ("file_read", "file_write"):
        return f"`{inp.get('path', '')}`"
    if name == "calculator":
        return f"`{inp.get('expression', '')}`"
    if name in ("web_search_exa", "get_code_context_exa"):
        return inp.get("query", "")[:60]
    if name == "company_research_exa":
        return inp.get("companyName", "")[:60]
    if name == "http_request":
        return f"{inp.get('method','GET')} {inp.get('url','')[:60]}"
    # Generic: show first key=value
    if inp:
        k, v = next(iter(inp.items()))
        return f"{k}={str(v)[:40]}"
    return ""


def _format_tool_uses(tool_uses: list[dict]) -> str:
    """Format agent tool uses into a readable summary."""
    parts = []
    for tu in tool_uses:
        name = tu.get("name", "unknown")
        brief = _brief_tool_input(name, tu.get("input", {}))
        parts.append(f"🔧 {name}" + (f"  {brief}" if brief else ""))
    return "\n".join(parts)


def _add_to_history(key: SessionKey, role: str, content: str):
    """Add a message to session's conversation history."""
    session_histories[key].append({"role": role, "content": content})
    if len(session_histories[key]) > MAX_HISTORY:
        session_histories[key] = session_histories[key][-MAX_HISTORY:]


@router.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(
        "👋 Hi! I'm kiro2chat — send me a message and I'll reply with Claude.\n\n"
        "Commands:\n"
        "/model — switch model\n"
        "/tools — view loaded tools\n"
        "/clear — clear conversation history\n"
        "/help — show this help"
    )


@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "🤖 **kiro2chat Telegram Bot**\n\n"
        "Just send a text message to chat with Claude.\n\n"
        "/model `<name>` — set model\n"
        "/model — list available models\n"
        "/tools — view loaded tools\n"
        "/clear — clear conversation history\n"
        "/help — show this help",
        parse_mode=ParseMode.MARKDOWN,
    )


@router.message(Command("tools"))
async def cmd_tools(message: Message):
    """Show loaded built-in and MCP tools."""
    from .._tool_names import BUILTIN_TOOL_NAMES

    lines = ["🛠 **已加载的工具**\n"]

    lines.append("**内置工具:**")
    for name in BUILTIN_TOOL_NAMES:
        lines.append(f"  • `{name}`")

    from ..config_manager import load_mcp_config
    mcp_cfg = load_mcp_config()
    servers = mcp_cfg.get("mcpServers", {})
    if servers:
        lines.append(f"\n**MCP 服务 ({len(servers)}):**")
        for name, cfg in servers.items():
            cmd = cfg.get("command", "?")
            args = " ".join(cfg.get("args", [])[:2])
            lines.append(f"  • `{name}` — {cmd} {args}")
    else:
        lines.append("\n**MCP 服务:** (无)")

    await message.answer("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


@router.message(Command("clear"))
async def cmd_clear(message: Message):
    key = _session_key(message)
    session_histories[key] = []
    await message.answer("🗑 对话历史已清空")


@router.message(Command("model"))
async def cmd_model(message: Message):
    key = _session_key(message)
    args = (message.text or "").split(maxsplit=1)

    if len(args) < 2:
        current = session_models.get(key, "claude-sonnet-4-6 (Krio)")
        models = _get_models()
        model_list = "\n".join(f"• `{m}`" for m in models)
        await message.answer(
            f"Current model: `{current}`\n\nAvailable:\n{model_list}\n\n"
            f"Set with: `/model <name>`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    chosen = args[1].strip()
    if chosen not in set(_get_models()):
        await message.answer(f"Unknown model `{chosen}`", parse_mode=ParseMode.MARKDOWN)
        return

    session_models[key] = chosen
    await message.answer(f"✅ Model set to `{chosen}`", parse_mode=ParseMode.MARKDOWN)


@router.message(F.text)
async def handle_message(message: Message):
    key = _session_key(message)

    # Acquire per-session lock to ensure message ordering
    lock = session_locks[key]
    if lock.locked():
        await message.reply("⏳ 上一条消息还在处理中，请稍候...")
        async with lock:
            pass

    async with lock:
        reply = await message.answer("⏳ Thinking...")

        _add_to_history(key, "user", message.text or "")

        full_text = ""
        tool_uses: list[dict] = []
        chunk_count = 0

        try:
            # Stream through Strands Agent
            async with httpx.AsyncClient(timeout=120) as client:
                async with client.stream(
                    "POST",
                    f"{API_BASE}/v1/agent/chat",
                    json={"message": message.text, "stream": True, "model": session_models.get(key)},
                ) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        data_str = line[6:]
                        if data_str == "[DONE]":
                            break

                        try:
                            event = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue

                        evt_type = event.get("type", "")

                        if evt_type == "data":
                            full_text += event.get("content", "")
                            chunk_count += 1
                            if chunk_count % EDIT_INTERVAL == 0:
                                display = _clean_response(full_text)
                                if display:
                                    try:
                                        await reply.edit_text(display[:4096] or "...")
                                    except Exception:
                                        pass

                        elif evt_type == "tool_start":
                            name = event.get("name", "")
                            inp = event.get("input", {})
                            tool_uses.append({"name": name, "input": inp})
                            brief = _brief_tool_input(name, inp)
                            tool_line = f"🔧 {name}: {brief}..." if brief else f"🔧 {name}..."
                            current = _clean_response(full_text)
                            preview = f"{current}\n\n{tool_line}" if current else tool_line
                            try:
                                await reply.edit_text(preview[:4096])
                            except Exception:
                                pass

                        elif evt_type == "error":
                            error_msg = event.get("message", "Unknown error")
                            try:
                                await reply.edit_text(f"❌ {error_msg}")
                            except Exception:
                                pass

            # Build final display
            display_parts = []
            clean_text = _clean_response(full_text)
            if clean_text:
                display_parts.append(clean_text)
            if tool_uses:
                display_parts.append(f"\n{_format_tool_uses(tool_uses)}")

            display = "\n".join(display_parts) if display_parts else "(empty response)"

            _add_to_history(key, "assistant", full_text)

            try:
                await reply.edit_text(display[:4096])
            except Exception:
                pass

        except Exception as e:
            logger.error(f"Chat error: {e}")
            if session_histories[key] and session_histories[key][-1]["role"] == "user":
                session_histories[key].pop()
            try:
                await reply.edit_text(f"❌ Error: {e}")
            except Exception:
                pass


def get_bot_token() -> Optional[str]:
    return os.environ.get("TG_BOT_TOKEN")


async def run_bot(handle_signals: bool = True):
    """Start the Telegram bot (blocks until stopped)."""
    token = get_bot_token()
    if not token:
        logger.warning("TG_BOT_TOKEN not set, skipping Telegram bot")
        return

    bot = Bot(token=token)
    dp = Dispatcher()
    dp.include_router(router)

    await bot.set_my_commands([
        BotCommand(command="model", description="切换/查看模型"),
        BotCommand(command="tools", description="查看已加载工具"),
        BotCommand(command="clear", description="清空对话历史"),
        BotCommand(command="help", description="帮助信息"),
    ])

    logger.info("🤖 Telegram bot starting...")
    await dp.start_polling(bot, handle_signals=handle_signals)


def main():
    """Launch bot standalone."""
    asyncio.run(run_bot())


if __name__ == "__main__":
    main()
