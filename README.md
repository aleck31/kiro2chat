# kiro2chat

Kiro to Chat — 利用 Kiro CLI 的认证，将 AWS CodeWhisperer 后端的 Claude 模型封装为 OpenAI 兼容 API，并集成 Strands Agent 框架提供工具调用能力。

## 版本

**v0.4.0** — 版本号定义在 `src/__init__.py`，pyproject.toml 通过 hatch 动态读取。

## 技术架构

### 整体架构

```
┌─────────────────────────────────────────────────────────┐
│                       客户端层                            │
│  TG Bot ─┐                                              │
│  WebUI  ─┤─→ /v1/agent/chat ─→ Strands Agent           │
│  CLI    ─┘                      (built-in + MCP tools)  │
│                                       │                  │
│                                       ↓                │
│                              /v1/chat/completions        │
│                                       │                  │
├───────────────────────────────────────┼──────────────────┤
│                    协议转换层          │                  │
│              OpenAI → CodeWhisperer   │                  │
│              (converter.py)           │                  │
│                                       ↓                  │
│              EventStream 解析 ← CodeWhisperer API        │
│              (eventstream.py)                            │
├─────────────────────────────────────────────────────────┤
│                     认证层                               │
│         kiro-cli SQLite → IdC Token Refresh              │
│         (~/.local/share/kiro-cli/data.sqlite3)           │
└─────────────────────────────────────────────────────────┘
```

### ⚠️ 已知架构问题

1. **自回环死锁风险**：Strands Agent 通过 LiteLLM 以 HTTP 方式回调 localhost:8000 的 `/v1/chat/completions`。当 API server 是单 worker 时会死锁。当前临时方案是 uvicorn 开 4 workers，但这不是优雅的解决方案。**更好的做法**是让 Agent 直接调用内部的 Python 函数（`CodeWhispererClient.generate_stream`），而不是走 HTTP 回环。

2. **Kiro 后端注入的 System Prompt**：CodeWhisperer 会注入 Kiro IDE 的 system prompt，包含大量 IDE 工具定义（readFile, fsWrite, webSearch 等）。这些工具只在 Kiro IDE 内有效，通过 kiro2chat 调用时无法执行。当前用 system prompt 告知 Claude 忽略这些，但效果有限。

## 项目结构

```
kiro2chat/src/
├── __init__.py           # 版本号 (__version__)
├── _tool_names.py        # 内置工具名称注册（避免循环导入）
├── app.py                # 入口，FastAPI app，lifespan，CLI 子命令
├── config.py             # 配置（env vars > config.toml > 默认值）
├── config_manager.py     # TOML 配置读写 + Kiro MCP 配置读取
├── stats.py              # 线程安全的请求统计收集器
├── webui.py              # Gradio 多页面 Web UI (Navbar)
├── agent.py              # Strands Agent 创建、MCP 工具加载
├── core/
│   ├── __init__.py       # TokenManager 导出
│   ├── client.py         # CodeWhisperer API 客户端 (httpx async)
│   ├── converter.py      # OpenAI ↔ CodeWhisperer 协议转换
│   └── eventstream.py    # AWS EventStream 二进制协议解析
├── api/
│   ├── __init__.py
│   ├── routes.py         # /v1/chat/completions, /v1/models
│   └── agent_routes.py   # /v1/agent/chat, /v1/agent/tools, /v1/agent/reload
└── bot/
    ├── __init__.py
    └── telegram.py       # Telegram Bot (aiogram)
```

## 技术栈

| 组件 | 技术 |
|------|------|
| Web 框架 | FastAPI + Uvicorn (4 workers) |
| HTTP 客户端 | httpx (async) |
| AI Agent | Strands Agents SDK |
| LLM Provider | LiteLLM → kiro2chat API (OpenAI 兼容) |
| Web UI | Gradio 6 (Navbar 多页面) |
| Telegram Bot | aiogram 3 |
| 配置管理 | python-dotenv + TOML (tomllib/tomli-w) |
| 认证 | kiro-cli SQLite → AWS IdC OIDC Token Refresh |
| 包管理 | uv + hatchling |
| Python | ≥ 3.13 |

## 核心模块说明

### 认证链路 (`core/__init__.py` — TokenManager)
1. 从 kiro-cli 的 SQLite 数据库读取 IdC token（key: `kirocli:odic:token`）
2. 使用 IdC refresh token 向 `oidc.us-east-1.amazonaws.com/token` 刷新 access token
3. 解析 profile ARN 用于 CodeWhisperer API 调用

### 协议转换 (`core/converter.py`)
- **OpenAI → CodeWhisperer**：将 OpenAI 格式的 messages/tools 转换为 CW 的 `generateAssistantResponse` 请求格式
- System message → 注入为 history 中的首轮对话
- Tool definitions → `toolSpecification` 格式
- Tool role messages → `toolResults` in `userInputMessageContext`
- `chatTriggerType` 固定为 `MANUAL`（CW 不接受 `AUTO`）

### EventStream 解析 (`core/eventstream.py`)
- 解析 AWS EventStream 二进制协议
- 支持流式和非流式解析
- 处理 `assistantResponseEvent`、`toolUse`、`exception` 等事件类型

### API 路由 (`api/routes.py`)
- `GET /v1/models` — 列出可用模型
- `POST /v1/chat/completions` — OpenAI 兼容的聊天接口（流式/非流式）
  - 支持 tool_calls 返回（流式 chunk + 非流式 message）
  - 支持 tool role 消息回传

### Agent 路由 (`api/agent_routes.py`)
- `POST /v1/agent/chat` — 通过 Strands Agent 聊天（支持 stream=true SSE）
- `GET /v1/agent/tools` — 列出已加载工具
- `POST /v1/agent/reload` — 重新加载 MCP 工具

### Agent (`agent.py`)
- 创建 Strands Agent，使用 LiteLLM 指向 localhost:8000 的 OpenAI 兼容 API
- 内置工具：calculator, file_read, file_write, http_request, shell
- MCP 工具从 `~/.kiro/settings/mcp.json` 加载（复用 Kiro CLI 配置）
- System prompt 引导 Agent 基于 tool spec 自主判断可用工具

### Telegram Bot (`bot/telegram.py`)
- 通过 `/v1/agent/chat` 流式调用 Strands Agent
- 会话隔离：session key = `(chat_id, user_id)`
- 每会话 asyncio.Lock 防止消息乱序
- 命令：`/model`, `/tools`, `/clear`, `/help`
- 过滤原始 XML/function_calls 标记
- 最大历史 20 条消息

### Web UI (`webui.py`)
- **聊天页**：模型选择 + 工具列表 + ChatInterface（直接调 /v1/chat/completions）
- **系统配置页**：可视化编辑所有配置项，保存到 `~/.config/kiro2chat/config.toml`
- **监控面板**：请求统计、延迟、错误率、最近请求日志（5s 自动刷新）
- **Agent 页**：通过 Strands Agent 聊天 + MCP 配置编辑

### 配置 (`config.py` + `config_manager.py`)
- 优先级：环境变量 > `~/.config/kiro2chat/config.toml` > 默认值
- MCP 配置直接读取 `~/.kiro/settings/mcp.json`
- 统计收集器 (`stats.py`)：线程安全，deque 最近 100 条记录

## 模型映射

| OpenAI 名称 | CodeWhisperer ID | 状态 |
|---|---|---|
| claude-sonnet-4-5 | CLAUDE_SONNET_4_5_20250929_V1_0 | ✅ 已验证 |
| claude-sonnet-4 | CLAUDE_SONNET_4_20250514_V1_0 | ✅ 已验证 |
| claude-3.7-sonnet | CLAUDE_3_7_SONNET_20250219_V1_0 | ✅ 已验证 |
| claude-haiku-4-5 | auto | ⚠️ 未充分测试 |

参考实现：`~/repos/kiro2api/config/config.go`（Go 版本的模型映射表）

## 快速开始

```bash
# 前置条件: kiro-cli 已登录 (kiro-cli login)
cd ~/repos/kiro2chat
uv sync

uv run kiro2chat api      # API server (端口 8000, 4 workers)
uv run kiro2chat webui     # Web UI (端口 7860)
uv run kiro2chat bot       # Telegram Bot
uv run kiro2chat all       # 全部一起启动
```

## 配置

### 环境变量

| 变量 | 默认值 | 说明 |
|---|---|---|
| HOST | 0.0.0.0 | 服务绑定地址 |
| PORT | 8000 | API 服务端口 |
| KIRO_DB_PATH | ~/.local/share/kiro-cli/data.sqlite3 | kiro-cli 数据库路径 |
| API_KEY | (无) | 可选的 API 认证密钥 |
| TG_BOT_TOKEN | (无) | Telegram Bot Token |
| LOG_LEVEL | info | 日志级别 |

### 配置文件

- **系统配置**：`~/.config/kiro2chat/config.toml`（可通过 Web UI 编辑）
- **MCP 工具**：`~/.kiro/settings/mcp.json`（复用 Kiro CLI 配置）

## 参考实现

- **kiro2api**（Go）：`~/repos/kiro2api/` — 更成熟的 Go 实现，有完整的 tool lifecycle 管理、SSE 合规校验、Sonic JSON 聚合器
- **kiro2cc**：另一个逆向 Kiro 认证的项目

## Changelog

### v0.4.0
- Strands Agent 集成（LiteLLM + MCP 工具）
- Agent API endpoints（/v1/agent/chat 流式 + 非流式）
- TG Bot 改为通过 Agent 层调用
- 内置工具：calculator, file_read, file_write, http_request, shell
- MCP 配置复用 Kiro CLI (~/.kiro/settings/mcp.json)

### v0.3.0
- OpenAI 兼容 API 完整 tool_calls 支持（流式 + 非流式）
- tool role 消息回传 CodeWhisperer

### v0.2.0
- Gradio 多页面 Web UI (Navbar)
- 系统配置页 + 监控面板
- TOML 配置文件管理
- 请求统计模块

### v0.1.0
- OpenAI 兼容 API (/v1/chat/completions, /v1/models)
- kiro-cli token 自动刷新
- 流式 + 非流式响应
- Telegram Bot
- 基础 Gradio Web UI

## License

MIT
