"""kiro2chat - Main application entry point."""

import asyncio
import logging
import os
import sys
from contextlib import asynccontextmanager

# Ensure non-interactive tool execution (must be set before any imports that read them)
os.environ.setdefault("AWS_PAGER", "")
os.environ.setdefault("STRANDS_NON_INTERACTIVE", "true")

import uvicorn
from fastapi import FastAPI

from . import __version__
from .config import config
from .core import TokenManager
from .core.client import KiroClient
from .api.routes import router, init_services
from .api.agent_routes import router as agent_router, init_agent_routes

# Configure logging
from pathlib import Path
from logging.handlers import RotatingFileHandler
from .log_context import UserTagFilter

_log_fmt = "%(asctime)s [%(levelname)s] %(name)s%(user_tag)s: %(message)s"
_user_filter = UserTagFilter()

# Console handler — follows LOG_LEVEL
_console = logging.StreamHandler()
_console.setLevel(getattr(logging, config.log_level.upper(), logging.INFO))
_console.setFormatter(logging.Formatter(_log_fmt))
_console.addFilter(_user_filter)

# File handler — always DEBUG, 20MB × 10 files
_log_dir = Path(__file__).resolve().parent.parent / "logs"
_log_dir.mkdir(parents=True, exist_ok=True)
_file = RotatingFileHandler(
    _log_dir / "kiro2chat.log", maxBytes=20 * 1024 * 1024, backupCount=10, encoding="utf-8",
)
_file.setLevel(logging.DEBUG)
_file.setFormatter(logging.Formatter(_log_fmt))
_file.addFilter(_user_filter)

logging.basicConfig(level=logging.DEBUG, handlers=[_console, _file])
# Suppress overly verbose third-party debug logs
logging.getLogger("openai._base_client").setLevel(logging.INFO)     # drops per-request options dump
logging.getLogger("strands.models.openai").setLevel(logging.INFO)   # drops "formatted request" dump
logging.getLogger("strands.tools.registry").setLevel(logging.WARNING)  # drops per-tool "loaded tool config" x30
logging.getLogger("httpcore").setLevel(logging.INFO)                # drops GeneratorExit false-failure noise
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: init and cleanup."""
    tm = TokenManager()
    kiro = KiroClient()
    init_services(tm, kiro)

    try:
        token = await tm.get_access_token()
        logger.info(f"✅ Token valid, profile: {tm.profile_arn}")
    except Exception as e:
        logger.error(f"❌ Token validation failed: {e}")
        logger.error("Make sure kiro-cli is logged in: kiro-cli login")

    # Initialize Strands Agent
    mcp_clients = []
    try:
        from .agent import create_agent
        from .config_manager import load_mcp_config
        mcp_config = load_mcp_config()
        agent, mcp_clients = create_agent(mcp_config=mcp_config)
        init_agent_routes(agent, mcp_clients, mcp_config)
        logger.info("✅ Strands Agent initialized")
    except Exception as e:
        logger.warning(f"⚠️ Agent init skipped: {e}")

    yield

    # Cleanup MCP clients
    for client in mcp_clients:
        try:
            client.stop(None, None, None)
        except Exception:
            pass
    await tm.close()
    await kiro.close()


app = FastAPI(
    title="kiro2chat",
    description="Kiro to Chat - OpenAI-compatible API powered by Kiro/CodeWhisperer",
    version=__version__,
    lifespan=lifespan,
)

app.include_router(router)
app.include_router(agent_router)


@app.get("/")
async def root():
    return {
        "name": "kiro2chat",
        "version": __version__,
        "status": "running",
        "endpoints": {
            "models": "/v1/models",
            "chat": "/v1/chat/completions",
            "agent_chat": "/v1/agent/chat",
            "agent_tools": "/v1/agent/tools",
        },
    }


def run_api():
    """Run the API server."""
    uvicorn.run(
        "src.app:app",
        host=config.host,
        port=config.port,
        log_level=config.log_level,
    )


def run_webui():
    """Run the Gradio Web UI."""
    from .webui import create_ui, LAUNCH_KWARGS
    demo = create_ui()
    demo.launch(**LAUNCH_KWARGS)


def run_bot():
    """Run the Telegram bot."""
    from .bot.telegram import run_bot as _run_bot
    asyncio.run(_run_bot())


def run_all():
    """Run API + WebUI + Bot together."""
    import threading
    from .bot.telegram import get_bot_token

    # Start API in a thread
    api_thread = threading.Thread(
        target=uvicorn.run,
        kwargs={
            "app": "src.app:app",
            "host": config.host,
            "port": config.port,
            "log_level": config.log_level,
        },
        daemon=True,
    )
    api_thread.start()
    logger.info("🚀 API server starting on port %d", config.port)

    # Start bot in a thread if token is available (no signal handling in sub-thread)
    if get_bot_token():
        def _run_bot_no_signals():
            from .bot.telegram import run_bot as _run_bot
            asyncio.run(_run_bot(handle_signals=False))

        bot_thread = threading.Thread(target=_run_bot_no_signals, daemon=True)
        bot_thread.start()
        logger.info("🤖 Telegram bot starting")
    else:
        logger.info("⏭️ TG_BOT_TOKEN not set, skipping Telegram bot")

    # Run WebUI in main thread (blocking)
    logger.info("🌐 Web UI starting on port 7860")
    run_webui()


USAGE = """\
Usage: kiro2chat [command]

Commands:
  api     Start the API server (default)
  webui   Start the Gradio Web UI
  bot     Start the Telegram bot
  all     Start API + Web UI + Bot together

Options:
  -h, --help  Show this help
"""


def main():
    args = sys.argv[1:]
    cmd = args[0] if args else "api"

    if cmd in ("-h", "--help", "help"):
        print(USAGE)
    elif cmd == "api":
        run_api()
    elif cmd == "webui":
        run_webui()
    elif cmd == "bot":
        run_bot()
    elif cmd == "all":
        run_all()
    else:
        print(f"Unknown command: {cmd}\n")
        print(USAGE)
        sys.exit(1)


if __name__ == "__main__":
    main()
