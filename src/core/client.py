"""Kiro API client."""

import logging
from typing import AsyncIterator

import httpx

from ..config import config
from .converter import openai_to_codewhisperer
from .eventstream import EventStreamMessage, parse_streaming_eventstream

logger = logging.getLogger(__name__)


class KiroClient:
    """Async client for Kiro generateAssistantResponse API."""

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
        """Send request to Kiro and yield streaming EventStream messages."""
        kiro_req = openai_to_codewhisperer(
            messages=messages,
            model=model,
            tools=tools,
            profile_arn=profile_arn,
            conversation_id=conversation_id,
        )

        _cs = kiro_req.get("conversationState", {})
        _cur = _cs.get("currentMessage", {}).get("userInputMessage", {})
        _tools = _cur.get("userInputMessageContext", {}).get("tools", [])
        _tool_names = [t.get("toolSpecification", {}).get("name") for t in _tools]
        logger.debug(
            f"📤 Kiro request: model={_cur.get('modelId')}, "
            f"tools={len(_tools)}{_tool_names}, "
            f"history={len(_cs.get('history', []))}, "
            f"content={_cur.get('content', '')[:80]!r}"
        )

        async with self._http.stream(
            "POST",
            config.codewhisperer_url,
            json=kiro_req,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {access_token}",
                "x-amzn-codewhisperer-optout": "true",
            },
        ) as response:
            if response.status_code != 200:
                body = await response.aread()
                raise RuntimeError(
                    f"Kiro API error: {response.status_code} {body.decode('utf-8', errors='replace')[:500]}"
                )
            async for msg in parse_streaming_eventstream(response):
                yield msg

    async def close(self):
        await self._http.aclose()
