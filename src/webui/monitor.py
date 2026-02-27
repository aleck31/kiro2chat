"""Monitoring page — request stats, system info, recent logs."""

import platform
from datetime import datetime, timezone, timedelta

import httpx
import gradio as gr

from ..config import config
from ..stats import stats

API_BASE = "http://localhost:8000"
TZ_CST = timezone(timedelta(hours=8))


def _get_stats_display():
    s = stats.get_summary()
    uptime_s = s["uptime_seconds"]
    h, rem = divmod(int(uptime_s), 3600)
    m, sec = divmod(rem, 60)
    uptime_str = f"{h}h {m}m {sec}s"

    sys_md = f"""### 🖥️ 系统信息
| 项目 | 值 |
|------|-----|
| 运行时间 | {uptime_str} |
| Python | {platform.python_version()} |
| 平台 | {platform.platform()} |
"""

    try:
        resp = httpx.get(f"{API_BASE}/health", timeout=3)
        data = resp.json() if resp.status_code == 200 else {}
        api_status = "🟢 运行中" if resp.status_code == 200 else f"🔴 状态码 {resp.status_code}"
        token_status = "🟢 有效" if data.get("checks", {}).get("token", {}).get("status") == "ok" else "🔴 异常"
    except Exception:
        api_status = "🔴 无法连接"
        token_status = "❓ 未知"

    try:
        mcp_resp = httpx.get(f"{API_BASE}/v1/agent/tools", timeout=3)
        mcp_data = mcp_resp.json() if mcp_resp.status_code == 200 else {}
        mcp_servers = mcp_data.get("mcp", [])
        mcp_total = mcp_data.get("total_mcp_tools", 0)
        if mcp_servers:
            mcp_lines = "\n".join(
                f"| {s['server']} | {'🟢' if s.get('status') == 'ok' else '🔴'} {s.get('tool_count', 0)} tools |"
                for s in mcp_servers
            )
            mcp_md = f"""### 🔌 MCP Servers
| Server | 状态 |
|------|-----|
{mcp_lines}
| 合计 | {mcp_total} tools |
"""
        else:
            mcp_md = "### 🔌 MCP Servers\n(未启用)"
    except Exception:
        mcp_md = "### 🔌 MCP Servers\n❓ 未知"

    token_md = f"""### 🔑 服务状态
| 项目 | 值 |
|------|-----|
| API 服务 | {api_status} |
| IdC Token | {token_status} |
| 可用模型 | {', '.join(config.model_map.keys())} |
"""

    avg_latency = s['avg_latency_ms']
    latency_color = "🟢" if avg_latency < 3000 else ("🟡" if avg_latency < 8000 else "🔴")
    summary_md = f"""### 📊 请求统计
| 指标 | 值 |
|------|-----|
| 总请求数 | {s['total_requests']} |
| 成功 | {s['total_success']} |
| 错误 | {s['total_errors']} |
| 平均延迟 | {latency_color} {avg_latency:.1f} ms |
"""

    return summary_md, sys_md, token_md, mcp_md


def _get_recent_logs():
    records = stats.get_recent(20)
    if not records:
        return "暂无请求记录"

    rows = []
    for r in reversed(records[-10:]):
        ts = datetime.fromtimestamp(r.timestamp, tz=TZ_CST).strftime("%H:%M:%S")
        status_icon = "✅" if r.status == "ok" else "❌"
        err = f" ({r.error[:40]})" if r.error else ""
        rows.append(f"| {ts} | {r.model} | {r.latency_ms:.0f}ms | {status_icon}{err} |")

    header = "| 时间 | 模型 | 延迟 | 状态 |\n|------|------|------|------|\n"
    return "### 📋 最近请求\n" + header + "\n".join(rows)


def _refresh():
    summary_md, sys_md, token_md, mcp_md = _get_stats_display()
    logs_md = _get_recent_logs()
    return summary_md, sys_md, token_md, mcp_md, logs_md


def build_monitor_page(demo: gr.Blocks):
    """Build the monitoring page UI within a route context."""
    with gr.Row():
        gr.Markdown("# 📊 监控面板")
        refresh_btn = gr.Button("🔄", scale=0, size="sm", min_width=40)

    # Row 1: system info | service status | MCP servers
    with gr.Row():
        with gr.Column(scale=1):
            sys_info_md = gr.Markdown("加载中...")
        with gr.Column(scale=1):
            token_md = gr.Markdown("加载中...")
        with gr.Column(scale=1):
            mcp_md = gr.Markdown("加载中...")

    # Row 2: request stats | recent requests
    with gr.Row():
        with gr.Column(scale=1):
            stats_md = gr.Markdown("加载中...")
        with gr.Column(scale=2):
            logs_md = gr.Markdown("加载中...")

    timer = gr.Timer(value=30)

    outputs = [stats_md, sys_info_md, token_md, mcp_md, logs_md]
    refresh_btn.click(fn=_refresh, outputs=outputs)
    timer.tick(fn=_refresh, outputs=outputs)
    demo.load(fn=_refresh, outputs=outputs)
