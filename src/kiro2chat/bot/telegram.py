"""Telegram bot for kiro2chat."""

import os
import json
import logging
from typing import Optional

import httpx
from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message
from aiogram.filters import Command
from aiogram.enums import ParseMode

logger = logging.getLogger(__name__)

API_BASE = "http://localhost:8000"
EDIT_INTERVAL = 15  # edit message every N chunks to avoid rate limits

router = Router()

# Per-user model selection
user_models: dict[int, str] = {}


def _get_models() -> list[str]:
    try:
        resp = httpx.get(f"{API_BASE}/v1/models", timeout=5)
        resp.raise_for_status()
        return [m["id"] for m in resp.json()["data"]]
    except Exception:
        return ["claude-sonnet-4-20250514"]


@router.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(
        "👋 Hi! I'm kiro2chat — send me a message and I'll reply with Claude.\n\n"
        "Commands:\n"
        "/model — switch model\n"
        "/help — show this help"
    )


@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "🤖 **kiro2chat Telegram Bot**\n\n"
        "Just send a text message to chat with Claude.\n\n"
        "/model `<name>` — set model (e.g. `/model claude-sonnet-4`)\n"
        "/model — list available models\n"
        "/help — show this help",
        parse_mode=ParseMode.MARKDOWN,
    )


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
    models = _get_models()
    model = user_models.get(message.from_user.id, models[0] if models else "claude-sonnet-4-20250514")

    reply = await message.answer("⏳ Thinking...")

    messages = [{"role": "user", "content": message.text}]
    full = ""
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
                    delta = chunk["choices"][0]["delta"].get("content", "")
                    if delta:
                        full += delta
                        chunk_count += 1
                        if chunk_count % EDIT_INTERVAL == 0:
                            try:
                                await reply.edit_text(full[:4096] or "...")
                            except Exception:
                                pass

        if full:
            try:
                await reply.edit_text(full[:4096])
            except Exception:
                pass
        else:
            await reply.edit_text("(empty response)")

    except Exception as e:
        logger.error(f"Chat error: {e}")
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
