<div align="center">
  <img src="docs/logo.png" alt="kiro2chat logo" width="128" height="128">
  <h1>kiro2chat</h1>
  <p><strong>Kiro → Standard API Gateway</strong></p>
  <p>Wrap Kiro CLI's Claude Opus 4.6 backend into a fully compatible OpenAI + Anthropic API Gateway</p>

  **[English](README.md)** | **[中文](README_CN.md)**

  ![Python](https://img.shields.io/badge/python-≥3.13-blue?logo=python&logoColor=white)
  ![FastAPI](https://img.shields.io/badge/FastAPI-0.129+-green?logo=fastapi&logoColor=white)
  ![License](https://img.shields.io/badge/license-MIT-blue)
  ![Version](https://img.shields.io/badge/version-0.6.0-purple)
</div>

---

## ✨ Features

- 🔄 **双协议兼容** — 同时支持 OpenAI `/v1/chat/completions` 和 Anthropic `/v1/messages` 格式
- 🧠 **Claude Opus 4.6 1M** — 后端固定使用最强模型，1M 上下文窗口
- 🧹 **System Prompt 清洗** — 三层防御彻底清除 Kiro IDE 注入的系统提示词和工具定义
- 🛠️ **完整 Tool Calling** — 支持工具定义、tool_choice、tool_result 多轮回传
- 📡 **流式 + 非流式** — 两种 API 格式均支持 SSE 流式和同步响应
- 🔑 **自动 Token 管理** — 从 kiro-cli SQLite 读取并自动刷新 IdC Token
- 🤖 **Strands Agent** — 可选的 Agent 层，支持 MCP 工具
- 🌐 **Web UI** — Gradio 多页面界面（聊天、监控、配置）
- 📱 **Telegram Bot** — 通过 Agent 层的 TG 机器人

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        Client Layer                          │
│                                                              │
│  OpenAI SDK ──┐                                              │
│  Anthropic SDK┤──→ /v1/chat/completions (OpenAI format)      │
│  Claude Code ─┤──→ /v1/messages         (Anthropic format)   │
│  Any Client  ─┘                                              │
│                           │                                  │
├───────────────────────────┼──────────────────────────────────┤
│                   Protocol Layer                             │
│                           │                                  │
│    ┌──────────────────────┼──────────────────────┐           │
│    │  Anti-Prompt Injection (sanitizer.py)        │           │
│    │  → Strips Kiro IDE system prompt             │           │
│    │  → Blocks IDE tool leakage                   │           │
│    │  → Enforces Claude identity                  │           │
│    └──────────────────────┼──────────────────────┘           │
│                           │                                  │
│    OpenAI/Anthropic → CodeWhisperer (converter.py)           │
│    EventStream Binary → JSON (eventstream.py)                │
│    Response → Sanitized Output (sanitizer.py)                │
│                           │                                  │
├───────────────────────────┼──────────────────────────────────┤
│                    Auth Layer                                │
│    kiro-cli SQLite → IdC Token Auto-Refresh                  │
│    (~/.local/share/kiro-cli/data.sqlite3)                    │
│                           │                                  │
│                           ↓                                  │
│    CodeWhisperer API (claude-opus-4.6-1m)                    │
└─────────────────────────────────────────────────────────────┘
```

## 📋 API Endpoints

| Endpoint | Method | Format | Description |
|----------|--------|--------|-------------|
| `/v1/chat/completions` | POST | OpenAI | Chat completions (stream + non-stream) |
| `/v1/models` | GET | OpenAI | List available models |
| `/v1/messages` | POST | Anthropic | Messages API (stream + non-stream) |
| `/v1/messages/count_tokens` | POST | Anthropic | Token count estimation |
| `/v1/messages/batches` | POST | Anthropic | Batch API (stub, 501) |
| `/v1/agent/chat` | POST | Custom | Strands Agent chat |
| `/v1/agent/tools` | GET | Custom | List loaded tools |
| `/health` | GET | — | Health check |
| `/` | GET | — | Service info |

## 🚀 Quick Start

### Prerequisites

```bash
# 1. Install kiro-cli and login
kiro-cli login

# 2. Clone and install
git clone https://github.com/neosun100/kiro2chat.git
cd kiro2chat
uv sync
```

### Run

```bash
# API server only (port 8000)
uv run kiro2chat api

# Web UI (port 7860)
uv run kiro2chat webui

# Telegram Bot
uv run kiro2chat bot

# All together
uv run kiro2chat all
```

### Use with OpenAI SDK

```python
from openai import OpenAI

client = OpenAI(base_url="http://localhost:8000/v1", api_key="not-needed")

response = client.chat.completions.create(
    model="claude-opus-4.6-1m",  # Any model name works
    messages=[{"role": "user", "content": "Hello!"}],
)
print(response.choices[0].message.content)
```

### Use with Anthropic SDK

```python
import anthropic

client = anthropic.Anthropic(base_url="http://localhost:8000", api_key="not-needed")

message = client.messages.create(
    model="claude-opus-4.6-1m",
    max_tokens=1024,
    messages=[{"role": "user", "content": "Hello!"}],
)
print(message.content[0].text)
```

### Use with curl

```bash
# OpenAI format
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "gpt-4o", "messages": [{"role": "user", "content": "Hello"}]}'

# Anthropic format
curl http://localhost:8000/v1/messages \
  -H "Content-Type: application/json" \
  -d '{"model": "claude-opus-4.6-1m", "max_tokens": 1024, "messages": [{"role": "user", "content": "Hello"}]}'
```

## 🔧 API Compatibility

### OpenAI `/v1/chat/completions`

| Feature | Status |
|---------|--------|
| Text generation (stream + non-stream) | ✅ |
| System / Developer role messages | ✅ |
| Multi-turn conversations | ✅ |
| Tool definitions + tool_calls | ✅ |
| Tool result round-trip | ✅ |
| tool_choice (none/auto/required) | ✅ |
| temperature / top_p / stop | ✅ |
| presence_penalty / frequency_penalty | ✅ |
| stream_options (include_usage) | ✅ |
| Any model name accepted | ✅ |
| Incremental streaming tool_calls | ✅ |

### Anthropic `/v1/messages`

| Feature | Status |
|---------|--------|
| Text generation (stream + non-stream) | ✅ |
| System prompt (string + content blocks) | ✅ |
| Multi-turn conversations | ✅ |
| Tool definitions (Anthropic format) | ✅ |
| tool_result round-trip | ✅ |
| tool_choice (auto/any/tool/none) | ✅ |
| Image blocks (base64 + URL) | ✅ |
| Thinking blocks (passthrough) | ✅ |
| stop_sequences | ✅ |
| SSE events (message_start/delta/stop) | ✅ |
| input_json_delta streaming | ✅ |
| count_tokens endpoint | ✅ |

## 🧹 System Prompt Sanitization

Kiro's CodeWhisperer backend injects an IDE system prompt containing tool definitions (readFile, fsWrite, webSearch, etc.) that don't exist outside the IDE. kiro2chat implements **three-layer defense**:

1. **Anti-Prompt Injection** — Prepends a high-priority override to every request, declaring the true identity (Claude by Anthropic) and explicitly denying all IDE tools
2. **Assistant Confirmation** — Injects a fake assistant turn confirming it will ignore IDE tools
3. **Response Sanitization** — Regex-based post-processing strips any leaked tool names, Kiro identity references, and XML markup from output

**Result**: 28/28 adversarial test scenarios pass with zero leakage.

## ⚙️ Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `HOST` | `0.0.0.0` | Server bind address |
| `PORT` | `8000` | API server port |
| `KIRO_DB_PATH` | `~/.local/share/kiro-cli/data.sqlite3` | kiro-cli database path |
| `API_KEY` | *(none)* | Optional API authentication key |
| `TG_BOT_TOKEN` | *(none)* | Telegram Bot token |
| `LOG_LEVEL` | `info` | Logging level |

### Config File

`~/.config/kiro2chat/config.toml` — editable via Web UI or manually.

### Model Mapping

All model names are accepted. The backend always uses `claude-opus-4.6-1m`. Common aliases:

| Client sends | Backend uses |
|---|---|
| `gpt-4o`, `gpt-4`, `gpt-3.5-turbo` | `claude-opus-4.6-1m` |
| `claude-opus-4.6-1m`, `claude-opus-4.6` | `claude-opus-4.6-1m` |
| `claude-sonnet-4.5`, `claude-sonnet-4` | `claude-opus-4.6-1m` |
| Any other string | `claude-opus-4.6-1m` |

## 🚢 Deployment

### Systemd Service

```bash
# Install service
sudo cp kiro2chat@.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now kiro2chat@$(whoami)

# Check status
sudo systemctl status kiro2chat@$(whoami)
journalctl -u kiro2chat@$(whoami) -f
```

### Docker (coming soon)

## 📁 Project Structure

```
kiro2chat/src/
├── __init__.py              # Version (__version__ = "0.5.0")
├── app.py                   # FastAPI app, lifespan, CLI, CORS, exception handlers
├── config.py                # Config (env > TOML > defaults)
├── config_manager.py        # TOML config read/write + MCP config
├── stats.py                 # Thread-safe request statistics
├── webui.py                 # Gradio multi-page Web UI
├── agent.py                 # Strands Agent + MCP tools
├── _tool_names.py           # Built-in tool name registry
├── core/
│   ├── __init__.py          # TokenManager (IdC token refresh)
│   ├── client.py            # CodeWhisperer API client (httpx async)
│   ├── converter.py         # OpenAI ↔ CodeWhisperer protocol conversion
│   ├── eventstream.py       # AWS EventStream binary parser
│   ├── sanitizer.py         # Anti-prompt + response cleansing + identity scrub
│   └── health.py            # Health check utilities
├── api/
│   ├── routes.py            # /v1/chat/completions, /v1/models (OpenAI)
│   ├── anthropic_routes.py  # /v1/messages, /v1/messages/count_tokens (Anthropic)
│   └── agent_routes.py      # /v1/agent/* (Strands Agent)
└── bot/
    └── telegram.py          # Telegram Bot (aiogram)
```

## 📊 Tech Stack

| Component | Technology |
|-----------|-----------|
| Web Framework | FastAPI + Uvicorn |
| HTTP Client | httpx (async) |
| AI Agent | Strands Agents SDK |
| Web UI | Gradio 6 |
| Telegram Bot | aiogram 3 |
| Config | python-dotenv + TOML |
| Auth | kiro-cli SQLite → AWS IdC OIDC |
| Package Manager | uv + hatchling |
| Python | ≥ 3.13 |

## 📝 Changelog

### v0.6.0 — MCP Tool Calling & Streaming Fixes (2026-02-26)

**Major: Full MCP tool calling support through client SDKs**

#### 🔧 MCP Tool Calling
- **`toolUseEvent` streaming support** — CodeWhisperer returns tool calls as incremental `toolUseEvent` chunks (name → input fragments → stop). Now correctly aggregates these into complete `tool_calls`
- **Tool result round-trip fixed** — Client MCP tools (firecrawl, etc.) can now search/scrape and return results that get correctly forwarded to the backend
- **History building fix** — Assistant messages with `toolUses` are now correctly placed in CW history during tool result round-trips (was causing 400 errors)
- **JSON content block parsing** — Client tool results sent as `[{"type":"text","text":"..."}]` strings are now correctly flattened to plain text for CW backend
- **Tool result truncation** — Long tool results (>50K chars) are truncated to prevent CW request size limits

#### 🧹 Anti-Prompt Rebalancing
- Rewrote anti-prompt to **encourage user-provided tool usage** while still blocking Kiro IDE tools
- Previous version was too aggressive — suppressed legitimate MCP tool calls (firecrawl, web search, etc.)
- Now explicitly distinguishes: IDE tools (blocked) vs. user API tools (actively used)

#### 📝 Streaming Markdown Fix
- Fixed `sanitize_text()` stripping whitespace from streaming chunks
- Was breaking Markdown rendering: `---\n\n## Title` became `---## Title`
- Streaming chunks now preserve original whitespace; only full responses get trimmed

#### 📊 Token Usage Estimation
- Added `token_counter.py` with CJK-aware character-based estimation
- OpenAI: `prompt_tokens`, `completion_tokens`, `total_tokens` in both stream and non-stream
- Anthropic: `input_tokens`, `output_tokens` in `message_start` and `message_delta` events
- `count_tokens` endpoint uses same estimator

### v0.5.0 — API Gateway (2026-02-26)

**Major upgrade: Full OpenAI + Anthropic API compatibility**

#### 🔄 Dual Protocol Support
- **Anthropic Messages API** (`/v1/messages`) — full compatibility with streaming, tools, system prompts, images, thinking blocks
- **`/v1/messages/count_tokens`** — token count estimation endpoint
- **`/v1/messages/batches`** — stub endpoint (501)

#### 🧠 Backend Model
- Fixed backend to **Claude Opus 4.6 1M** (`claude-opus-4.6-1m`)
- All model names accepted (gpt-4o, claude-sonnet-4, any string)
- Discovered correct model ID format and required `KiroIDE` User-Agent header

#### 🧹 System Prompt Sanitization (3-layer defense)
- **Anti-prompt injection**: High-priority override denying Kiro identity and IDE tools
- **Assistant confirmation**: Fake turn reinforcing Claude identity
- **Response sanitization**: Regex scrubbing of tool names, Kiro references, XML markup
- 28/28 adversarial test scenarios pass with zero leakage

#### 🛠️ OpenAI Compatibility Enhancements
- Parameter passthrough: `temperature`, `top_p`, `stop`, `presence_penalty`, `frequency_penalty`
- `tool_choice` support (`none`/`auto`/`required`/specific tool)
- `stream_options` with `include_usage`
- Tool validation (filter empty name/description)
- Incremental streaming `tool_calls` (name + arguments in separate chunks)
- `developer` role support
- Model capabilities in `/v1/models` (vision + function_calling)

#### 🔌 Anthropic Compatibility
- System prompt as string or content blocks array
- `tool_choice` conversion (`auto`/`any`/`tool`/`none`)
- Image blocks (base64 + URL) → OpenAI `image_url` conversion
- Thinking blocks passthrough
- `stop_sequences` support
- Proper SSE event sequence (`message_start` → `content_block_*` → `message_delta` → `message_stop`)
- `input_json_delta` for streaming tool input

#### 🏗️ Infrastructure
- CORS middleware (allow all origins)
- Global exception handlers (HTTP + unhandled)
- `/health` endpoint for monitoring
- systemd service template (`kiro2chat@.service`)

### v0.4.0 — Agent Integration

- Strands Agent integration (LiteLLM + MCP tools)
- Agent API endpoints (`/v1/agent/chat` stream + non-stream)
- TG Bot via Agent layer
- Built-in tools: calculator, file_read, file_write, http_request, shell
- MCP config reuse from Kiro CLI (`~/.kiro/settings/mcp.json`)

### v0.3.0 — Tool Calling

- OpenAI-compatible `tool_calls` support (stream + non-stream)
- Tool role message passback to CodeWhisperer

### v0.2.0 — Web UI

- Gradio multi-page Web UI (Navbar)
- System config page + monitoring dashboard
- TOML config file management
- Request statistics module

### v0.1.0 — Initial Release

- OpenAI-compatible API (`/v1/chat/completions`, `/v1/models`)
- kiro-cli token auto-refresh
- Stream + non-stream responses
- Telegram Bot
- Basic Gradio Web UI

## 📄 License

MIT
