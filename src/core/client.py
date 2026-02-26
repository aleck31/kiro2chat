"""CodeWhisperer API client with retry logic."""

import asyncio
import logging
import uuid
from typing import AsyncIterator

import httpx

from ..config import config
from .converter import openai_to_codewhisperer
from .eventstream import EventStreamMessage, parse_streaming_eventstream

logger = logging.getLogger(__name__)

# CW backend timeout: 2 hours for long outputs
CW_TIMEOUT = httpx.Timeout(connect=30.0, read=7200.0, write=30.0, pool=30.0)
MAX_RETRIES = 3
RETRY_BACKOFF = [1, 3, 10]  # seconds


class CodeWhispererClient:
    """Async client for CodeWhisperer generateAssistantResponse API."""

    def __init__(self):
        self._http = httpx.AsyncClient(timeout=CW_TIMEOUT)

    async def generate_stream(
        self,
        access_token: str,
        messages: list[dict],
        model: str,
        profile_arn: str,
        tools: list[dict] | None = None,
        conversation_id: str | None = None,
    ) -> AsyncIterator[EventStreamMessage]:
        """Send request to CodeWhisperer and yield streaming EventStream messages.
        
        Retries on 5xx errors with exponential backoff.
        """
        cw_req = openai_to_codewhisperer(
            messages=messages, model=model, tools=tools,
            profile_arn=profile_arn, conversation_id=conversation_id,
        )

        import json as _json
        logger.info(f"CW request: {_json.dumps(cw_req, ensure_ascii=False)[:2000]}")

        last_error = None
        for attempt in range(MAX_RETRIES):
            try:
                async with self._http.stream(
                    "POST", config.codewhisperer_url, json=cw_req,
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {access_token}",
                        "x-amzn-codewhisperer-optout": "true",
                        "User-Agent": "aws-sdk-js/3.738.0 ua/2.1 os/other lang/js md/browser#unknown_unknown api/codewhisperer#3.738.0 m/E KiroIDE",
                    },
                ) as response:
                    if response.status_code == 200:
                        async for msg in parse_streaming_eventstream(response):
                            yield msg
                        return
                    
                    body = await response.aread()
                    error_text = body.decode("utf-8", errors="replace")[:500]
                    
                    # 5xx: retry with backoff
                    if response.status_code >= 500 and attempt < MAX_RETRIES - 1:
                        delay = RETRY_BACKOFF[min(attempt, len(RETRY_BACKOFF) - 1)]
                        logger.warning(f"CW {response.status_code}, retry {attempt+1}/{MAX_RETRIES} in {delay}s")
                        from ..metrics import CW_RETRIES
                        CW_RETRIES.inc()
                        await asyncio.sleep(delay)
                        last_error = RuntimeError(f"CodeWhisperer API error: {response.status_code} {error_text}")
                        continue
                    
                    raise RuntimeError(f"CodeWhisperer API error: {response.status_code} {error_text}")
                    
            except (httpx.ReadTimeout, httpx.ConnectTimeout) as e:
                if attempt < MAX_RETRIES - 1:
                    delay = RETRY_BACKOFF[min(attempt, len(RETRY_BACKOFF) - 1)]
                    logger.warning(f"CW timeout, retry {attempt+1}/{MAX_RETRIES} in {delay}s: {e}")
                    await asyncio.sleep(delay)
                    last_error = e
                    continue
                raise RuntimeError(f"CodeWhisperer timeout after {MAX_RETRIES} attempts: {e}") from e

        if last_error:
            raise last_error

    async def close(self):
        await self._http.aclose()
