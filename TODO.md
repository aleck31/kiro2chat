# TODO List — kiro2chat Roadmap

> Last updated: 2026-02-27 (v1.2.0)

## 🔴 P0 — Bug / Missing Features

| # | Item | Description |
|---|------|-------------|
| 1 | **OpenAI non-stream auto-continuation** | Streaming has auto-continuation on truncation, but `_non_stream_response` does not. Long non-stream outputs get silently truncated |
| 2 | **Anthropic non-stream auto-continuation** | Same issue — `/v1/messages` non-stream lacks auto-continuation |
| 3 | **Anthropic non-stream toolUseEvent** | Non-stream route only handles `toolUse`, not `toolUseEvent` (streaming incremental tool calls) |

## 🟡 P1 — Robustness & Operations

| # | Item | Description |
|---|------|-------------|
| 4 | **AWS Managed Prometheus** | Connect /metrics to AWS Managed Prometheus, configure scrape target |
| 5 | **Grafana dashboard template** | Visualize requests, latency, tokens, errors, continuation rounds |
| 6 | **Token refresh failure alerts** | Send TG/email notification when IdC token refresh fails |
| 7 | **Request log persistence** | Write request/response summaries to SQLite or JSON file for audit |
| 8 | **Config hot-reload** | Auto-reload config.toml changes without restart |

## 🟢 P2 — Feature Enhancements

| # | Item | Description |
|---|------|-------------|
| 9 | **Multi-account rotation** | Multiple kiro-cli SQLite sources for load balancing / rate limit failover |
| 10 | **OpenAI Responses API** | `/v1/responses` new format compatibility |
| 11 | **WebSocket support** | Some clients use WebSocket instead of SSE for streaming |
| 12 | **Anthropic Batch API** | Currently 501 stub — implement queue-based batch processing |
| 13 | **Response caching** | Cache identical requests to reduce CW backend calls |
| 14 | **Real-time streaming usage** | Token counts in every chunk (currently only in final chunk) |

## 🔵 P3 — Code Quality & Documentation

| # | Item | Description |
|---|------|-------------|
| 15 | **mypy type checking** | Add py.typed, configure mypy strict mode |
| 16 | **ruff format** | Auto code formatting (currently lint only) |
| 17 | **API versioning** | Reserve `/v2/` routes for future breaking changes |
| 18 | **Performance benchmarks** | Concurrent load test script, measure QPS and P99 latency |
| 19 | **Error code standardization** | Unified OpenAI/Anthropic error format, map CW error codes |
| 20 | **Architecture diagram** | Mermaid flowchart to replace ASCII art in README |
