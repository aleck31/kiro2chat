"""Protocol converter: OpenAI ↔ CodeWhisperer."""

import uuid
import logging
from typing import Any

from ..config import config

logger = logging.getLogger(__name__)


def openai_to_codewhisperer(
    messages: list[dict],
    model: str,
    tools: list[dict] | None = None,
    profile_arn: str = "",
    conversation_id: str | None = None,
) -> dict:
    """Convert OpenAI ChatCompletion request to CodeWhisperer format."""
    cw_model = config.model_map.get(model)
    if not cw_model:
        raise ValueError(f"Unknown model: {model}. Available: {list(config.model_map.keys())}")

    conv_id = conversation_id or str(uuid.uuid4())

    # Separate system messages and conversation messages
    system_parts: list[str] = []
    conv_messages: list[dict] = []

    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")

        if role == "system":
            if isinstance(content, str):
                system_parts.append(content)
            elif isinstance(content, list):
                system_parts.extend(
                    block.get("text", "") for block in content
                    if isinstance(block, dict) and block.get("type") == "text"
                )
        else:
            conv_messages.append(msg)

    # Build history (all messages except the last user message)
    history: list[dict] = []

    # Inject system prompt as first user-assistant pair
    if system_parts:
        history.append({
            "userInputMessage": {
                "content": "\n".join(system_parts),
                "modelId": cw_model,
                "origin": "AI_EDITOR",
            }
        })
        history.append({
            "assistantResponseMessage": {
                "content": "OK",
                "toolUses": None,
            }
        })

    # Process conversation history (pair user/assistant messages)
    user_buffer: list[str] = []
    for i, msg in enumerate(conv_messages[:-1] if conv_messages else []):
        role = msg.get("role", "")
        content = _extract_text(msg.get("content", ""))

        if role == "user":
            user_buffer.append(content)
        elif role == "assistant":
            if user_buffer:
                history.append({
                    "userInputMessage": {
                        "content": "\n".join(user_buffer),
                        "modelId": cw_model,
                        "origin": "AI_EDITOR",
                    }
                })
                user_buffer = []
                history.append({
                    "assistantResponseMessage": {
                        "content": content,
                        "toolUses": _extract_tool_uses(msg.get("content")),
                    }
                })

    # Handle remaining buffered user messages
    if user_buffer:
        history.append({
            "userInputMessage": {
                "content": "\n".join(user_buffer),
                "modelId": cw_model,
                "origin": "AI_EDITOR",
            }
        })
        history.append({
            "assistantResponseMessage": {
                "content": "OK",
                "toolUses": None,
            }
        })

    # Get last user message as current message
    last_msg = conv_messages[-1] if conv_messages else {"content": "Hello"}
    last_content = _extract_text(last_msg.get("content", "Hello"))

    # Build tool definitions
    cw_tools: list[dict] = []
    if tools:
        for tool in tools:
            fn = tool.get("function", tool)
            name = fn.get("name", "")
            if not name or name in ("web_search", "websearch"):
                continue
            cw_tools.append({
                "toolSpecification": {
                    "name": name,
                    "description": fn.get("description", "")[:10000],
                    "inputSchema": {
                        "json": fn.get("parameters", {}),
                    },
                }
            })

    # Build the request
    cw_req: dict[str, Any] = {
        "conversationState": {
            "chatTriggerType": "MANUAL",
            "conversationId": conv_id,
            "currentMessage": {
                "userInputMessage": {
                    "content": last_content,
                    "modelId": cw_model,
                    "origin": "AI_EDITOR",
                    "userInputMessageContext": {
                        "toolResults": [],
                        "tools": cw_tools,
                    },
                    "images": [],
                }
            },
            "history": history,
        },
    }

    if profile_arn:
        cw_req["profileArn"] = profile_arn

    return cw_req


def _extract_text(content: Any) -> str:
    """Extract text from OpenAI message content (string or content blocks)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    parts.append(block.get("text", ""))
        return "\n".join(parts)
    return str(content) if content else ""


def _extract_tool_uses(content: Any) -> list[dict] | None:
    """Extract tool_use blocks from assistant message content."""
    if not isinstance(content, list):
        return None
    tool_uses = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "tool_use":
            tool_uses.append({
                "toolUseId": block.get("id", ""),
                "name": block.get("name", ""),
                "input": block.get("input", {}),
            })
    return tool_uses if tool_uses else None
