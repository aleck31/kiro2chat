"""CodeWhisperer API client."""

import logging
from typing import AsyncIterator

import httpx

from ..config import config
from .converter import openai_to_codewhisperer
from .eventstream import EventStreamMessage, parse_streaming_eventstream

logger = logging.getLogger(__name__)


class CodeWhispererClient:
    """Async client for CodeWhisperer generateAssistantResponse API."""

    def __init__(self):
        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=15.0, read=120.0, write=15.0, pool=15.0),
        )

    async def generate_stream(
        self,
        access_token: str,
        messages: list[dict],
        model: str,
        profile_arn: str,
        tools: list[dict] | None = None,
        conversation_id: str | None = None,
    ) -> AsyncIterator[EventStreamMessage]:
        """Send request to CodeWhisperer and yield streaming EventStream messages."""
        cw_req = openai_to_codewhisperer(
            messages=messages,
            model=model,
            tools=tools,
            profile_arn=profile_arn,
            conversation_id=conversation_id,
        )

        import json as _json
        logger.info(f"📤 CW request: {_json.dumps(cw_req, ensure_ascii=False)[:2000]}")

        async with self._http.stream(
            "POST",
            config.codewhisperer_url,
            json=cw_req,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {access_token}",
                "x-amzn-codewhisperer-optout": "true",
            },
        ) as response:
            if response.status_code != 200:
                body = await response.aread()
                raise RuntimeError(
                    f"CodeWhisperer API error: {response.status_code} {body.decode('utf-8', errors='replace')[:500]}"
                )
            async for msg in parse_streaming_eventstream(response):
                yield msg

    async def close(self):
        await self._http.aclose()
