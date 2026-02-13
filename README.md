# kiro2chat

Kiro to Chat — 将 Kiro CLI 的 AI 能力转化为 OpenAI 兼容 API，支持流式响应。

## 功能

- 🔌 OpenAI 兼容 API (`/v1/chat/completions`, `/v1/models`)
- 🔄 自动从 kiro-cli SQLite 读取并刷新 IdC token
- 📡 流式响应 (SSE)
- 🔀 Anthropic ↔ CodeWhisperer 协议转换
- 🤖 Telegram Bot 交互
- 🌐 Gradio Web UI — 多页面应用
  - 💬 聊天页面 — 与 Claude 实时对话
  - ⚙️ 系统配置 — 可视化编辑所有配置项，保存到 TOML 文件
  - 📊 监控面板 — 请求统计、延迟、错误率、最近请求日志、系统状态
- 📈 内置请求统计与监控
- 📄 TOML 配置文件支持（`~/.config/kiro2chat/config.toml`）

## 架构

```
Client (OpenAI SDK / ChatBot / TG Bot)
    ↓ OpenAI API format
FastAPI Server (/v1/chat/completions)
    ↓ Convert to CodeWhisperer format
AWS CodeWhisperer API (generateAssistantResponse)
    ↓ EventStream binary
StreamParser → SSE (OpenAI format)
    ↓
Client receives streaming response
```

```
kiro2chat/
├── app.py              # 入口，lifespan 管理，CLI 子命令
├── config.py           # 配置（env > config.toml > 默认值）
├── config_manager.py   # TOML 配置文件读写
├── stats.py            # 线程安全的请求统计收集器
├── webui.py            # Gradio 多页面 Web UI (Navbar)
├── core/
│   ├── client.py       # CodeWhisperer API 客户端 (httpx async)
│   ├── converter.py    # OpenAI ↔ CW 协议转换
│   └── eventstream.py  # AWS event-stream 二进制协议解析
├── api/
│   └── routes.py       # /v1/chat/completions, /v1/models
└── bot/
    └── telegram.py     # Telegram Bot (aiogram)
```

## 快速开始

```bash
# 前置条件: kiro-cli 已登录 (kiro-cli login)
uv sync
uv run kiro2chat          # 启动 API server (默认端口 8000)
uv run kiro2chat webui    # 启动 Web UI (端口 7860)
uv run kiro2chat bot      # 启动 Telegram Bot
uv run kiro2chat all      # 全部一起启动
```

## 配置

### 优先级

环境变量 > `~/.config/kiro2chat/config.toml` > 默认值

### 配置项

| 变量 | 默认值 | 说明 |
|---|---|---|
| `HOST` | `0.0.0.0` | 服务绑定地址 |
| `PORT` | `8000` | API 服务端口 |
| `KIRO_DB_PATH` | `~/.local/share/kiro-cli/data.sqlite3` | kiro-cli 数据库路径 |
| `API_KEY` | (无) | 可选的 API 认证密钥 |
| `TG_BOT_TOKEN` | (无) | Telegram Bot Token |
| `LOG_LEVEL` | `info` | 日志级别 |

### 配置文件

也可以通过 Web UI 的「系统配置」页面可视化编辑，保存到 `~/.config/kiro2chat/config.toml`：

```toml
[server]
host = "0.0.0.0"
port = 8000
log_level = "info"

[auth]
api_key = ""

[kiro]
kiro_db_path = "/home/user/.local/share/kiro-cli/data.sqlite3"

[telegram]
tg_bot_token = ""

[model]
default_model = "claude-sonnet-4-20250514"

[model.model_map]
"claude-sonnet-4" = "CLAUDE_SONNET_4_20250514_V1_0"
"claude-sonnet-4-20250514" = "CLAUDE_SONNET_4_20250514_V1_0"
```

## Changelog

### v0.4.0
- 🤖 Strands Agents 集成
  - 新增 `agent.py` — Strands Agent + LiteLLM 模型（指向 kiro2chat API）
  - MCP 工具支持：从 `~/.config/kiro2chat/mcp.json` 加载 MCP servers
  - 新增 CLI 子命令 `kiro2chat agent` — 终端交互式 Agent 聊天
  - 新增 API 端点：`/v1/agent/chat`, `/v1/agent/tools`, `/v1/agent/reload`
  - Web UI 新增「🤖 Agent」页面 — 带 MCP 工具的 Agent 聊天
  - 设置页面新增 MCP 配置编辑器
- 📦 新增依赖：strands-agents, strands-agents-tools, litellm

### v0.3.0
- 🔧 完整的 tool_calls 支持（兼容 OpenAI function calling / Strands Agents）
  - 流式响应：`toolUse` 事件转换为 OpenAI `tool_calls` delta chunks
  - 非流式响应：收集 tool_calls 并返回完整响应
  - `finish_reason: "tool_calls"` 当有工具调用时
- 🔄 converter.py：支持 `role="tool"` 消息转换为 CW `toolResults` 格式
- 🔄 converter.py：支持 assistant `tool_calls` 转换为 CW `toolUses` 历史格式
- 📦 代码重构：routes.py 提取公共辅助函数，减少重复代码

### v0.2.0
- ✨ Gradio 多页面 Web UI (Navbar 导航)
  - 💬 聊天页面 + 模型选择
  - ⚙️ 系统配置页面（可视化编辑 + TOML 保存）
  - 📊 监控面板（实时统计 + 请求日志 + 5s 自动刷新）
- 📈 内置请求统计模块 (StatsCollector)
- 📄 TOML 配置文件管理 (`~/.config/kiro2chat/config.toml`)
- 🔧 配置优先级：环境变量 > config.toml > 默认值

### v0.1.0
- 🔌 OpenAI 兼容 API (`/v1/chat/completions`, `/v1/models`)
- 🔄 kiro-cli token 自动刷新
- 📡 流式 + 非流式响应
- 🤖 Telegram Bot
- 🌐 基础 Gradio Web UI

## License

MIT
