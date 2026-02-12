"""AWS EventStream parser for CodeWhisperer responses."""

import json
import struct
import logging
from dataclasses import dataclass
from typing import AsyncIterator

logger = logging.getLogger(__name__)


@dataclass
class EventStreamMessage:
    """A parsed EventStream message."""
    event_type: str
    content_type: str
    payload: dict


def parse_eventstream_bytes(raw: bytes) -> list[EventStreamMessage]:
    """Parse AWS EventStream binary format into messages."""
    messages = []
    offset = 0

    while offset + 12 <= len(raw):
        # Prelude: total_length (4) + headers_length (4) + prelude_crc (4)
        total_length = struct.unpack(">I", raw[offset : offset + 4])[0]
        headers_length = struct.unpack(">I", raw[offset + 4 : offset + 8])[0]

        if total_length < 16 or offset + total_length > len(raw):
            break

        # Parse headers
        headers = _parse_headers(raw[offset + 12 : offset + 12 + headers_length])

        # Payload is between headers and message CRC
        payload_start = offset + 12 + headers_length
        payload_end = offset + total_length - 4  # minus message CRC
        payload_bytes = raw[payload_start:payload_end]

        event_type = headers.get(":event-type", "")
        content_type = headers.get(":content-type", "")
        message_type = headers.get(":message-type", "")

        if message_type == "exception":
            # Error event
            try:
                payload = json.loads(payload_bytes.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                payload = {"error": payload_bytes.decode("utf-8", errors="replace")}
            messages.append(EventStreamMessage(
                event_type=event_type or "exception",
                content_type=content_type,
                payload=payload,
            ))
        elif payload_bytes:
            try:
                payload = json.loads(payload_bytes.decode("utf-8"))
                messages.append(EventStreamMessage(
                    event_type=event_type,
                    content_type=content_type,
                    payload=payload,
                ))
            except (json.JSONDecodeError, UnicodeDecodeError):
                pass

        offset += total_length

    return messages


def _parse_headers(data: bytes) -> dict[str, str]:
    """Parse EventStream headers."""
    headers = {}
    offset = 0
    while offset < len(data):
        if offset >= len(data):
            break
        # Header name length (1 byte)
        name_len = data[offset]
        offset += 1
        if offset + name_len > len(data):
            break
        name = data[offset : offset + name_len].decode("utf-8")
        offset += name_len

        # Header value type (1 byte) - 7 = string
        if offset >= len(data):
            break
        value_type = data[offset]
        offset += 1

        if value_type == 7:  # String
            if offset + 2 > len(data):
                break
            value_len = struct.unpack(">H", data[offset : offset + 2])[0]
            offset += 2
            if offset + value_len > len(data):
                break
            value = data[offset : offset + value_len].decode("utf-8")
            offset += value_len
            headers[name] = value
        else:
            # Skip unknown types - best effort
            break

    return headers


def extract_content_from_events(
    messages: list[EventStreamMessage],
) -> tuple[str, list[dict] | None]:
    """Extract text content and tool uses from EventStream messages.

    Returns (text_content, tool_uses).
    """
    text_parts: list[str] = []
    tool_uses: list[dict] = []

    for msg in messages:
        if msg.event_type == "assistantResponseEvent":
            content = msg.payload.get("content", "")
            if content:
                text_parts.append(content)

        elif msg.event_type == "codeEvent":
            content = msg.payload.get("content", "")
            if content:
                text_parts.append(content)

        elif msg.event_type == "toolUse":
            tool_uses.append(msg.payload)

        elif msg.event_type == "exception":
            error_msg = msg.payload.get("message", str(msg.payload))
            raise RuntimeError(f"CodeWhisperer error: {error_msg}")

    return "".join(text_parts), tool_uses if tool_uses else None


async def parse_streaming_eventstream(
    response,
) -> AsyncIterator[EventStreamMessage]:
    """Parse streaming EventStream response, yielding messages as they arrive.

    The response should be an httpx streaming response.
    """
    buffer = b""

    async for chunk in response.aiter_bytes():
        buffer += chunk

        # Try to parse complete messages from buffer
        while len(buffer) >= 12:
            total_length = struct.unpack(">I", buffer[:4])[0]
            if total_length < 16 or len(buffer) < total_length:
                break  # Need more data

            # Extract one complete message
            message_bytes = buffer[:total_length]
            buffer = buffer[total_length:]

            headers_length = struct.unpack(">I", message_bytes[4:8])[0]
            headers = _parse_headers(
                message_bytes[12 : 12 + headers_length]
            )

            payload_start = 12 + headers_length
            payload_end = total_length - 4
            payload_bytes = message_bytes[payload_start:payload_end]

            event_type = headers.get(":event-type", "")
            content_type = headers.get(":content-type", "")
            message_type = headers.get(":message-type", "")

            if message_type == "exception":
                try:
                    payload = json.loads(payload_bytes.decode("utf-8"))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    payload = {"error": payload_bytes.decode("utf-8", errors="replace")}
                yield EventStreamMessage(
                    event_type=event_type or "exception",
                    content_type=content_type,
                    payload=payload,
                )
            elif payload_bytes:
                try:
                    payload = json.loads(payload_bytes.decode("utf-8"))
                    yield EventStreamMessage(
                        event_type=event_type,
                        content_type=content_type,
                        payload=payload,
                    )
                except (json.JSONDecodeError, UnicodeDecodeError):
                    pass
