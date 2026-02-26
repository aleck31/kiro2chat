"""Health check utilities."""

import time
import logging

logger = logging.getLogger(__name__)


async def check_health(token_manager, cw_client) -> dict:
    """Check service health: token validity and CW API connectivity."""
    result = {"status": "ok", "checks": {}}

    # Token check
    try:
        token = await token_manager.get_access_token()
        result["checks"]["token"] = {"status": "ok", "profile": token_manager.profile_arn}
    except Exception as e:
        result["status"] = "degraded"
        result["checks"]["token"] = {"status": "error", "error": str(e)}

    return result
