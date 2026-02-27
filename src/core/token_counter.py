"""Token counting for Claude models using tiktoken.

Claude's tokenizer is very close to OpenAI's cl100k_base encoding.
We use tiktoken for accurate counting, with a character-based fallback
if tiktoken is not available.
"""

import logging

logger = logging.getLogger(__name__)

try:
    import tiktoken
    _enc = tiktoken.get_encoding("cl100k_base")
    _USE_TIKTOKEN = True
except ImportError:
    _USE_TIKTOKEN = False
    logger.warning("tiktoken not available, using character-based estimation")


def count_tokens(text: str) -> int:
    """Count tokens in a string."""
    if not text:
        return 0
    if _USE_TIKTOKEN:
        return len(_enc.encode(text))
    # Fallback: rough heuristic
    import re
    cjk = len(re.findall(r'[\u4e00-\u9fff\u3400-\u4dbf\u3000-\u303f\uff00-\uffef\u3040-\u30ff\uac00-\ud7af]', text))
    return max(1, int(cjk / 1.5 + (len(text) - cjk) / 4 + 0.5))


def count_messages_tokens(messages: list[dict], system: str | None = None) -> int:
    """Count total input tokens for a message list.

    Accounts for per-message overhead (~4 tokens) and system prompt.
    """
    total = 0

    if system:
        total += count_tokens(system) + 4

    for msg in messages:
        total += 4  # per-message overhead
        content = msg.get("content", "")
        if isinstance(content, str):
            total += count_tokens(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    btype = block.get("type", "")
                    if btype == "text":
                        total += count_tokens(block.get("text", ""))
                    elif btype in ("image", "image_url"):
                        total += 85  # image token estimate
                    elif btype == "tool_use":
                        total += count_tokens(str(block.get("input", {})))
                    elif btype == "tool_result":
                        total += count_tokens(str(block.get("content", "")))

        # tool_calls in assistant messages
        for tc in msg.get("tool_calls", []):
            fn = tc.get("function", {})
            total += count_tokens(fn.get("name", ""))
            total += count_tokens(fn.get("arguments", ""))

    total += 3  # assistant reply priming
    return total


# Backward-compatible aliases
estimate_tokens = count_tokens
estimate_messages_tokens = count_messages_tokens
