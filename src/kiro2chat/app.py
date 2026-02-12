"""kiro2chat - Main application entry point."""

import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from .config import config
from .core import TokenManager
from .core.client import CodeWhispererClient
from .api.routes import router, init_services

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
    cw = CodeWhispererClient()
    init_services(tm, cw)

    # Validate token on startup
    try:
        token = await tm.get_access_token()
        logger.info(f"✅ Token valid, profile: {tm.profile_arn}")
    except Exception as e:
        logger.error(f"❌ Token validation failed: {e}")
        logger.error("Make sure kiro-cli is logged in: kiro-cli login")

    yield

    await tm.close()
    await cw.close()


app = FastAPI(
    title="kiro2chat",
    description="Kiro to Chat - OpenAI-compatible API powered by Kiro/CodeWhisperer",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(router)


@app.get("/")
async def root():
    return {
        "name": "kiro2chat",
        "version": "0.1.0",
        "status": "running",
        "endpoints": {
            "models": "/v1/models",
            "chat": "/v1/chat/completions",
        },
    }


def main():
    uvicorn.run(
        "kiro2chat.app:app",
        host=config.host,
        port=config.port,
        log_level=config.log_level,
    )


if __name__ == "__main__":
    main()
