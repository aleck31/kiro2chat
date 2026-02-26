"""Tests for API route helpers."""
import pytest
from src.api.routes import _is_valid_tool, _filter_valid_tools


class TestToolValidation:
    def test_valid_openai_tool(self):
        assert _is_valid_tool({"type": "function", "function": {"name": "t", "description": "d"}})

    def test_valid_anthropic_tool(self):
        assert _is_valid_tool({"name": "t", "description": "d"})

    def test_empty_name(self):
        assert not _is_valid_tool({"type": "function", "function": {"name": "", "description": "d"}})

    def test_empty_description(self):
        assert not _is_valid_tool({"name": "t", "description": ""})

    def test_empty_dict(self):
        assert not _is_valid_tool({})


class TestFilterValidTools:
    def test_filters_invalid(self):
        tools = [
            {"name": "good", "description": "ok"},
            {"name": "", "description": ""},
            {"name": "also_good", "description": "fine"},
        ]
        result = _filter_valid_tools(tools)
        assert len(result) == 2
