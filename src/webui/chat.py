"""Chat page — agent chat with multimodal support and tool display."""

import json
import os
from pathlib import Path

import httpx
import gradio as gr

from ..config import config
from .._tool_names import BUILTIN_TOOL_NAMES

API_BASE = "http://localhost:8000"


def get_models() -> list[str]:
    try:
        resp = httpx.get(f"{API_BASE}/v1/models", timeout=5)
        resp.raise_for_status()
        return [m["id"] for m in resp.json()["data"]]
    except Exception:
        return list(config.model_map.keys())


def _get_tools_display() -> str:
    """Build markdown display of actually loaded tools from the running API."""
    lines = ["**内置工具:**"]
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


def _brief_tool_input(name: str, inp) -> str:
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


def build_chat_page(demo: gr.Blocks):
    """Build the chat page UI within the given Blocks context."""
    models = get_models()
    default_model = config.default_model if config.default_model in models else (models[0] if models else "")

    gr.Markdown("# 🤖 kiro2chat")

    # Hidden state to bridge model dropdown into ChatInterface
    model_state = gr.State(value=default_model)

    def agent_chat_fn(message: dict, history: list[dict], model: str, request: gr.Request):
        try:
            full_text = ""
            tool_status = ""
            image_paths = []
            session_id = request.session_hash or "unknown" if request else "unknown"

            # Extract text and images from multimodal input
            text = message.get("text", "") if isinstance(message, dict) else message
            files = message.get("files", []) if isinstance(message, dict) else []
            body: dict = {"message": text, "model": model, "stream": True}
            if files:
                import base64
                images = []
                for f in files:
                    path = f if isinstance(f, str) else f.get("path", "")
                    if not path:
                        continue
                    with open(path, "rb") as fh:
                        img_b64 = base64.b64encode(fh.read()).decode()
                    ext = path.rsplit(".", 1)[-1].lower().replace("jpg", "jpeg")
                    images.append({"data": img_b64, "format": ext if ext in ("jpeg", "png", "gif", "webp") else "jpeg"})
                if images:
                    body["images"] = images

            with httpx.stream(
                "POST",
                f"{API_BASE}/v1/agent/chat",
                json=body,
                headers={"x-user-tag": f"web:{session_id[:8]}"},
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
                        brief = _brief_tool_input(name, inp)
                        tool_status = f"🔧 *{name}*" + (f": {brief}" if brief else "") + "..."
                        prefix = full_text + "\n\n" if full_text else ""
                        yield prefix + tool_status

                    elif evt_type == "tool_end":
                        tool_status = ""
                        # Check for image paths in tool result
                        content = event.get("content", {})
                        paths = content.get("paths", []) if isinstance(content, dict) else []
                        for p in paths:
                            p = p.replace("file://", "")
                            if not os.path.isabs(p):
                                p = str(Path(__file__).resolve().parent.parent.parent / p)
                            if os.path.isfile(p):
                                image_paths.append(p)
                        if full_text:
                            yield full_text

                    elif evt_type == "error":
                        prefix = full_text + "\n\n" if full_text else ""
                        yield prefix + f"❌ {event.get('message', 'Unknown error')}"
                        return

            # Append generated images to final message
            if image_paths:
                for p in image_paths:
                    full_text += f"\n\n![image](/gradio_api/file={p})"
                yield full_text

        except Exception as e:
            yield f"❌ Error: {e}"

    chatbot = gr.Chatbot(height="60vh", buttons=["copy", "copy_all"])

    gr.ChatInterface(
        fn=agent_chat_fn,
        chatbot=chatbot,
        additional_inputs=[model_state],
        multimodal=True,
    )

    # --- model selector ---
    model_dd = gr.Dropdown(
        choices=models,
        value=default_model or None,
        label="模型选择",
        interactive=True,
    )
    model_dd.change(fn=lambda x: x, inputs=[model_dd], outputs=[model_state])

    # --- tools list (collapsible, refreshes on open) ---
    with gr.Accordion("🛠 工具列表", open=False) as tools_accordion:
        tools_display = gr.Markdown("点击展开查看已加载工具")

    tools_accordion.expand(fn=lambda: _get_tools_display(), outputs=[tools_display])
