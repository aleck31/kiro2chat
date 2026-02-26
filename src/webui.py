"""Gradio Web UI for kiro2chat - Multi-page app with Navbar."""

import json
import platform
from datetime import datetime, timezone, timedelta

import httpx
import gradio as gr

from .config import config
from .config_manager import load_config_file, save_config_file, load_mcp_config, save_mcp_config
from .stats import stats

API_BASE = "http://localhost:8000"
TZ_CST = timezone(timedelta(hours=8))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_models() -> list[str]:
    try:
        resp = httpx.get(f"{API_BASE}/v1/models", timeout=5)
        resp.raise_for_status()
        return [m["id"] for m in resp.json()["data"]]
    except Exception:
        return list(config.model_map.keys())


def chat_stream(message: str, history: list[dict], model: str):
    messages = [{"role": m["role"], "content": m["content"]} for m in history]
    messages.append({"role": "user", "content": message})

    with httpx.stream(
        "POST",
        f"{API_BASE}/v1/chat/completions",
        json={"model": model, "messages": messages, "stream": True},
        timeout=120,
    ) as resp:
        resp.raise_for_status()
        full = ""
        for line in resp.iter_lines():
            if not line.startswith("data: "):
                continue
            data = line[6:]
            if data == "[DONE]":
                break
            chunk = json.loads(data)
            delta = chunk["choices"][0]["delta"].get("content", "")
            if delta:
                full += delta
                yield full


# ---------------------------------------------------------------------------
# Config page helpers
# ---------------------------------------------------------------------------

def load_config_values():
    cfg = load_config_file()
    c = config
    return (
        cfg.get("default_model", c.default_model),
        json.dumps(cfg.get("model_map", dict(c.model_map)), indent=2, ensure_ascii=False),
    )


def save_config(default_model, model_map_json):
    try:
        model_map = json.loads(model_map_json) if model_map_json.strip() else {}
    except json.JSONDecodeError as e:
        return f"❌ model_map JSON 解析错误: {e}"

    data = {
        "default_model": default_model,
        "model_map": model_map,
    }
    try:
        save_config_file(data)
        return "✅ 配置已保存！重启服务后生效。"
    except Exception as e:
        return f"❌ 保存失败: {e}"


# ---------------------------------------------------------------------------
# Monitoring page helpers
# ---------------------------------------------------------------------------

def get_stats_display():
    s = stats.get_summary()
    uptime_s = s["uptime_seconds"]
    h, rem = divmod(int(uptime_s), 3600)
    m, sec = divmod(rem, 60)
    uptime_str = f"{h}h {m}m {sec}s"

    summary_md = f"""### 📊 请求统计
| 指标 | 值 |
|------|-----|
| 总请求数 | {s['total_requests']} |
| 成功 | {s['total_success']} |
| 错误 | {s['total_errors']} |
| 平均延迟 | {s['avg_latency_ms']:.1f} ms |
"""

    sys_md = f"""### 🖥️ 系统信息
| 项目 | 值 |
|------|-----|
| 运行时间 | {uptime_str} |
| Python | {platform.python_version()} |
| 平台 | {platform.platform()} |
| 默认模型 | {config.default_model} |
"""

    try:
        resp = httpx.get(f"{API_BASE}/", timeout=3)
        api_status = "🟢 运行中" if resp.status_code == 200 else f"🔴 状态码 {resp.status_code}"
    except Exception:
        api_status = "🔴 无法连接"

    token_md = f"""### 🔑 服务状态
| 项目 | 值 |
|------|-----|
| API 服务 | {api_status} |
| 可用模型 | {', '.join(config.model_map.keys())} |
"""

    return summary_md, sys_md, token_md


def get_recent_logs():
    records = stats.get_recent(20)
    if not records:
        return "暂无请求记录"

    rows = []
    for r in reversed(records):
        ts = datetime.fromtimestamp(r.timestamp, tz=TZ_CST).strftime("%H:%M:%S")
        status_icon = "✅" if r.status == "ok" else "❌"
        err = f" ({r.error[:40]})" if r.error else ""
        rows.append(f"| {ts} | {r.model} | {r.latency_ms:.0f}ms | {status_icon}{err} |")

    header = "| 时间 | 模型 | 延迟 | 状态 |\n|------|------|------|------|\n"
    return "### 📋 最近请求\n" + header + "\n".join(rows)


def refresh_monitoring():
    summary_md, sys_md, token_md = get_stats_display()
    logs_md = get_recent_logs()
    return summary_md, sys_md, token_md, logs_md


# ---------------------------------------------------------------------------
# Build UI
# ---------------------------------------------------------------------------

def _get_tools_display() -> str:
    """Build markdown display of actually loaded tools from the running API."""
    from ._tool_names import BUILTIN_TOOL_NAMES

    lines = ["### 🛠 工具列表\n", "**内置工具:**"]
    for name in BUILTIN_TOOL_NAMES:
        lines.append(f"- `{name}`")

    try:
        resp = httpx.get(f"{API_BASE}/v1/agent/tools", timeout=5)
        resp.raise_for_status()
        data = resp.json()
        mcp_servers = data.get("mcp", [])
        total = data.get("total_mcp_tools", 0)

        if mcp_servers:
            lines.append(f"\n**MCP 工具 ({len(mcp_servers)} servers / {total} tools):**")
            for s in mcp_servers:
                name = s["server"]
                cmd = s.get("command", "?")
                args = " ".join(s.get("args", [])[:2])
                tc = s.get("tool_count", 0)
                status = s.get("status", "")
                if status == "ok":
                    lines.append(f"- `{name}` — {cmd} {args} ({tc} tools)")
                else:
                    lines.append(f"- `{name}` — {cmd} {args} ⚠️ {status}")
        else:
            lines.append("\n**MCP 工具:** (无)")
    except Exception as e:
        lines.append(f"\n**MCP 工具:** ⚠️ 无法获取 ({e})")

    return "\n".join(lines)


def create_ui() -> gr.Blocks:
    models = get_models()
    default_model = config.default_model if config.default_model in models else (models[0] if models else "")

    # ---- Kiro Chat Home Page ----
    with gr.Blocks(title="kiro2chat") as demo:

        gr.Markdown("# 🤖 kiro2chat\nChat with Kiro (with MCP tools)")

        # Hidden state to bridge model dropdown (rendered below) into ChatInterface
        model_state = gr.State(value=default_model)

        def agent_chat_fn(message: str, history: list[dict], model: str):
            def _brief(name: str, inp) -> str:
                if isinstance(inp, str):
                    try:
                        inp = json.loads(inp)
                    except Exception:
                        return inp[:80]
                if not isinstance(inp, dict):
                    return str(inp)[:80]
                if name == "shell":
                    cmd = inp.get("command", "")
                    if isinstance(cmd, list):
                        cmd = cmd[0] if cmd else ""
                    return f"`{str(cmd)[:80]}`"
                if name in ("file_read", "file_write"):
                    return f"`{inp.get('path', '')}`"
                if name == "calculator":
                    return f"`{inp.get('expression', '')}`"
                if name == "http_request":
                    return f"{inp.get('method', 'GET')} {inp.get('url', '')[:60]}"
                if inp:
                    k, v = next(iter(inp.items()))
                    return f"{k}={str(v)[:40]}"
                return ""

            try:
                full_text = ""
                tool_status = ""

                with httpx.stream(
                    "POST",
                    f"{API_BASE}/v1/agent/chat",
                    json={"message": message, "model": model, "stream": True},
                    timeout=120,
                ) as resp:
                    resp.raise_for_status()
                    for line in resp.iter_lines():
                        if not line.startswith("data: "):
                            continue
                        data_str = line[6:]
                        if data_str == "[DONE]":
                            break
                        try:
                            event = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue

                        evt_type = event.get("type", "")

                        if evt_type == "data":
                            full_text += event.get("content", "")
                            tool_status = ""
                            yield full_text

                        elif evt_type == "tool_start":
                            name = event.get("name", "")
                            inp = event.get("input", {})
                            brief = _brief(name, inp)
                            tool_status = f"🔧 *{name}*" + (f": {brief}" if brief else "") + "..."
                            prefix = full_text + "\n\n" if full_text else ""
                            yield prefix + tool_status

                        elif evt_type == "tool_end":
                            tool_status = ""
                            if full_text:
                                yield full_text

                        elif evt_type == "error":
                            prefix = full_text + "\n\n" if full_text else ""
                            yield prefix + f"❌ {event.get('message', 'Unknown error')}"
                            return

            except Exception as e:
                yield f"❌ Error: {e}"

        gr.ChatInterface(
            fn=agent_chat_fn,
            additional_inputs=[model_state],
        )

        # --- model selector + tools ---
        with gr.Row():
            model_dd = gr.Dropdown(
                choices=models,
                value=default_model or None,
                label="模型选择",
                interactive=True,
                scale=3,
            )
            reload_btn = gr.Button("🔄 Reload MCP Tools", scale=1)

        model_dd.change(fn=lambda x: x, inputs=[model_dd], outputs=[model_state])

        tools_display = gr.Markdown(_get_tools_display())
        reload_status = gr.Markdown("")

        def reload_tools():
            try:
                resp = httpx.post(f"{API_BASE}/v1/agent/reload", timeout=30)
                resp.raise_for_status()
                data = resp.json()
                tc = data.get("tool_count", 0)
                return (
                    _get_tools_display(),
                    f"✅ Reloaded: {tc} tools from {', '.join(data.get('servers', []))}",
                )
            except Exception as e:
                return _get_tools_display(), f"❌ Reload failed: {e}"

        reload_btn.click(fn=reload_tools, outputs=[tools_display, reload_status])

    # ---- Monitoring Page ----
    with demo.route("📊 监控面板", "/monitor"):
        gr.Markdown("# 📊 监控面板")

        with gr.Row():
            stats_md = gr.Markdown("加载中...")
            sys_info_md = gr.Markdown("加载中...")
            token_md = gr.Markdown("加载中...")

        logs_md = gr.Markdown("加载中...")

        refresh_btn = gr.Button("🔄 刷新")
        timer = gr.Timer(value=5)

        refresh_btn.click(
            fn=refresh_monitoring,
            outputs=[stats_md, sys_info_md, token_md, logs_md],
        )
        timer.tick(
            fn=refresh_monitoring,
            outputs=[stats_md, sys_info_md, token_md, logs_md],
        )

        demo.load(
            fn=refresh_monitoring,
            outputs=[stats_md, sys_info_md, token_md, logs_md],
        )

    # ---- Settings Page ----
    with demo.route("⚙️ 系统配置", "/settings"):
        gr.Markdown("# ⚙️ 系统配置")

        defaults = load_config_values()

        with gr.Tab(id='model', label='模型配置'):

            gr.Markdown("### 🧠 模型配置\n修改后保存，重启服务生效。")

            cfg_default_model = gr.Textbox(label="默认模型", value=defaults[0])
            cfg_model_map = gr.Code(label="model_map (JSON)", value=defaults[1], language="json")

            save_btn = gr.Button("💾 保存配置", variant="primary")
            save_status = gr.Markdown("")

            save_btn.click(
                fn=save_config,
                inputs=[cfg_default_model, cfg_model_map],
                outputs=[save_status],
            )

        with gr.Tab(id='mcp', label='MCP Config'):
            # MCP Config Section
            gr.Markdown("### 🔧 MCP Servers 配置\n编辑 `~/.kiro/settings/mcp.json`")

            def load_mcp_json():
                cfg = load_mcp_config()
                return json.dumps(cfg, indent=2, ensure_ascii=False)

            mcp_json = gr.Code(label="mcp.json", value=load_mcp_json(), language="json")

            def save_mcp_json(mcp_text):
                try:
                    data = json.loads(mcp_text)
                    save_mcp_config(data)
                    return "✅ MCP 配置已保存！使用 Reload 按钮加载。"
                except json.JSONDecodeError as e:
                    return f"❌ JSON 解析错误: {e}"
                except Exception as e:
                    return f"❌ 保存失败: {e}"

            mcp_save_btn = gr.Button("💾 保存 MCP 配置", variant="secondary")
            mcp_status = gr.Markdown("")
            mcp_save_btn.click(fn=save_mcp_json, inputs=[mcp_json], outputs=[mcp_status])

    return demo


def main():
    demo = create_ui()
    demo.launch(server_name="0.0.0.0", server_port=7860)


if __name__ == "__main__":
    main()
