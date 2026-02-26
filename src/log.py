"""Centralized loguru configuration for kiro2chat."""

import sys
import logging
from loguru import logger

# Remove default loguru handler
logger.remove()

# Add JSON-structured handler for production
logger.add(
    sys.stderr,
    format="{time:YYYY-MM-DD HH:mm:ss} | {level:<7} | {name}:{function}:{line} | {message}",
    level="INFO",
    colorize=True,
)

# Intercept stdlib logging → loguru
class InterceptHandler(logging.Handler):
    def emit(self, record):
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        frame, depth = logging.currentframe(), 2
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1
        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())

logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)

# Suppress noisy loggers
for name in ("uvicorn.access", "httpx", "httpcore"):
    logging.getLogger(name).setLevel(logging.WARNING)
