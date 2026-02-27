# kiro2chat

将 Kiro CLI 的 Claude 后端封装为 OpenAI + Anthropic 兼容 API 网关，集成 Strands Agent 框架提供工具调用能力。

**[English](README.md)** | **[中文](README_CN.md)**

> ⚠️ **注意：** Kiro 后端会注入 IDE 系统提示词，包含工具定义（readFile, fsWrite, webSearch 等），这些工具只在 Kiro IDE 内有效。kiro2chat 实现了三层防御（反提示词注入 + 助手确认 + 响应清洗）来对抗这一问题。

## 功能特性

- 🔄 **双协议 API** — OpenAI `/v1/chat/completions` + Anthropic `/v1/messages`
- 🧹 **提示词清洗** — 三层防御对抗 Kiro IDE 提示词注入
- 🛠️ **Strands Agent** — 内置 + MCP 工具，通过 OpenAI 兼容 API 自回环
- 🌐 **Web UI** — Gradio 6 多页面界面（聊天、监控、设置）
- 📱 **Telegram Bot** — Agent 驱动的机器人，支持图片收发、Markdown 渲染
- 🔑 **自动 Token 管理** — 从 kiro-cli SQLite 读取并自动刷新 IdC Token
- 📊 **Token 估算** — CJK 感知的 token 计数（tiktoken + 降级方案）
- 📈 **Prometheus 监控** — 请求计数、延迟、token 统计、错误、重试

## 架构

![Architecture](docs/architecture.png)

## 快速开始

```bash
# 前置条件：kiro-cli 已安装并登录
cd ~/repos/kiro2chat
uv sync
cp .env.example .env   # 编辑配置

./kiro2chat.sh start   # 后台启动所有服务
./kiro2chat.sh status  # 查看状态
./kiro2chat.sh stop    # 停止
```

> 运行 `./kiro2chat.sh attach` 查看实时输出（`Ctrl+B D` 退出）。

或直接运行：

```bash
uv run kiro2chat all       # 全部一起启动
uv run kiro2chat api       # API 服务（端口 8000）
uv run kiro2chat webui     # Web UI（端口 7860）
uv run kiro2chat bot       # Telegram Bot
```

### 使用 OpenAI SDK

```python
from openai import OpenAI

client = OpenAI(base_url="http://localhost:8000/v1", api_key="not-needed")
response = client.chat.completions.create(
    model="claude-sonnet-4",  # 任何模型名都可以
    messages=[{"role": "user", "content": "你好！"}],
)
print(response.choices[0].message.content)
```

### 使用 Anthropic SDK

```python
import anthropic

client = anthropic.Anthropic(base_url="http://localhost:8000", api_key="not-needed")
message = client.messages.create(
    model="claude-sonnet-4",
    max_tokens=1024,
    messages=[{"role": "user", "content": "你好！"}],
)
print(message.content[0].text)
```

## API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/v1/chat/completions` | POST | OpenAI 兼容聊天（流式 + 非流式） |
| `/v1/models` | GET | 列出可用模型 |
| `/v1/messages` | POST | Anthropic Messages API（流式 + 非流式） |
| `/v1/messages/count_tokens` | POST | Token 计数估算 |
| `/v1/agent/chat` | POST | Strands Agent 聊天（SSE 流式） |
| `/v1/agent/tools` | GET | 列出已加载工具 |
| `/v1/agent/reload` | POST | 重新加载 MCP 工具 |
| `/health` | GET | 健康检查 |
| `/metrics` | GET | Prometheus 监控指标 |

## 系统提示词清洗

Kiro 后端会注入 IDE 系统提示词，包含在 IDE 外部不存在的工具定义。kiro2chat 实现了**三层防御**：

1. **反提示词注入** — 在请求前注入高优先级覆盖指令，声明 Claude 身份，否认所有 IDE 工具，同时鼓励使用用户提供的工具
2. **助手确认** — 注入助手回复，确认将忽略 IDE 工具但积极使用用户提供的工具
3. **响应清洗** — 基于正则的后处理，清除泄露的工具名、Kiro 身份引用和 XML 标记

## 项目结构

```
kiro2chat/src/
├── __init__.py           # 版本号 (__version__)
├── _tool_names.py        # 内置工具名称注册
├── app.py                # 入口，FastAPI app，lifespan，CORS，CLI
├── config.py             # 配置（env vars > config.toml > 默认值）
├── config_manager.py     # TOML 配置读写 + Kiro MCP 配置
├── log_context.py        # ContextVar 用户标签 + 日志过滤器
├── stats.py              # 线程安全的请求统计
├── metrics.py            # Prometheus 监控指标
├── agent.py              # Strands Agent + MCP 工具加载
├── webui/
│   ├── __init__.py       # create_ui(), LAUNCH_KWARGS, main()
│   ├── chat.py           # 聊天页（多模态，Agent 流式）
│   ├── monitor.py        # 监控页（统计，日志）
│   └── settings.py       # 设置页（模型配置，MCP 配置）
├── core/
│   ├── __init__.py       # TokenManager（IdC token 刷新）
│   ├── client.py         # Kiro API 客户端（httpx 异步，重试逻辑）
│   ├── converter.py      # OpenAI ↔ Kiro 协议转换
│   ├── eventstream.py    # AWS EventStream 二进制解析
│   ├── sanitizer.py      # 反提示词 + 响应清洗
│   ├── token_counter.py  # CJK 感知的 token 估算
│   └── health.py         # 健康检查工具
├── api/
│   ├── routes.py         # /v1/chat/completions, /v1/models (OpenAI)
│   ├── anthropic_routes.py # /v1/messages (Anthropic)
│   └── agent_routes.py   # /v1/agent/chat, /v1/agent/tools, /v1/agent/reload
└── bot/
    └── telegram.py       # Telegram Bot (aiogram)
```

## 技术栈

| 组件 | 技术 |
|------|------|
| Web 框架 | FastAPI + Uvicorn (async) |
| HTTP 客户端 | httpx (async, retry) |
| AI Agent | Strands Agents SDK |
| LLM Provider | strands OpenAIModel → kiro2chat API (自回环) |
| Web UI | Gradio 6 (多页面 Navbar) |
| Telegram Bot | aiogram 3 |
| 配置管理 | python-dotenv + TOML (tomllib/tomli-w) |
| 认证 | kiro-cli SQLite → AWS IdC OIDC Token Refresh |
| 监控 | Prometheus (prometheus-client) |
| 包管理 | uv + hatchling |
| Python | ≥ 3.13 |

## 配置

### 环境变量 (`.env`)

启动参数和敏感信息，详见 `.env.example`：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `TG_BOT_TOKEN` | *(无)* | Telegram Bot Token |
| `API_KEY` | *(无)* | 可选的 API 认证密钥 |
| `HOST` | `0.0.0.0` | 服务绑定地址 |
| `PORT` | `8000` | API 服务端口 |
| `LOG_LEVEL` | `info` | 日志级别（控制台） |
| `KIRO_DB_PATH` | `~/.local/share/kiro-cli/data.sqlite3` | kiro-cli 数据库路径 |
| `IDC_REFRESH_URL` | *(AWS 默认)* | AWS IdC Token 刷新端点 |
| `KIRO_API_ENDPOINT` | *(AWS 默认)* | Kiro/CodeWhisperer API 端点 |

### 模型配置 (`config.toml`)

通过 Web UI 或直接编辑 `~/.config/kiro2chat/config.toml`：

| 配置项 | 说明 |
|--------|------|
| `default_model` | 默认模型名称 |
| `model_map` | 模型名称映射 |

### 其他

- **MCP 工具**：`~/.kiro/settings/mcp.json`（复用 Kiro CLI 配置）

## 部署

参见 [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) 了解 systemd、nginx 和监控配置。

## 更新日志

参见 [CHANGELOG.md](CHANGELOG.md)

## 许可证

MIT
