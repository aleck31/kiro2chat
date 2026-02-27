"""Gradio Web UI for kiro2chat — assembles pages into multi-page app."""

from pathlib import Path

import gradio as gr

from .chat import build_chat_page
from .monitor import build_monitor_page
from .settings import build_settings_page


def create_ui() -> gr.Blocks:
    with gr.Blocks(title="kiro2chat", fill_height=True) as demo:
        build_chat_page(demo)

    with demo.route("📊 监控面板", "/monitor"):
        build_monitor_page(demo)

    with demo.route("⚙️ 系统配置", "/settings"):
        build_settings_page()

    return demo


# Shared launch kwargs for all entry points
LAUNCH_KWARGS = {
    "server_name": "0.0.0.0",
    "server_port": 7860,
    "footer_links": [],
    "allowed_paths": ["/tmp", str(Path(__file__).resolve().parent.parent.parent / "output")],
}


def main():
    demo = create_ui()
    demo.launch(**LAUNCH_KWARGS)


if __name__ == "__main__":
    main()
