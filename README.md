# kiro2chat

Kiro to Chat — 将 Kiro CLI 的 AI 能力转化为 OpenAI 兼容 API，支持流式响应。

## 功能

- 🔌 OpenAI 兼容 API (`/v1/chat/completions`, `/v1/models`)
- 🔄 自动从 kiro-cli SQLite 读取并刷新 IdC token
- 📡 流式响应 (SSE)
- 🔀 Anthropic ↔ CodeWhisperer 协议转换
- 🤖 Telegram Bot 交互 (planned)
- 🌐 Web UI Chatbot (planned)

## 架构

```
Client (OpenAI SDK / ChatBot)
    ↓ OpenAI API format
FastAPI Server (/v1/chat/completions)
    ↓ Convert to CodeWhisperer format
AWS CodeWhisperer API (generateAssistantResponse)
    ↓ EventStream binary
StreamParser → SSE (OpenAI format)
    ↓
Client receives streaming response
```

## 快速开始

```bash
# 前置条件: kiro-cli 已登录 (kiro-cli login)
uv sync
uv run kiro2chat
```

## 配置

通过环境变量或 `.env` 文件配置:

| 变量 | 默认值 | 说明 |
|---|---|---|
| `PORT` | `8000` | 服务端口 |
| `KIRO_DB_PATH` | `~/.local/share/kiro-cli/data.sqlite3` | kiro-cli 数据库路径 |
| `API_KEY` | (无) | 可选的 API 认证密钥 |
| `LOG_LEVEL` | `info` | 日志级别 |

## License

MIT
