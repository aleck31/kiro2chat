"""Telegram bot for kiro2chat."""

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
# In private chats: chat_id == user_id
# In groups: each user has their own session per group
SessionKey = tuple[int, int]

# Per-session state
session_models: dict[SessionKey, str] = {}
session_histories: dict[SessionKey, list[dict]] = defaultdict(list)

# Per-session locks to prevent message ordering issues
session_locks: dict[SessionKey, asyncio.Lock] = defaultdict(asyncio.Lock)

# Curated model list for TG menu (short names only, no date aliases)
MENU_MODELS = [
    "claude-opus-4-6",
    "claude-opus-4-5",
    "claude-sonnet-4-5",
    "claude-sonnet-4",
    "claude-3.7-sonnet",
    "claude-haiku-4-5",
]


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


def _format_tool_calls(tool_calls: list[dict]) -> str:
    """Format tool calls into a readable summary."""
    parts = []
    for tc in tool_calls:
        fn = tc.get("function", {})
        name = fn.get("name", "unknown")
        args = fn.get("arguments", "{}")
        try:
            args_obj = json.loads(args) if isinstance(args, str) else args
            args_short = ", ".join(f"{k}={v!r}" for k, v in list(args_obj.items())[:3])
            if len(args_obj) > 3:
                args_short += ", ..."
        except Exception:
            args_short = args[:50] if len(args) > 50 else args
        parts.append(f"🔧 {name}({args_short})")
    return "\n".join(parts)


def _add_to_history(key: SessionKey, role: str, content: str, tool_calls: list | None = None):
    """Add a message to session's conversation history."""
    msg: dict = {"role": role, "content": content}
    if tool_calls:
        msg["tool_calls"] = tool_calls
    session_histories[key].append(msg)
    if len(session_histories[key]) > MAX_HISTORY:
        session_histories[key] = session_histories[key][-MAX_HISTORY:]


@router.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(
        "👋 Hi! I'm kiro2chat — send me a message and I'll reply with Claude.\n\n"
        "Commands:\n"
        "/model — switch model\n"
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
        "/clear — clear conversation history\n"
        "/help — show this help",
        parse_mode=ParseMode.MARKDOWN,
    )


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
        current = session_models.get(key, "claude-sonnet-4-5")
        model_list = "\n".join(f"• `{m}`" for m in MENU_MODELS)
        await message.answer(
            f"Current model: `{current}`\n\nAvailable:\n{model_list}\n\n"
            f"Set with: `/model <name>`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    chosen = args[1].strip()
    all_models = list(_get_models())
    if chosen not in all_models:
        await message.answer(f"Unknown model `{chosen}`", parse_mode=ParseMode.MARKDOWN)
        return

    session_models[key] = chosen
    await message.answer(f"✅ Model set to `{chosen}`", parse_mode=ParseMode.MARKDOWN)


@router.message(F.text)
async def handle_message(message: Message):
    key = _session_key(message)
    model = session_models.get(key, "claude-sonnet-4-5")

    # Acquire per-session lock to ensure message ordering
    lock = session_locks[key]
    if lock.locked():
        await message.reply("⏳ 上一条消息还在处理中，请稍候...")
        # Wait for the lock instead of dropping the message
        async with lock:
            pass
        # Now re-acquire for this message

    async with lock:
        reply = await message.answer("⏳ Thinking...")

        _add_to_history(key, "user", message.text)

        messages = [
            {"role": m["role"], "content": m["content"]}
            for m in session_histories[key]
        ]

        full = ""
        tool_calls_collected: list[dict] = []
        chunk_count = 0

        try:
            async with httpx.AsyncClient(timeout=120) as client:
                async with client.stream(
                    "POST",
                    f"{API_BASE}/v1/chat/completions",
                    json={"model": model, "messages": messages, "stream": True},
                ) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        data = line[6:]
                        if data == "[DONE]":
                            break
                        chunk = json.loads(data)
                        choice = chunk["choices"][0]
                        delta = choice.get("delta", {})

                        content = delta.get("content", "")
                        if content:
                            full += content
                            chunk_count += 1
                            if chunk_count % EDIT_INTERVAL == 0:
                                display = _clean_response(full)
                                if display:
                                    try:
                                        await reply.edit_text(display[:4096] or "...")
                                    except Exception:
                                        pass

                        if "tool_calls" in delta:
                            for tc in delta["tool_calls"]:
                                idx = tc.get("index", 0)
                                while len(tool_calls_collected) <= idx:
                                    tool_calls_collected.append({
                                        "id": "", "type": "function",
                                        "function": {"name": "", "arguments": ""}
                                    })
                                if tc.get("id"):
                                    tool_calls_collected[idx]["id"] = tc["id"]
                                fn = tc.get("function", {})
                                if fn.get("name"):
                                    tool_calls_collected[idx]["function"]["name"] = fn["name"]
                                if fn.get("arguments"):
                                    tool_calls_collected[idx]["function"]["arguments"] += fn["arguments"]

            # Build final display
            display_parts = []
            clean_text = _clean_response(full)
            if clean_text:
                display_parts.append(clean_text)
            if tool_calls_collected:
                display_parts.append(f"\n{_format_tool_calls(tool_calls_collected)}")

            display = "\n".join(display_parts) if display_parts else "(empty response)"

            _add_to_history(key, "assistant", full)

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


async def run_bot():
    """Start the Telegram bot (blocks until stopped)."""
    token = get_bot_token()
    if not token:
        logger.warning("TG_BOT_TOKEN not set, skipping Telegram bot")
        return

    bot = Bot(token=token)
    dp = Dispatcher()
    dp.include_router(router)

    # Register bot commands menu
    await bot.set_my_commands([
        BotCommand(command="model", description="切换/查看模型"),
        BotCommand(command="clear", description="清空对话历史"),
        BotCommand(command="help", description="帮助信息"),
    ])

    logger.info("🤖 Telegram bot starting...")
    await dp.start_polling(bot)


def main():
    """Launch bot standalone."""
    asyncio.run(run_bot())


if __name__ == "__main__":
    main()
