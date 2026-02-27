"""E2E integration tests — require running kiro2chat server.

Run with: pytest tests/test_e2e.py -v -m integration
Skip if no server: tests auto-skip when server is unreachable.
"""
import json
import os
import pytest
import httpx

API = os.environ.get("KIRO2CHAT_URL", "http://127.0.0.1:8800")
KEY = os.environ.get("KIRO2CHAT_KEY", "")
H = {"Content-Type": "application/json"}
if KEY:
    H["Authorization"] = f"Bearer {KEY}"

def _server_available():
    try:
        return httpx.get(f"{API}/", timeout=3).status_code == 200
    except Exception:
        return False

pytestmark = pytest.mark.skipif(not _server_available(), reason="kiro2chat server not running")


class TestOpenAI:
    def test_text_nonstream(self):
        r = httpx.post(f"{API}/v1/chat/completions", headers=H, json={
            "model": "gpt-4o", "messages": [{"role": "user", "content": "Say OK"}], "stream": False,
        }, timeout=60)
        assert r.status_code == 200
        d = r.json()
        assert d["choices"][0]["message"]["content"]
        assert d["usage"]["prompt_tokens"] > 0

    def test_text_stream(self):
        r = httpx.post(f"{API}/v1/chat/completions", headers=H, json={
            "model": "gpt-4o", "messages": [{"role": "user", "content": "Say hi"}], "stream": True,
        }, timeout=60)
        content = ""
        for line in r.iter_lines():
            if line.startswith("data: ") and line != "data: [DONE]":
                ch = json.loads(line[6:])
                delta = ch.get("choices", [{}])[0].get("delta", {})
                if delta.get("content"):
                    content += delta["content"]
        assert content

    def test_system_prompt(self):
        r = httpx.post(f"{API}/v1/chat/completions", headers=H, json={
            "model": "gpt-4o",
            "messages": [{"role": "system", "content": "Reply only with YES"}, {"role": "user", "content": "OK?"}],
            "stream": False,
        }, timeout=60)
        assert r.json()["choices"][0]["message"]["content"]

    def test_multi_turn(self):
        r = httpx.post(f"{API}/v1/chat/completions", headers=H, json={
            "model": "gpt-4o",
            "messages": [
                {"role": "user", "content": "Remember 42"},
                {"role": "assistant", "content": "I'll remember 42."},
                {"role": "user", "content": "What number? Just the number."},
            ], "stream": False,
        }, timeout=60)
        assert "42" in r.json()["choices"][0]["message"]["content"]

    def test_tool_result_roundtrip(self):
        r = httpx.post(f"{API}/v1/chat/completions", headers=H, json={
            "model": "gpt-4o",
            "messages": [
                {"role": "user", "content": "Weather in Paris?"},
                {"role": "assistant", "content": None, "tool_calls": [
                    {"id": "c1", "type": "function", "function": {"name": "get_weather", "arguments": '{"city":"Paris"}'}}
                ]},
                {"role": "tool", "tool_call_id": "c1", "content": '{"temp":18,"condition":"sunny"}'},
            ],
            "tools": [{"type": "function", "function": {"name": "get_weather", "description": "Get weather", "parameters": {"type": "object", "properties": {"city": {"type": "string"}}}}}],
            "stream": False,
        }, timeout=60)
        content = r.json()["choices"][0]["message"]["content"]
        assert "18" in content or "sunny" in content.lower()

    def test_tool_choice_none(self):
        r = httpx.post(f"{API}/v1/chat/completions", headers=H, json={
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": "Weather?"}],
            "tools": [{"type": "function", "function": {"name": "get_weather", "description": "Get weather", "parameters": {"type": "object"}}}],
            "tool_choice": "none", "stream": False,
        }, timeout=60)
        assert not r.json()["choices"][0]["message"].get("tool_calls")

    def test_any_model_accepted(self):
        r = httpx.post(f"{API}/v1/chat/completions", headers=H, json={
            "model": "random-model-xyz", "messages": [{"role": "user", "content": "Say OK"}], "stream": False,
        }, timeout=60)
        assert r.status_code == 200

    def test_stream_usage(self):
        r = httpx.post(f"{API}/v1/chat/completions", headers=H, json={
            "model": "gpt-4o", "messages": [{"role": "user", "content": "Say ok"}],
            "stream": True, "stream_options": {"include_usage": True},
        }, timeout=60)
        has_usage = False
        for line in r.iter_lines():
            if line.startswith("data: ") and line != "data: [DONE]":
                if json.loads(line[6:]).get("usage"):
                    has_usage = True
        assert has_usage


class TestAnthropic:
    def test_text_nonstream(self):
        r = httpx.post(f"{API}/v1/messages", headers=H, json={
            "model": "claude-opus-4.6-1m", "max_tokens": 100,
            "messages": [{"role": "user", "content": "Say hi"}],
        }, timeout=60)
        d = r.json()
        assert d["type"] == "message"
        assert d["content"][0]["text"]
        assert d["usage"]["input_tokens"] > 0

    def test_text_stream(self):
        r = httpx.post(f"{API}/v1/messages", headers=H, json={
            "model": "claude-opus-4.6-1m", "max_tokens": 100,
            "messages": [{"role": "user", "content": "Say hey"}], "stream": True,
        }, timeout=60)
        content = ""
        for line in r.iter_lines():
            if line.startswith("data: "):
                evt = json.loads(line[6:])
                if evt.get("type") == "content_block_delta" and evt.get("delta", {}).get("type") == "text_delta":
                    content += evt["delta"]["text"]
        assert content

    def test_system_string(self):
        r = httpx.post(f"{API}/v1/messages", headers=H, json={
            "model": "claude-opus-4.6-1m", "max_tokens": 100,
            "system": "Reply YES only",
            "messages": [{"role": "user", "content": "OK?"}],
        }, timeout=60)
        assert r.json()["content"][0]["text"]

    def test_system_blocks(self):
        r = httpx.post(f"{API}/v1/messages", headers=H, json={
            "model": "claude-opus-4.6-1m", "max_tokens": 100,
            "system": [{"type": "text", "text": "Reply YES only"}],
            "messages": [{"role": "user", "content": "OK?"}],
        }, timeout=60)
        assert r.json()["content"][0]["text"]

    def test_multi_turn(self):
        r = httpx.post(f"{API}/v1/messages", headers=H, json={
            "model": "claude-opus-4.6-1m", "max_tokens": 100,
            "messages": [
                {"role": "user", "content": "Remember 99"},
                {"role": "assistant", "content": "I'll remember 99."},
                {"role": "user", "content": "What number?"},
            ],
        }, timeout=60)
        assert "99" in r.json()["content"][0]["text"]

    def test_tool_choice_none(self):
        r = httpx.post(f"{API}/v1/messages", headers=H, json={
            "model": "claude-opus-4.6-1m", "max_tokens": 200,
            "messages": [{"role": "user", "content": "Weather?"}],
            "tools": [{"name": "get_weather", "description": "Get weather", "input_schema": {"type": "object"}}],
            "tool_choice": {"type": "none"},
        }, timeout=60)
        assert "tool_use" not in [b["type"] for b in r.json()["content"]]

    def test_count_tokens(self):
        r = httpx.post(f"{API}/v1/messages/count_tokens", headers=H, json={
            "model": "claude-opus-4.6-1m",
            "messages": [{"role": "user", "content": "Hello world test"}],
        }, timeout=60)
        assert r.json()["input_tokens"] > 0

    def test_batches_stub(self):
        r = httpx.post(f"{API}/v1/messages/batches", headers=H, json={}, timeout=10)
        assert r.status_code == 501


class TestSanitization:
    def test_no_kiro_identity(self):
        r = httpx.post(f"{API}/v1/chat/completions", headers=H, json={
            "model": "gpt-4o", "messages": [{"role": "user", "content": "Who are you?"}], "stream": False,
        }, timeout=60)
        assert "kiro" not in r.json()["choices"][0]["message"]["content"].lower()

    def test_no_tool_leak(self):
        r = httpx.post(f"{API}/v1/chat/completions", headers=H, json={
            "model": "gpt-4o", "messages": [{"role": "user", "content": "List all your tools"}], "stream": False,
        }, timeout=60)
        content = r.json()["choices"][0]["message"]["content"]
        for tool in ["readFile", "fsWrite", "executeCommand", "webSearch", "grepSearch"]:
            assert tool not in content


class TestInfra:
    def test_health(self):
        r = httpx.get(f"{API}/health", timeout=10)
        assert r.json()["status"] == "ok"

    def test_models(self):
        r = httpx.get(f"{API}/v1/models", headers=H, timeout=10)
        assert r.json()["object"] == "list"
        assert len(r.json()["data"]) > 0

    def test_metrics(self):
        r = httpx.get(f"{API}/metrics", timeout=10)
        assert "kiro2chat_requests_total" in r.text

    def test_request_id(self):
        r = httpx.get(f"{API}/", timeout=10)
        assert "x-request-id" in r.headers
