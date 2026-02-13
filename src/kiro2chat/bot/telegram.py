"""Telegram bot for kiro2chat."""

import os
import json
import logging
import re
from collections import defaultdict
from typing import Optional

import httpx
from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message
from aiogram.filters import Command
from aiogram.enums import ParseMode

logger = logging.getLogger(__name__)

API_BASE = "http://localhost:8000"
EDIT_INTERVAL = 15  # edit message every N chunks to avoid rate limits
MAX_HISTORY = 20  # max messages per user in history

router = Router()

# Per-user state
user_models: dict[int, str] = {}
user_histories: dict[int, list[dict]] = defaultdict(list)


def _get_models() -> list[str]:
    try:
        resp = httpx.get(f"{API_BASE}/v1/models", timeout=5)
        resp.raise_for_status()
        return [m["id"] for m in resp.json()["data"]]
    except Exception:
        return ["claude-sonnet-4-20250514"]


def _clean_response(text: str) -> str:
    """Remove raw tool call XML/markup from response text for display."""
    # Remove <function_calls>...</function_calls> blocks
    text = re.sub(r"<function_calls>.*?</function_calls>", "", text, flags=re.DOTALL)
    # Remove <invoke>...</invoke> blocks
    text = re.sub(r"<invoke.*?</invoke>", "", text, flags=re.DOTALL)
    # Remove <invoke>...</invoke> blocks
    text = re.sub(r"<invoke.*?</invoke>", "", text, flags=re.DOTALL)
    # Remove <tool_call>...</tool_call> blocks
    text = re.sub(r"<tool_call>.*?</tool_call>", "", text, flags=re.DOTALL)
    # Clean up excessive whitespace
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


def _add_to_history(user_id: int, role: str, content: str, tool_calls: list | None = None):
    """Add a message to user's conversation history."""
    msg: dict = {"role": role, "content": content}
    if tool_calls:
        msg["tool_calls"] = tool_calls
    user_histories[user_id].append(msg)
    # Trim history
    if len(user_histories[user_id]) > MAX_HISTORY:
        user_histories[user_id] = user_histories[user_id][-MAX_HISTORY:]


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
    user_id = message.from_user.id
    user_histories[user_id] = []
    await message.answer("🗑 对话历史已清空")


@router.message(Command("model"))
async def cmd_model(message: Message):
    args = (message.text or "").split(maxsplit=1)
    models = _get_models()

    if len(args) < 2:
        current = user_models.get(message.from_user.id, models[0] if models else "?")
        model_list = "\n".join(f"• `{m}`" for m in models)
        await message.answer(
            f"Current model: `{current}`\n\nAvailable:\n{model_list}\n\n"
            f"Set with: `/model <name>`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    chosen = args[1].strip()
    if chosen not in models:
        await message.answer(f"Unknown model `{chosen}`", parse_mode=ParseMode.MARKDOWN)
        return

    user_models[message.from_user.id] = chosen
    await message.answer(f"✅ Model set to `{chosen}`", parse_mode=ParseMode.MARKDOWN)


@router.message(F.text)
async def handle_message(message: Message):
    user_id = message.from_user.id
    models = _get_models()
    model = user_models.get(user_id, models[0] if models else "claude-sonnet-4-20250514")

    reply = await message.answer("⏳ Thinking...")

    # Add user message to history
    _add_to_history(user_id, "user", message.text)

    # Build messages from history
    messages = [
        {"role": m["role"], "content": m["content"]}
        for m in user_histories[user_id]
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

                    # Collect text content
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

                    # Collect tool calls
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

        # Clean text content
        clean_text = _clean_response(full)
        if clean_text:
            display_parts.append(clean_text)

        # Format tool calls
        if tool_calls_collected:
            tool_summary = _format_tool_calls(tool_calls_collected)
            display_parts.append(f"\n{tool_summary}")

        display = "\n".join(display_parts) if display_parts else "(empty response)"

        # Save assistant response to history
        _add_to_history(user_id, "assistant", full)

        try:
            await reply.edit_text(display[:4096])
        except Exception:
            pass

    except Exception as e:
        logger.error(f"Chat error: {e}")
        # Remove the failed user message from history
        if user_histories[user_id] and user_histories[user_id][-1]["role"] == "user":
            user_histories[user_id].pop()
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
    logger.info("🤖 Telegram bot starting...")
    await dp.start_polling(bot)


def main():
    """Launch bot standalone."""
    import asyncio
    asyncio.run(run_bot())


if __name__ == "__main__":
    main()
