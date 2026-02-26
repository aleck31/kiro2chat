"""Token estimation for Claude models.

Claude uses a BPE tokenizer similar to cl100k_base. Rough heuristics:
- English: ~4 chars per token
- Chinese/Japanese/Korean: ~1.5 chars per token
- Code: ~3.5 chars per token
- JSON/structured: ~3 chars per token

For more accurate counting, we detect CJK characters and adjust accordingly.
"""

import re

# CJK Unicode ranges
_CJK_RE = re.compile(
    r'[\u4e00-\u9fff\u3400-\u4dbf\u2e80-\u2eff\u3000-\u303f'
    r'\uff00-\uffef\u3040-\u309f\u30a0-\u30ff\uac00-\ud7af]'
)


def estimate_tokens(text: str) -> int:
    """Estimate token count for a string."""
    if not text:
        return 0

    cjk_chars = len(_CJK_RE.findall(text))
    other_chars = len(text) - cjk_chars

    # CJK: ~1.5 chars/token, Other: ~4 chars/token
    tokens = cjk_chars / 1.5 + other_chars / 4

    # Minimum 1 token for non-empty text
    return max(1, int(tokens + 0.5))


def estimate_messages_tokens(messages: list[dict], system: str | None = None) -> int:
    """Estimate total input tokens for a message list.

    Accounts for per-message overhead (~4 tokens each) and system prompt.
    """
    total = 0

    if system:
        total += estimate_tokens(system) + 4  # system overhead

    for msg in messages:
        total += 4  # per-message overhead (role, formatting)
        content = msg.get("content", "")
        if isinstance(content, str):
            total += estimate_tokens(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "text":
                        total += estimate_tokens(block.get("text", ""))
                    elif block.get("type") in ("image", "image_url"):
                        total += 85  # image tokens estimate
                    elif block.get("type") == "tool_use":
                        total += estimate_tokens(str(block.get("input", {})))
                    elif block.get("type") == "tool_result":
                        tc = block.get("content", "")
                        total += estimate_tokens(str(tc))

        # tool_calls in assistant messages
        for tc in msg.get("tool_calls", []):
            fn = tc.get("function", {})
            total += estimate_tokens(fn.get("name", ""))
            total += estimate_tokens(fn.get("arguments", ""))

    total += 3  # assistant reply priming
    return total
