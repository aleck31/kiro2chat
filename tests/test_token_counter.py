"""Tests for token counting."""
import pytest
from src.core.token_counter import count_tokens, count_messages_tokens


class TestCountTokens:
    def test_english(self):
        assert count_tokens("Hello world") > 0

    def test_chinese(self):
        # Chinese should have more tokens per character
        assert count_tokens("你好世界") > 2

    def test_empty(self):
        assert count_tokens("") == 0

    def test_code(self):
        assert count_tokens("def foo(): pass") > 0


class TestCountMessagesTokens:
    def test_simple(self):
        msgs = [{"role": "user", "content": "Hello"}]
        assert count_messages_tokens(msgs) > 0

    def test_with_system(self):
        msgs = [{"role": "user", "content": "Hi"}]
        with_sys = count_messages_tokens(msgs, system="You are helpful")
        without_sys = count_messages_tokens(msgs)
        assert with_sys > without_sys

    def test_multi_turn(self):
        msgs = [
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Hello!"},
            {"role": "user", "content": "How are you?"},
        ]
        assert count_messages_tokens(msgs) > count_messages_tokens(msgs[:1])
