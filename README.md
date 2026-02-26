<div align="center">
  <img src="docs/logo.png" alt="kiro2chat logo" width="128" height="128">
  <h1>kiro2chat</h1>
  <p><strong>Kiro → Standard API Gateway</strong></p>
  <p>Wrap Kiro CLI's Claude Opus 4.6 backend into a fully compatible OpenAI + Anthropic API Gateway</p>

  **[English](README.md)** | **[中文](README_CN.md)**

  ![Python](https://img.shields.io/badge/python-≥3.13-blue?logo=python&logoColor=white)
  ![FastAPI](https://img.shields.io/badge/FastAPI-0.129+-green?logo=fastapi&logoColor=white)
  ![License](https://img.shields.io/badge/license-MIT-blue)
  ![Version](https://img.shields.io/badge/version-1.0.0-purple)
</div>

---

## ✨ Features

- 🔄 **Dual Protocol** — Supports both OpenAI `/v1/chat/completions` and Anthropic `/v1/messages` formats
- 🧠 **Claude Opus 4.6 1M** — Backend always uses the most powerful model with 1M context window
- 🧹 **System Prompt Sanitization** — Three-layer defense to strip Kiro IDE injected prompts and tool definitions
- 🛠️ **Full Tool Calling** — Tool definitions, tool_choice, tool_result round-trip, MCP tool support
- 📡 **Stream + Non-Stream** — Both API formats support SSE streaming and synchronous responses
- 🔑 **Auto Token Management** — Reads and auto-refreshes IdC tokens from kiro-cli SQLite
- 📊 **Token Usage Estimation** — CJK-aware character-based token counting
- 🤖 **Strands Agent** — Optional agent layer with MCP tool support
- 🌐 **Web UI** — Gradio multi-page interface (chat, monitoring, config)
- 📱 **Telegram Bot** — Bot powered by the agent layer

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
| MCP tool calling | ✅ |
| Token usage estimation | ✅ |

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
| Token usage estimation | ✅ |

## 🧹 System Prompt Sanitization

Kiro's CodeWhisperer backend injects an IDE system prompt containing tool definitions (readFile, fsWrite, webSearch, etc.) that don't exist outside the IDE. kiro2chat implements **three-layer defense**:

1. **Anti-Prompt Injection** — Prepends a high-priority override declaring the true identity (Claude by Anthropic) and explicitly denying all IDE tools while encouraging user-provided tools
2. **Assistant Confirmation** — Injects a fake assistant turn confirming it will ignore IDE tools but actively use user-provided tools
3. **Response Sanitization** — Regex-based post-processing strips leaked tool names, Kiro identity references, and XML markup

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
sudo cp kiro2chat@.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now kiro2chat@$(whoami)
```

### Environment Variables

```bash
nohup env API_KEY="your-key" PORT="8800" HOST="0.0.0.0" \
  uv run kiro2chat api > /tmp/kiro2chat.log 2>&1 &
```

## 📁 Project Structure

```
kiro2chat/src/
├── __init__.py              # Version
├── app.py                   # FastAPI app, lifespan, CORS, exception handlers
├── config.py                # Config (env > TOML > defaults)
├── config_manager.py        # TOML config read/write + MCP config
├── stats.py                 # Thread-safe request statistics
├── webui.py                 # Gradio multi-page Web UI
├── agent.py                 # Strands Agent + MCP tools
├── core/
│   ├── __init__.py          # TokenManager (IdC token refresh)
│   ├── client.py            # CodeWhisperer API client (httpx async)
│   ├── converter.py         # OpenAI <-> CodeWhisperer protocol conversion
│   ├── eventstream.py       # AWS EventStream binary parser
│   ├── sanitizer.py         # Anti-prompt + response cleansing + identity scrub
│   ├── health.py            # Health check utilities
│   └── token_counter.py     # CJK-aware token estimator
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

### v1.0.0 — Production Release (2026-02-27)

#### 📦 Production Ready
- **loguru** logging framework — structured, colorized, with stdlib interception
- **Prometheus /metrics** — requests, latency histogram, tokens, tool calls, errors, retries
- **Swagger /docs** — full OpenAPI documentation with endpoint descriptions
- **39 pytest tests** — sanitizer, token counter, converter, routes

#### 🔧 Streaming Enhancements
- **Incremental tool_calls** — arguments sent in ~40 char chunks (OpenAI standard)
- **Anthropic thinking blocks** — passthrough support for extended thinking

#### 📝 Documentation
- **docs/DEPLOYMENT.md** — complete deployment guide (systemd, nginx, monitoring)
- **CONTRIBUTING.md** — development setup and PR guidelines
- Bilingual README (EN/CN) with full changelog

### v0.9.0 — Retry Logic, Test Suite & Code Quality (2026-02-27)

#### 🔄 Robustness
- **CW backend retry** — 5xx errors and timeouts retry with exponential backoff (1s → 3s → 10s, max 3 attempts)
- **2-hour client timeout** — `httpx` read timeout set to 7200s matching Nginx, no premature disconnects on long outputs
- **Request ID** — Every request gets an `x-request-id` header for tracing and debugging
- **API key security** — Moved from systemd unit file to `EnvironmentFile` with 600 permissions

#### 🧪 Test Suite
- **39 pytest tests** across 4 modules:
  - `test_sanitizer` — identity scrub, tool filtering, streaming whitespace, anti-prompt
  - `test_token_counter` — tiktoken accuracy, CJK, message counting
  - `test_converter` — model override, anti-prompt injection, tool results, image extraction
  - `test_routes` — tool validation, filtering

#### 📦 Code Quality
- **ruff** linting config (line-length=120, Python 3.13)
- **CONTRIBUTING.md** — development setup, testing, PR guidelines
- **pytest** config in `pyproject.toml`

### v0.8.0 — Accurate Token Counting & Nginx Optimization (2026-02-26)

#### 📊 Accurate Token Counting
- Replaced character-based heuristic with **tiktoken cl100k_base** encoding
- Chinese text accuracy improved from ±48% error to **exact match**
- All token counts now match OpenAI's tokenizer precisely
- Graceful fallback to heuristic if tiktoken unavailable

#### 🔧 Nginx Optimization
- `proxy_read_timeout` / `proxy_send_timeout`: 300s → **7200s** (2 hours for long outputs)
- `proxy_http_version`: added **1.1** (required for SSE streaming)
- `proxy_connect_timeout`: added **60s**
- `chunked_transfer_encoding`: **on**, `proxy_cache`: **off**

### v0.7.0 — Image Support & Production Deployment (2026-02-26)

#### 🖼️ Image Support
- OpenAI `image_url` (data URI base64) → CW `images` format conversion
- Anthropic `image` blocks (base64 + URL) → CW `images` format conversion
- Tested: pixel color recognition works end-to-end through public endpoint

#### 🔧 Production Deployment
- **systemd service** — `Restart=always` with 3s delay, auto-start on boot
- Replaces nohup/supervisor.sh with proper process management
- `journalctl -u kiro2chat -f` for unified log viewing

### v0.6.0 — MCP Tool Calling & Streaming Fixes (2026-02-26)

**Major: Full MCP tool calling support through client SDKs**

#### MCP Tool Calling
- `toolUseEvent` streaming support — aggregates incremental chunks into complete tool_calls
- Tool result round-trip fixed — client MCP tools can search/scrape and return results correctly
- History building fix — assistant messages with toolUses correctly placed in CW history
- JSON content block parsing — nested content blocks flattened to plain text for CW backend
- Tool result truncation at 50K chars

#### Anti-Prompt Rebalancing
- Rewrote anti-prompt to encourage user-provided tool usage while blocking Kiro IDE tools
- Explicitly distinguishes: IDE tools (blocked) vs. user API tools (actively used)

#### Streaming Markdown Fix
- Fixed `sanitize_text()` stripping whitespace from streaming chunks
- Streaming chunks now preserve original whitespace for proper Markdown rendering

#### Token Usage Estimation
- Added `token_counter.py` with CJK-aware character-based estimation
- OpenAI: `prompt_tokens`, `completion_tokens`, `total_tokens`
- Anthropic: `input_tokens`, `output_tokens`

### v0.5.0 — API Gateway (2026-02-26)

- Full OpenAI + Anthropic dual protocol support
- Backend fixed to Claude Opus 4.6 1M
- Three-layer system prompt sanitization (28/28 tests pass)
- Parameter passthrough, tool_choice, tool validation
- CORS, global exception handlers, health check
- systemd service template

### v0.4.0 — Agent Integration
### v0.3.0 — Tool Calling
### v0.2.0 — Web UI
### v0.1.0 — Initial Release

## 👥 Contributors

<table>
  <tr>
    <td align="center">
      <a href="https://github.com/aleck">
        <img src="https://github.com/aleck.png?size=100" width="100" height="100" style="border-radius:50%" alt="Aleck"/><br/>
        <sub><b>Aleck</b></sub>
      </a><br/>
      <sub>Original Author</sub>
    </td>
    <td align="center">
      <a href="https://github.com/neosun100">
        <img src="https://github.com/neosun100.png?size=100" width="100" height="100" style="border-radius:50%" alt="Neo"/><br/>
        <sub><b>Neo</b></sub>
      </a><br/>
      <sub>API Gateway & Sanitization</sub>
    </td>
  </tr>
</table>

**[Aleck](https://github.com/aleck)** designed the core architecture — CodeWhisperer protocol reverse engineering, EventStream binary parser, and kiro-cli token management.

**[Neo](https://github.com/neosun100)** extended the project into a production-ready API Gateway:
- Full OpenAI + Anthropic dual-protocol compatibility
- Three-layer system prompt sanitization (28/28 adversarial tests pass)
- MCP tool calling with `toolUseEvent` streaming aggregation
- Image support (OpenAI `image_url` + Anthropic `image` blocks)
- Accurate token counting via tiktoken
- Nginx optimization for long-running SSE streams
- systemd production deployment
- Bilingual documentation (EN/CN)

We welcome contributions from the community! Whether it's bug fixes, new features, documentation improvements, or test cases — all contributions are appreciated.

## 📄 License

MIT
