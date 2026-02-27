"""Settings page — model config and MCP config."""

import json

import gradio as gr

from ..config import config
from ..config_manager import load_config_file, save_config_file, load_mcp_config, save_mcp_config


def _load_config_values():
    cfg = load_config_file()
    c = config
    return (
        cfg.get("default_model", c.default_model),
        json.dumps(cfg.get("model_map", dict(c.model_map)), indent=2, ensure_ascii=False),
    )


def _save_config(default_model, model_map_json):
    try:
        model_map = json.loads(model_map_json) if model_map_json.strip() else {}
    except json.JSONDecodeError as e:
        return f"❌ model_map JSON 格式错误（第 {e.lineno} 行第 {e.colno} 列）：{e.msg}"

    data = {
        "default_model": default_model,
        "model_map": model_map,
    }
    try:
        save_config_file(data)
        return "✅ 配置已保存！重启服务后生效。"
    except Exception as e:
        return f"❌ 保存失败: {e}"


def build_settings_page():
    """Build the settings page UI within a route context."""
    gr.Markdown("# ⚙️ 系统配置")

    defaults = _load_config_values()

    with gr.Tab(id='model', label='模型配置'):
        gr.Markdown("### 🧠 模型配置\n修改后保存，重启服务生效。")

        cfg_default_model = gr.Textbox(label="默认模型", value=defaults[0])
        cfg_model_map = gr.Code(label="model_map (JSON)", value=defaults[1], language="json")

        save_btn = gr.Button("💾 保存配置", variant="primary")
        save_status = gr.Markdown("")

        save_btn.click(
            fn=_save_config,
            inputs=[cfg_default_model, cfg_model_map],
            outputs=[save_status],
        )

    with gr.Tab(id='mcp', label='MCP Config'):
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
