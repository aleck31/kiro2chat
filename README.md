# kiro2chat

Wrap Kiro CLI's Claude backend into an OpenAI-compatible API, with Strands Agent integration for tool calling.

> ⚠️ **Note:** The Kiro backend injects an IDE system prompt with tool definitions (readFile, fsWrite, webSearch, etc.) that only work inside the Kiro IDE. kiro2chat uses a system prompt override to tell Claude to ignore these, but effectiveness is limited.

## Architecture

```
curl / OpenWebUI / Cursor          TG Bot / WebUI
         │                                │
         │ OpenAI format                   │
         ▼                                ▼
  /v1/chat/completions          /v1/agent/chat
         ▲                                │
         │ OpenAI format (loopback)        ▼
         └──────────────── Strands Agent
                           (built-in + MCP tools)
         │
         ▼
  OpenAI → Kiro protocol conversion
  (converter.py)
         │
         ▼
  Kiro/CodeWhisperer API
  (EventStream parser)
         │
         ▼
  kiro-cli SQLite → IdC Token
```

## Features

- 🔄 **OpenAI-Compatible API** — `/v1/chat/completions` with streaming, tool calls, multi-turn
- 🛠️ **Strands Agent** — Built-in + MCP tools, loopback through the OpenAI-compatible API
- 🌐 **Web UI** — Gradio 6 multi-page interface (chat, monitoring, settings)
- 📱 **Telegram Bot** — Agent-powered bot with image I/O, Markdown rendering
- 🔑 **Auto Token Management** — Reads and auto-refreshes IdC tokens from kiro-cli SQLite
- 🧹 **Prompt Sanitization** — Strips Kiro IDE injected prompts and tool definitions
- 📊 **Token Estimation** — CJK-aware character-based token counting

## Quick Start

```bash
# Prerequisites: kiro-cli installed and logged in
cd ~/repos/kiro2chat
uv sync

# Copy and edit environment config
cp .env.example .env

uv run kiro2chat api       # API server (port 8000)
uv run kiro2chat webui     # Web UI (port 7860)
uv run kiro2chat bot       # Telegram Bot
uv run kiro2chat all       # All together
```

### Usage with OpenAI SDK

```python
from openai import OpenAI

client = OpenAI(base_url="http://localhost:8000/v1", api_key="not-needed")
response = client.chat.completions.create(
    model="claude-sonnet-4",  # Any model name works
    messages=[{"role": "user", "content": "Hello!"}],
)
print(response.choices[0].message.content)
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/v1/chat/completions` | POST | OpenAI-compatible chat (stream + non-stream) |
| `/v1/models` | GET | List available models |
| `/v1/agent/chat` | POST | Strands Agent chat (SSE stream) |
| `/v1/agent/tools` | GET | List loaded tools |
| `/v1/agent/reload` | POST | Reload MCP tools |

## Project Structure

```
kiro2chat/src/
├── __init__.py           # Version (__version__)
├── _tool_names.py        # Built-in tool name registry
├── app.py                # Entry point, FastAPI app, lifespan, CLI subcommands
├── config.py             # Config (env vars > config.toml > defaults)
├── config_manager.py     # TOML config read/write + Kiro MCP config
├── log_context.py        # ContextVar user tag + logging filter
├── stats.py              # Thread-safe request statistics
├── agent.py              # Strands Agent + MCP tool loading
├── webui/
│   ├── __init__.py       # create_ui(), LAUNCH_KWARGS, main()
│   ├── chat.py           # Chat page (multimodal, agent streaming)
│   ├── monitor.py        # Monitoring page (stats, logs)
│   └── settings.py       # Settings page (model config, MCP config)
├── core/
│   ├── __init__.py       # TokenManager export
│   ├── client.py         # Kiro API client (httpx async)
│   ├── converter.py      # OpenAI ↔ Kiro protocol conversion
│   ├── eventstream.py    # AWS EventStream binary parser
│   ├── sanitizer.py      # Response sanitization (identity + tool scrub)
│   ├── token_counter.py  # CJK-aware token estimator
│   └── health.py         # Health check utilities
├── api/
│   ├── routes.py         # /v1/chat/completions, /v1/models
│   └── agent_routes.py   # /v1/agent/chat, /v1/agent/tools, /v1/agent/reload
└── bot/
    └── telegram.py       # Telegram Bot (aiogram)
```

## Tech Stack

| Component | Technology |
|-----------|------------|
| Web Framework | FastAPI + Uvicorn (async) |
| HTTP Client | httpx (async) |
| AI Agent | Strands Agents SDK |
| LLM Provider | strands OpenAIModel → kiro2chat API (loopback) |
| Web UI | Gradio 6 (multi-page Navbar) |
| Telegram Bot | aiogram 3 |
| Config | python-dotenv + TOML (tomllib/tomli-w) |
| Auth | kiro-cli SQLite → AWS IdC OIDC Token Refresh |
| Package Manager | uv + hatchling |
| Python | ≥ 3.13 |

## Configuration

### Environment Variables (`.env`)

Startup params and secrets, see `.env.example`:

| Variable | Default | Description |
|----------|---------|-------------|
| `TG_BOT_TOKEN` | *(none)* | Telegram Bot token |
| `API_KEY` | *(none)* | Optional API authentication key |
| `HOST` | `0.0.0.0` | Server bind address |
| `PORT` | `8000` | API server port |
| `LOG_LEVEL` | `info` | Log level (console handler) |
| `KIRO_DB_PATH` | `~/.local/share/kiro-cli/data.sqlite3` | kiro-cli database path |
| `IDC_REFRESH_URL` | *(AWS default)* | AWS IdC token refresh endpoint |
| `KIRO_API_ENDPOINT` | *(AWS default)* | Kiro/CodeWhisperer API endpoint |

### Model Config (`config.toml`)

Editable via Web UI or directly at `~/.config/kiro2chat/config.toml`:

| Key | Description |
|-----|-------------|
| `default_model` | Default model name |
| `model_map` | Model name mapping |

### Other

- **MCP tools**: `~/.kiro/settings/mcp.json` (reuses Kiro CLI config)

## Changelog

See [CHANGELOG.md](CHANGELOG.md)

## License

MIT
