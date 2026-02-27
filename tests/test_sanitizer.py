"""Tests for system prompt sanitization."""
from src.core.sanitizer import sanitize_text, filter_tool_calls, build_system_prompt


class TestSanitizeText:
    def test_clean_text_unchanged(self):
        assert sanitize_text("Hello world") == "Hello world"

    def test_strips_kiro_identity(self):
        assert "Claude" in sanitize_text("I'm Kiro, an AI assistant", identity="claude")
        assert "Kiro" not in sanitize_text("I'm Kiro", identity="claude").lower()

    def test_strips_ide_and_identity(self):
        result = sanitize_text("I'm an AI assistant and IDE built to help", identity="claude")
        assert "IDE" not in result

    def test_strips_codewhisperer(self):
        assert "Claude" in sanitize_text("CodeWhisperer is great", identity="claude")

    def test_kiro_identity_preserved(self):
        # When identity=kiro (default), Kiro identity is NOT scrubbed
        assert "Kiro" in sanitize_text("I'm Kiro, an AI assistant")

    def test_removes_tool_name_lines(self):
        text = "Here are tools:\n- readFile\n- other stuff"
        result = sanitize_text(text)
        assert "readFile" not in result
        assert "other stuff" in result

    def test_preserves_streaming_whitespace(self):
        assert sanitize_text("\n\nHello\n\n", is_chunk=True) == "\n\nHello\n\n"

    def test_strips_non_chunk(self):
        assert sanitize_text("\n\nHello\n\n", is_chunk=False) == "Hello"

    def test_empty_string(self):
        assert sanitize_text("") == ""
        assert sanitize_text(None) is None


class TestFilterToolCalls:
    def test_filters_kiro_tools(self):
        tcs = [
            {"function": {"name": "readFile", "arguments": "{}"}},
            {"function": {"name": "my_tool", "arguments": "{}"}},
        ]
        result = filter_tool_calls(tcs)
        assert len(result) == 1
        assert result[0]["function"]["name"] == "my_tool"

    def test_keeps_user_tools(self):
        tcs = [{"function": {"name": "mcp__search", "arguments": "{}"}}]
        assert filter_tool_calls(tcs) == tcs

    def test_returns_none_if_all_filtered(self):
        tcs = [{"function": {"name": "webSearch", "arguments": "{}"}}]
        assert filter_tool_calls(tcs) is None

    def test_none_input(self):
        assert filter_tool_calls(None) is None


class TestBuildSystemPrompt:
    def test_includes_anti_prompt(self):
        result = build_system_prompt(None, identity="claude")
        assert "Claude" in result

    def test_includes_anti_prompt_kiro(self):
        result = build_system_prompt(None, identity="kiro")
        assert "TOOL RULES" in result
        assert "Claude" not in result

    def test_includes_user_system(self):
        result = build_system_prompt("You are a pirate")
        assert "pirate" in result

    def test_tool_hint_when_tools(self):
        result = build_system_prompt(None, has_tools=True)
        assert "tool" in result.lower()
