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
│   ├── routes.py         # /v1/chat/completions, /v1/models
│   └── agent_routes.py   # /v1/agent/chat, /v1/agent/tools, /v1/agent/reload
└── bot/
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

## 功能模块说明

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

### Web UI (`webui.py`)
- **聊天页**：模型选择（默认 `config.default_model`）+ 工具列表 + ChatInterface
  - 流式 SSE 渲染，实时显示 `🔧 工具名: 参数...` 进度状态
- **系统配置页**：可视化编辑模型配置，保存到 `~/.config/kiro2chat/config.toml`
- **监控面板**：请求统计、延迟、错误率、最近请求日志（5s 自动刷新）

### Telegram Bot (`bot/telegram.py`)
- 通过 `/v1/agent/chat` 流式调用 Strands Agent
- 实时显示工具调用状态（`🔧 tool_name: brief_input...`）
- Markdown 渲染：`_md_to_html()` 转换为 Telegram HTML（bold、italic、code、code block）
- 表格渲染：`_table_to_pre()` 将 Markdown 表格转为等宽对齐文本（CJK 双倍宽度）
- 图片输入：支持 photo 和 document（大图/PNG）两种方式发送图片给 Agent
- 图片输出：Agent 生成的图片自动通过 `send_photo` 发送到聊天窗口
- 会话隔离：session key = `(chat_id, user_id)`
- 每会话 asyncio.Lock 防止消息乱序
- 命令：`/model`, `/tools`, `/clear`, `/help`
- 过滤原始 XML/function_calls 标记
- 最大历史 20 条消息

### 配置模块 (`config.py` + `config_manager.py`)
- `.env`：启动参数 + secrets（启动时读一次）
- `config.toml`：模型配置（Web UI 可编辑）
- MCP 配置直接读取 `~/.kiro/settings/mcp.json`
- 统计收集器 (`stats.py`)：线程安全，deque 最近 100 条记录

## 快速开始

```bash
# 前置条件: kiro-cli 已登录 (kiro-cli login)
cd ~/repos/kiro2chat
uv sync

# 复制环境变量配置并按需修改
cp .env.example .env
# 编辑 .env，填入 TG_BOT_TOKEN 等配置

uv run kiro2chat api      # API server (端口 8000, 基础服务)
uv run kiro2chat webui     # Web UI (端口 7860)
uv run kiro2chat bot       # Telegram Bot
uv run kiro2chat all       # 全部一起启动
```

## 配置

### 环境变量 (`.env`)

启动参数和敏感信息，详见 `.env.example`：

| 变量 | 默认值 | 说明 |
|---|---|---|
| TG_BOT_TOKEN | (无) | Telegram Bot Token |
| API_KEY | (无) | 可选的 API 认证密钥 |
| HOST | 0.0.0.0 | 服务绑定地址 |
| PORT | 8000 | API 服务端口 |
| LOG_LEVEL | info | 日志级别 |
| KIRO_DB_PATH | ~/.local/share/kiro-cli/data.sqlite3 | kiro-cli 数据库路径 |
| IDC_REFRESH_URL | (AWS 默认) | AWS IdC Token 刷新端点 |
| KIRO_API_ENDPOINT | (AWS 默认) | Kiro/CodeWhisperer API 端点 |

### 模型配置 (`config.toml`)

通过 Web UI 或直接编辑 `~/.config/kiro2chat/config.toml`：

| 配置项 | 说明 |
|---|---|
| default_model | 默认模型 |
| model_map | 模型名称映射 |

### 其他配置

- **MCP 工具**：`~/.kiro/settings/mcp.json`（复用 Kiro CLI 配置）

## Changelog

See [CHANGELOG.md](CHANGELOG.md)

## License

MIT
