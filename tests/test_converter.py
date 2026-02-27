"""Tests for protocol converter."""
from src.core.converter import (
    openai_to_kiro,
    _extract_images, _convert_tool_message_to_result,
)
from src.config import config

# Pick a valid model from config for testing
_TEST_MODEL = next(iter(config.model_map.keys()))


class TestAntiPrompt:
    def test_anti_prompt_injected(self):
        req = openai_to_kiro(
            messages=[{"role": "user", "content": "Hi"}], model=_TEST_MODEL,
        )
        history = req["conversationState"]["history"]
        assert len(history) >= 2
        assert "Claude" in history[0]["userInputMessage"]["content"]

    def test_user_system_preserved(self):
        req = openai_to_kiro(
            messages=[
                {"role": "system", "content": "You are a pirate"},
                {"role": "user", "content": "Hi"},
            ], model=_TEST_MODEL,
        )
        first = req["conversationState"]["history"][0]["userInputMessage"]["content"]
        assert "pirate" in first


class TestToolResultConversion:
    def test_string_content(self):
        msg = {"role": "tool", "tool_call_id": "t1", "content": "result text"}
        r = _convert_tool_message_to_result(msg)
        assert r["content"][0]["text"] == "result text"

    def test_list_content(self):
        msg = {"role": "tool", "tool_call_id": "t1",
               "content": [{"text": "actual data"}]}
        r = _convert_tool_message_to_result(msg)
        assert r["content"][0]["text"] == "actual data"


class TestExtractImages:
    def test_openai_data_uri(self):
        content = [
            {"type": "text", "text": "What color?"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc123"}},
        ]
        imgs = _extract_images(content)
        assert len(imgs) == 1
        assert imgs[0]["format"] == "png"
        assert imgs[0]["source"]["bytes"] == "abc123"

    def test_no_images(self):
        assert _extract_images("just text") == []
        assert _extract_images([{"type": "text", "text": "hi"}]) == []
