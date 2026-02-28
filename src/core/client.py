"""Kiro API client with retry logic."""

import asyncio
import logging
from typing import AsyncIterator

import httpx

from ..config import config
from .converter import openai_to_kiro
from .eventstream import EventStreamMessage, parse_streaming_eventstream
from .token_counter import count_messages_tokens

logger = logging.getLogger(__name__)



# Long timeout for extended outputs; retry on transient failures
_TIMEOUT = httpx.Timeout(connect=30.0, read=7200.0, write=30.0, pool=30.0)
_MAX_RETRIES = 3
_RETRY_BACKOFF = [1, 3, 10]  # seconds

_UA = (
    "aws-sdk-js/3.738.0 ua/2.1 os/other lang/js "
    "md/browser#unknown_unknown api/codewhisperer#3.738.0 m/E KiroIDE"
)


class KiroClient:
    """Async client for Kiro generateAssistantResponse API."""

    def __init__(self):
        self._http = httpx.AsyncClient(timeout=_TIMEOUT)

    async def generate_stream(
        self,
        access_token: str,
        messages: list[dict],
        model: str,
        profile_arn: str,
        tools: list[dict] | None = None,
        conversation_id: str | None = None,
    ) -> AsyncIterator[EventStreamMessage]:
        """Send request to Kiro and yield streaming EventStream messages.

        Retries on 5xx errors and timeouts with exponential backoff.
        """
        # Pre-flight context size check
        estimated_tokens = count_messages_tokens(messages)
        if estimated_tokens > config.context_limit:
            raise RuntimeError(
                f"Context too large: ~{estimated_tokens:,} tokens exceeds limit of {config.context_limit:,}. "
                "Please start a new conversation or reduce message history."
            )

        kiro_req = openai_to_kiro(
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
            f"content={_cur.get('content', '')[:80]!r}, "
            f"images={len(_cur.get('images', []))}"
        )

        last_error = None
        for attempt in range(_MAX_RETRIES):
            try:
                async with self._http.stream(
                    "POST",
                    config.kiro_api_endpoint,
                    json=kiro_req,
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {access_token}",
                        "x-amzn-codewhisperer-optout": "true",
                        "User-Agent": _UA,
                    },
                ) as response:
                    if response.status_code == 200:
                        async for msg in parse_streaming_eventstream(response):
                            yield msg
                        return

                    body = await response.aread()
                    error_text = body.decode("utf-8", errors="replace")[:500]

                    if response.status_code == 400:
                        _hist = kiro_req.get("conversationState", {}).get("history", [])
                        _cur_ctx = kiro_req.get("conversationState", {}).get("currentMessage", {}).get("userInputMessage", {}).get("userInputMessageContext", {})
                        _shape = [
                            f"user(toolResults={len(h['userInputMessage'].get('userInputMessageContext',{}).get('toolResults',[]))})" if "userInputMessage" in h
                            else f"assistant(toolUses={len(h['assistantResponseMessage'].get('toolUses') or [])})"
                            for h in _hist
                        ]
                        logger.debug(f"400 history: {' → '.join(_shape)} → current(toolResults={len(_cur_ctx.get('toolResults',[]))})")

                    # 5xx: retry with backoff
                    if response.status_code >= 500 and attempt < _MAX_RETRIES - 1:
                        delay = _RETRY_BACKOFF[min(attempt, len(_RETRY_BACKOFF) - 1)]
                        logger.warning(f"Kiro {response.status_code}, retry {attempt + 1}/{_MAX_RETRIES} in {delay}s")
                        from ..metrics import CW_RETRIES
                        CW_RETRIES.inc()
                        await asyncio.sleep(delay)
                        last_error = RuntimeError(f"Kiro API error: {response.status_code} {error_text}")
                        continue

                    raise RuntimeError(f"Kiro API error: {response.status_code} {error_text}")

            except (httpx.ReadTimeout, httpx.ConnectTimeout) as e:
                if attempt < _MAX_RETRIES - 1:
                    delay = _RETRY_BACKOFF[min(attempt, len(_RETRY_BACKOFF) - 1)]
                    logger.warning(f"Kiro timeout, retry {attempt + 1}/{_MAX_RETRIES} in {delay}s: {e}")
                    await asyncio.sleep(delay)
                    last_error = e
                    continue
                raise RuntimeError(f"Kiro timeout after {_MAX_RETRIES} attempts: {e}") from e

        if last_error:
            raise last_error

    async def close(self):
        await self._http.aclose()
