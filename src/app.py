"""kiro2chat - Main application entry point."""

import asyncio
import logging
import sys
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from . import __version__
from .config import config
from .core import TokenManager
from .core.client import KiroClient
from .api.routes import router, init_services
from .api.agent_routes import router as agent_router, init_agent_routes

# Configure logging
logging.basicConfig(
    level=getattr(logging, config.log_level.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
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
            client.__exit__(None, None, None)
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
    from .webui import create_ui
    demo = create_ui()
    demo.launch(server_name="0.0.0.0", server_port=7860)


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
