"""Prometheus metrics for kiro2chat."""

from prometheus_client import Counter, Histogram, Gauge, Info, generate_latest, CONTENT_TYPE_LATEST

# Service info
SERVICE_INFO = Info("kiro2chat", "kiro2chat API Gateway")

# Request counters
REQUEST_COUNT = Counter(
    "kiro2chat_requests_total",
    "Total API requests",
    ["endpoint", "method", "status"],
)

# Latency histogram (seconds)
REQUEST_LATENCY = Histogram(
    "kiro2chat_request_duration_seconds",
    "Request latency in seconds",
    ["endpoint"],
    buckets=[0.5, 1, 2, 5, 10, 30, 60, 120, 300],
)

# Active requests gauge
ACTIVE_REQUESTS = Gauge(
    "kiro2chat_active_requests",
    "Currently active requests",
)

# Token counters
TOKENS_INPUT = Counter(
    "kiro2chat_tokens_input_total",
    "Total input tokens processed",
)
TOKENS_OUTPUT = Counter(
    "kiro2chat_tokens_output_total",
    "Total output tokens generated",
)

# Tool call counter
TOOL_CALLS = Counter(
    "kiro2chat_tool_calls_total",
    "Total tool calls made",
    ["tool_name"],
)

# Error counter
ERRORS = Counter(
    "kiro2chat_errors_total",
    "Total errors",
    ["type"],
)

# CW backend metrics
CW_RETRIES = Counter(
    "kiro2chat_cw_retries_total",
    "CodeWhisperer backend retry count",
)


def get_metrics() -> bytes:
    """Generate Prometheus metrics output."""
    return generate_latest()


def get_content_type() -> str:
    return CONTENT_TYPE_LATEST
