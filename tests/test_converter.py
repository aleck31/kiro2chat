"""Tests for protocol converter."""
import json
import pytest
from src.core.converter import (
    openai_to_codewhisperer, BACKEND_MODEL_ID,
    _extract_text, _extract_images, _convert_tool_message_to_result,
)


class TestBackendModel:
    def test_always_opus_46_1m(self):
        assert BACKEND_MODEL_ID == "claude-opus-4.6-1m"

    def test_any_model_accepted(self):
        for model in ["gpt-4o", "claude-sonnet-4", "random-xyz"]:
            req = openai_to_codewhisperer(
                messages=[{"role": "user", "content": "Hi"}], model=model,
            )
            mid = req["conversationState"]["currentMessage"]["userInputMessage"]["modelId"]
            assert mid == BACKEND_MODEL_ID


class TestAntiPrompt:
    def test_anti_prompt_injected(self):
        req = openai_to_codewhisperer(
            messages=[{"role": "user", "content": "Hi"}], model="gpt-4o",
        )
        history = req["conversationState"]["history"]
        assert len(history) >= 2
        assert "Claude" in history[0]["userInputMessage"]["content"]

    def test_user_system_preserved(self):
        req = openai_to_codewhisperer(
            messages=[
                {"role": "system", "content": "You are a pirate"},
                {"role": "user", "content": "Hi"},
            ], model="gpt-4o",
        )
        first = req["conversationState"]["history"][0]["userInputMessage"]["content"]
        assert "pirate" in first

    def test_developer_role(self):
        req = openai_to_codewhisperer(
            messages=[
                {"role": "developer", "content": "Be helpful"},
                {"role": "user", "content": "Hi"},
            ], model="gpt-4o",
        )
        first = req["conversationState"]["history"][0]["userInputMessage"]["content"]
        assert "helpful" in first


class TestToolResultConversion:
    def test_string_content(self):
        msg = {"role": "tool", "tool_call_id": "t1", "content": "result text"}
        r = _convert_tool_message_to_result(msg)
        assert r["content"][0]["text"] == "result text"

    def test_json_encoded_content_blocks(self):
        msg = {"role": "tool", "tool_call_id": "t1",
               "content": '[{"type":"text","text":"actual data"}]'}
        r = _convert_tool_message_to_result(msg)
        assert r["content"][0]["text"] == "actual data"

    def test_truncation(self):
        msg = {"role": "tool", "tool_call_id": "t1", "content": "x" * 60000}
        r = _convert_tool_message_to_result(msg)
        assert len(r["content"][0]["text"]) < 51000


class TestExtractImages:
    def test_openai_data_uri(self):
        msg = {"content": [
            {"type": "text", "text": "What color?"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc123"}},
        ]}
        imgs = _extract_images(msg)
        assert len(imgs) == 1
        assert imgs[0]["format"] == "png"
        assert imgs[0]["source"]["bytes"] == "abc123"

    def test_anthropic_base64(self):
        msg = {"content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": "xyz"}},
        ]}
        imgs = _extract_images(msg)
        assert len(imgs) == 1
        assert imgs[0]["format"] == "jpg"

    def test_no_images(self):
        msg = {"content": "just text"}
        assert _extract_images(msg) == []
