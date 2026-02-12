"""Gradio Web UI for kiro2chat."""

import json
import httpx
import gradio as gr

API_BASE = "http://localhost:8000"


def get_models() -> list[str]:
    """Fetch available models from the API."""
    try:
        resp = httpx.get(f"{API_BASE}/v1/models", timeout=5)
        resp.raise_for_status()
        return [m["id"] for m in resp.json()["data"]]
    except Exception:
        return ["claude-sonnet-4-20250514"]


def chat_stream(message: str, history: list[dict], model: str):
    """Stream chat response from the API."""
    messages = []
    for msg in history:
        messages.append({"role": msg["role"], "content": msg["content"]})
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


def create_ui() -> gr.Blocks:
    """Create and return the Gradio Blocks app."""
    models = get_models()

    with gr.Blocks(title="kiro2chat", theme=gr.themes.Soft()) as demo:
        gr.Markdown("# 🤖 kiro2chat\nChat with Claude via Kiro/CodeWhisperer")

        model_dropdown = gr.Dropdown(
            choices=models,
            value=models[0] if models else None,
            label="Model",
            interactive=True,
        )

        gr.ChatInterface(
            fn=chat_stream,
            type="messages",
            additional_inputs=[model_dropdown],
        )

    return demo


def main():
    """Launch the Web UI standalone."""
    demo = create_ui()
    demo.launch(server_name="0.0.0.0", server_port=7860)


if __name__ == "__main__":
    main()
