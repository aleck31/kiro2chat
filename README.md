# kiro2chat

Kiro to Chat — 利用 Kiro CLI 的认证，将 AWS Kiro/CodeWhisperer 后端的 Claude 模型封装为 OpenAI 兼容 API，并集成 Strands Agent 框架提供工具调用能力。


> ⚠️ 注意：**Kiro 后端注入的 System Prompt**，包含大量 IDE 工具定义（readFile, fsWrite, webSearch 等）。这些工具只在 Kiro IDE 内有效，通过 kiro2chat 调用时无法执行。当前用 system prompt 告知 Claude 忽略这些，但效果有限。

## 技术架构

### 整体架构

```
curl / OpenWebUI / Cursor          TG Bot / WebUI
         │                                │
         │ OpenAI 格式                     │
         ▼                                ▼
  /v1/chat/completions          /v1/agent/chat
         ▲                                │
         │ OpenAI 格式（自回环）            ▼
         └──────────────── Strands Agent
                           (built-in + MCP tools)
         │
         ▼
  OpenAI → Kiro 协议转换
  (converter.py)
         │
         ▼
  Kiro/CodeWhisperer API
  (EventStream 解析)
         │
         ▼
  kiro-cli SQLite → IdC Token
```

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
│   ├── client.py         # Kiro API 客户端 (httpx async)
│   ├── converter.py      # OpenAI ↔ Kiro 协议转换
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
| Web 框架 | FastAPI + Uvicorn (async) |
| HTTP 客户端 | httpx (async) |
| AI Agent | Strands Agents SDK |
| LLM Provider | strands OpenAIModel → kiro2chat API (OpenAI 兼容) |
| Web UI | Gradio 6 (Navbar 多页面) |
| Telegram Bot | aiogram 3 |
| 配置管理 | python-dotenv + TOML (tomllib/tomli-w) |
| 认证 | kiro-cli SQLite → AWS IdC OIDC Token Refresh |
| 包管理 | uv + hatchling |
| Python | ≥ 3.13 |

## 应用模块说明

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
- 创建 Strands Agent，使用 OpenAIModel 回调 localhost:8000 的 OpenAI 兼容 API（自回环）
- 内置工具：calculator, file_read, file_write, http_request, shell
- MCP 工具从 `~/.kiro/settings/mcp.json` 加载（复用 Kiro CLI 配置）
- System prompt 引导 Agent 基于 tool spec 自主判断可用工具

### Telegram Bot (`bot/telegram.py`)
- 通过 `/v1/agent/chat` 流式调用 Strands Agent
- 实时显示工具调用状态（`🔧 tool_name: brief_input...`）
- 会话隔离：session key = `(chat_id, user_id)`
- 每会话 asyncio.Lock 防止消息乱序
- 命令：`/model`, `/tools`, `/clear`, `/help`
- 过滤原始 XML/function_calls 标记
- 最大历史 20 条消息

### Web UI (`webui.py`)
- **聊天页**：模型选择（默认 `config.default_model`）+ 工具列表 + ChatInterface
  - 流式 SSE 渲染，实时显示 `🔧 工具名: 参数...` 进度状态
- **系统配置页**：可视化编辑所有配置项，保存到 `~/.config/kiro2chat/config.toml`
- **监控面板**：请求统计、延迟、错误率、最近请求日志（5s 自动刷新）

### 配置 (`config.py` + `config_manager.py`)
- 优先级：环境变量 > `~/.config/kiro2chat/config.toml` > 默认值
- MCP 配置直接读取 `~/.kiro/settings/mcp.json`
- 统计收集器 (`stats.py`)：线程安全，deque 最近 100 条记录

## 快速开始

```bash
# 前置条件: kiro-cli 已登录 (kiro-cli login)
cd ~/repos/kiro2chat
uv sync

uv run kiro2chat api      # API server (端口 8000, 单 worker)
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

## Changelog

### v0.6.0
- 修复 `toolUseEvent` 解析：Kiro 流式分块传输工具调用输入，累积 `input_chunks` 至 `stop=True` 后组装完整 tool_call
- 新增 `_accumulate_tool_use_event()` 处理多块 tool input，替换原错误的 `toolUse` 事件处理
- 修复 shell 工具阻塞：添加 `STRANDS_NON_INTERACTIVE=true` 环境变量，禁用 PTY 和交互确认
- 修复 AWS CLI pager 阻塞：`.env` 添加 `AWS_PAGER=`，子进程继承空值禁用 `less`
- TG Bot 工具调用实时状态：`tool_start` 事件显示 `🔧 name: brief_input...`，`_brief_tool_input()` 按工具类型提取关键参数
- WebUI 聊天改为流式 SSE：`agent_chat_fn` 从阻塞 `httpx.post` 改为 generator + `httpx.stream`，实时渲染工具使用进度
- 修复 `/v1/agent/reload` 500 错误：移除不适用的 `tool_registry.process_tools()` 调用，reload 仅重启 MCP 连接

### v0.5.0
- 修复 Agent 自回环死锁：非流式路径改用 `await invoke_async()`，移除多 worker
- Agent /chat 支持 per-request 切换模型
- 统一 MCP 配置源为 `~/.kiro/settings/mcp.json`，修复 webui 标注错误
- 跳过 http/sse 类型 MCP server（不再崩溃）
- 修复 `mcp.client.stdio` 与 gradio 的循环导入死锁
- Telegram bot 模型列表改为从 `/v1/models` 动态获取

### v0.4.0
- Strands Agent 集成（OpenAIModel 自回环 + MCP 工具）
- Agent API endpoints（/v1/agent/chat 流式 + 非流式）
- TG Bot 改为通过 Agent 层调用
- 内置工具：calculator, file_read, file_write, http_request, shell
- MCP 配置复用 Kiro CLI (~/.kiro/settings/mcp.json)

### v0.3.0
- OpenAI 兼容 API 完整 tool_calls 支持（流式 + 非流式）
- tool role 消息回传 Kiro

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
