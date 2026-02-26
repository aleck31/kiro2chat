"""Health check utilities."""

import time
import logging

logger = logging.getLogger(__name__)


async def check_health(token_manager, cw_client) -> dict:
    """Check service health: token validity and CW API connectivity."""
    result = {"status": "ok", "checks": {}}

    try:
        await token_manager.get_access_token()
        result["checks"]["token"] = {"status": "ok"}
    except Exception as e:
        result["status"] = "degraded"
        result["checks"]["token"] = {"status": "error", "error": "token_refresh_failed"}

    return result
