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


def _get_recent_logs():
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


def _refresh():
    summary_md, sys_md, token_md = _get_stats_display()
    logs_md = _get_recent_logs()
    return summary_md, sys_md, token_md, logs_md


def build_monitor_page(demo: gr.Blocks):
    """Build the monitoring page UI within a route context."""
    gr.Markdown("# 📊 监控面板")

    with gr.Row():
        stats_md = gr.Markdown("加载中...")
        sys_info_md = gr.Markdown("加载中...")
        token_md = gr.Markdown("加载中...")

    logs_md = gr.Markdown("加载中...")

    refresh_btn = gr.Button("🔄 刷新")
    timer = gr.Timer(value=5)

    outputs = [stats_md, sys_info_md, token_md, logs_md]
    refresh_btn.click(fn=_refresh, outputs=outputs)
    timer.tick(fn=_refresh, outputs=outputs)
    demo.load(fn=_refresh, outputs=outputs)
