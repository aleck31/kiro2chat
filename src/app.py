"""kiro2chat - Main application entry point."""

import asyncio
import sys
import signal
import uuid
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse as _JSONResponse

from . import __version__
from .config import config
from .core import TokenManager
from .core.client import CodeWhispererClient
from .api.routes import router, init_services
from .api.agent_routes import router as agent_router, init_agent_routes
from .api.anthropic_routes import router as anthropic_router, init_anthropic_routes

# Configure loguru
from . import log  # noqa: F401 — initializes loguru
from loguru import logger

# Module-level refs for health check
token_manager: "TokenManager | None" = None
cw_client: "CodeWhispererClient | None" = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: init and cleanup."""
    global token_manager, cw_client
    tm = TokenManager()
    cw = CodeWhispererClient()
    token_manager = tm
    cw_client = cw
    init_services(tm, cw)
    init_anthropic_routes(tm, cw)

    try:
        token = await tm.get_access_token()
        logger.info(f"✅ Token valid, profile: {tm.profile_arn}")
    except Exception as e:
        logger.error(f"❌ Token validation failed: {e}")
        logger.error("Make sure kiro-cli is logged in: kiro-cli login")

    # Initialize Strands Agent
    mcp_clients = []
    try:
        from .agent import create_agent, load_mcp_config
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
    await cw.close()


app = FastAPI(
    title="kiro2chat",
    description="""
## Kiro → Standard API Gateway

Wrap Kiro CLI's Claude Opus 4.6 backend into a fully compatible OpenAI + Anthropic API Gateway.

### Endpoints
- **OpenAI**: `/v1/chat/completions`, `/v1/models`
- **Anthropic**: `/v1/messages`, `/v1/messages/count_tokens`
- **Monitoring**: `/health`, `/metrics`

### Features
- Dual protocol (OpenAI + Anthropic)
- Claude Opus 4.6 1M context window
- Full tool calling with MCP support
- Image recognition
- System prompt sanitization
- Token usage estimation (tiktoken)
""",
    version=__version__,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS
from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
app.include_router(agent_router)
app.include_router(anthropic_router)


# Request ID + Metrics middleware
from .metrics import REQUEST_COUNT, REQUEST_LATENCY, ACTIVE_REQUESTS, SERVICE_INFO, get_metrics, get_content_type
import time as _time

SERVICE_INFO.info({"version": __version__, "backend": "claude-opus-4.6-1m"})

@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    request_id = request.headers.get("x-request-id", str(uuid.uuid4())[:8])
    ACTIVE_REQUESTS.inc()
    start = _time.time()
    try:
        response = await call_next(request)
        REQUEST_COUNT.labels(
            endpoint=request.url.path, method=request.method, status=response.status_code,
        ).inc()
        REQUEST_LATENCY.labels(endpoint=request.url.path).observe(_time.time() - start)
        response.headers["x-request-id"] = request_id
        return response
    except Exception:
        REQUEST_COUNT.labels(endpoint=request.url.path, method=request.method, status=500).inc()
        raise
    finally:
        ACTIVE_REQUESTS.dec()


@app.get("/metrics")
async def prometheus_metrics():
    from fastapi.responses import Response
    return Response(content=get_metrics(), media_type=get_content_type())


# Global exception handlers
from fastapi.responses import JSONResponse as _JSONResponse

@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    detail = exc.detail if isinstance(exc.detail, dict) else {"error": {"message": str(exc.detail)}}
    return _JSONResponse(status_code=exc.status_code, content=detail)

@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    logger.exception("Unhandled exception")
    return _JSONResponse(status_code=500, content={"error": {"message": "Internal server error", "type": "internal_error"}})


@app.get("/")
async def root():
    return {
        "name": "kiro2chat",
        "version": __version__,
        "status": "running",
        "backend_model": "claude-opus-4.6-1m",
        "endpoints": {
            "openai_chat": "/v1/chat/completions",
            "openai_models": "/v1/models",
            "anthropic_messages": "/v1/messages",
            "agent_chat": "/v1/agent/chat",
            "agent_tools": "/v1/agent/tools",
            "health": "/health",
        },
    }


@app.get("/health")
async def health():
    """Health check endpoint for monitoring and load balancers."""
    from .core.health import check_health
    return await check_health(token_manager, cw_client)


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
