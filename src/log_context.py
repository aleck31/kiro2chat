"""Logging context for user/session tracking."""

import logging
from contextvars import ContextVar

# Current request's user tag, e.g. "tg:12345", "web:a3f8b2c1", "api:192.168.1.5"
user_tag: ContextVar[str] = ContextVar("user_tag", default="")


class UserTagFilter(logging.Filter):
    """Inject user_tag into log records."""
    def filter(self, record):
        tag = user_tag.get()
        record.user_tag = f" [{tag}]" if tag else ""
        return True
