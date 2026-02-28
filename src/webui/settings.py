"""Settings page — model config and MCP config."""

import json

import gradio as gr

from ..config import config
from ..config_manager import load_config_file, save_config_file, load_mcp_config
from ..agent import get_enabled_server_names, set_enabled_mcp_servers


def _load_config_values():
    cfg = load_config_file()
    c = config
    return (
        cfg.get("assistant_identity", c.assistant_identity),
        cfg.get("context_limit", c.context_limit),
        cfg.get("default_model", c.default_model),
        json.dumps(cfg.get("model_map", dict(c.model_map)), indent=2, ensure_ascii=False),
    )


def _save_config(assistant_identity, context_limit, default_model, model_map_json):
    try:
        model_map = json.loads(model_map_json) if model_map_json.strip() else {}
    except json.JSONDecodeError as e:
        raise gr.Error(f"model_map JSON 格式错误（第 {e.lineno} 行第 {e.colno} 列）：{e.msg}")

    # Merge with existing config to preserve other sections (e.g. [mcp])
    data = load_config_file()
    data["assistant_identity"] = assistant_identity
    data["context_limit"] = int(context_limit)
    data["default_model"] = default_model
    data["model_map"] = model_map
    try:
        save_config_file(data)
        gr.Info("配置已保存！重启服务后生效。")
        return (
            assistant_identity,
            context_limit,
            default_model,
            json.dumps(model_map, indent=2, ensure_ascii=False),
            gr.Button(value="✅ 已保存", interactive=False),
        )
    except Exception as e:
        raise gr.Error(f"保存失败: {e}")


def build_settings_page():
    """Build the settings page UI within a route context."""
    gr.Markdown("# ⚙️ 系统配置")

    defaults = _load_config_values()

    with gr.Tab(id='mcp', label='MCP Config') as mcp_tab:
        gr.Markdown("### 🎛️ Agent MCP Servers\nKiro MCP Server 全局配置 (`~/.kiro/settings/mcp.json`)")

        def _get_all_server_names():
            # Kiro CLI + kiro2chat own mcp.json
            names = list(load_mcp_config().get("mcpServers", {}).keys())
            from ..agent import MCP_CONFIG_PATH
            if MCP_CONFIG_PATH.exists():
                try:
                    own = json.loads(MCP_CONFIG_PATH.read_text())
                    names.extend(own.get("mcpServers", {}).keys())
                except Exception:
                    pass
            return list(dict.fromkeys(names))  # dedupe, preserve order

        def _mcp_label():
            all_names = _get_all_server_names()
            enabled = get_enabled_server_names()
            return f"启用的 MCP Servers ({len(enabled)}/{len(all_names)})"

        mcp_toggle = gr.CheckboxGroup(
            choices=_get_all_server_names(),
            value=get_enabled_server_names(),
            label=_mcp_label(),
        )

        # Refresh choices/value when tab is selected
        def _refresh_toggle():
            return gr.CheckboxGroup(
                choices=_get_all_server_names(), value=get_enabled_server_names(), label=_mcp_label(),
            )
        mcp_tab.select(fn=_refresh_toggle, outputs=[mcp_toggle])

        toggle_btn = gr.Button("💾 保存并 Reload", variant="primary", interactive=False)

        mcp_toggle.change(
            fn=lambda: gr.Button(value="💾 保存并 Reload", interactive=True),
            outputs=[toggle_btn],
        )

        gr.Markdown("Kiro2chat MCP 配置 (`~/.config/kiro2chat/mcp.json`)")
        gr.Code(label="JSON", value='TBD', language="json")

        def save_and_reload(selected):
            import httpx
            set_enabled_mcp_servers(selected)
            all_names = _get_all_server_names()
            try:
                resp = httpx.post("http://localhost:8000/v1/agent/reload", timeout=30)
                data = resp.json()
                n = data.get("tool_count", 0)
                gr.Info(f"已启用 {len(selected)}/{len(all_names)} 个 MCP server，共 {n} tools")
            except Exception as e:
                gr.Warning(f"已保存，但 reload 失败: {e}")
            label = f"启用的 MCP Servers ({len(selected)}/{len(all_names)})"
            return (
                gr.CheckboxGroup(choices=all_names, value=selected, label=label),
                gr.Button(value="✅ 已保存", interactive=False),
            )

        toggle_btn.click(fn=save_and_reload, inputs=[mcp_toggle], outputs=[mcp_toggle, toggle_btn])

    with gr.Tab(id='model', label='模型配置'):
        gr.Markdown("### 🧠 模型配置\n修改后保存，重启服务生效。")

        cfg_identity = gr.Dropdown(
            choices=[("Kiro", "kiro"), ("Claude", "claude")],
            value=defaults[0],
            label="Assistant Identity",
            info="kiro: 保留 Kiro 身份；claude: 覆盖为 Claude 身份并启用身份替换",
        )
        cfg_context_limit = gr.Number(
            label="Context Limit (tokens)",
            value=defaults[1],
            precision=0,
            info="发送给 LLM 的最大 token 数，超出时主动报错（Claude 上限 200k）",
        )
        cfg_default_model = gr.Textbox(label="默认模型", value=defaults[2])
        gr.Markdown("Model MAP")
        cfg_model_map = gr.Code(label="JSON", value=defaults[3], language="json")

        save_btn = gr.Button("💾 保存配置", variant="primary")

        def _enable_save():
            return gr.Button(value="💾 保存配置", interactive=True)

        cfg_identity.input(fn=_enable_save, outputs=[save_btn])
        cfg_context_limit.input(fn=_enable_save, outputs=[save_btn])
        cfg_default_model.input(fn=_enable_save, outputs=[save_btn])
        cfg_model_map.input(fn=_enable_save, outputs=[save_btn])

        save_btn.click(
            fn=_save_config,
            inputs=[cfg_identity, cfg_context_limit, cfg_default_model, cfg_model_map],
            outputs=[cfg_identity, cfg_context_limit, cfg_default_model, cfg_model_map, save_btn],
        )
