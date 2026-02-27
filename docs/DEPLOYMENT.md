# Deployment Guide

## Prerequisites

- Python ≥ 3.13
- [uv](https://docs.astral.sh/uv/) package manager
- kiro-cli installed and logged in (`kiro-cli login`)

## Quick Deploy

```bash
git clone https://github.com/aleck31/kiro2chat.git
cd kiro2chat
uv sync
cp .env.example .env   # edit with your config
```

## systemd Service (Recommended)

The project includes a template service file `kiro2chat@.service` that uses the system username as the instance parameter.

### 1. Configure environment

```bash
cd ~/repos/kiro2chat
cp .env.example .env
# Edit .env: set API_KEY, TG_BOT_TOKEN, etc.
chmod 600 .env
```

### 2. Install and start

```bash
sudo cp kiro2chat@.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now kiro2chat@$(whoami)
```

### 3. Verify

```bash
sudo systemctl status kiro2chat@$(whoami)
curl http://localhost:8000/health
```

## Management Commands

```bash
# Status
sudo systemctl status kiro2chat@$(whoami)

# Restart
sudo systemctl restart kiro2chat@$(whoami)

# Logs (live)
journalctl --user -u kiro2chat@$(whoami) -f

# Stop
sudo systemctl stop kiro2chat@$(whoami)
```

Application logs are also written to `~/.local/share/kiro2chat/logs/kiro2chat.log` (rotating, 20MB × 10 files).

## Nginx Reverse Proxy

Recommended Nginx configuration for production:

```nginx
server {
    listen 443 ssl;
    server_name your-domain.com;

    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Critical for long outputs and SSE streaming
        proxy_read_timeout 7200;
        proxy_send_timeout 7200;
        proxy_connect_timeout 60;
        proxy_buffering off;
        proxy_cache off;
        chunked_transfer_encoding on;

        client_max_body_size 100M;
    }
}
```

## Monitoring

### Prometheus Metrics

```bash
curl http://localhost:8000/metrics
```

Available metrics:
- `kiro2chat_requests_total` — Total requests by endpoint, method, status
- `kiro2chat_request_duration_seconds` — Request latency histogram
- `kiro2chat_active_requests` — Currently active requests
- `kiro2chat_tokens_input_total` — Total input tokens
- `kiro2chat_tokens_output_total` — Total output tokens
- `kiro2chat_tool_calls_total` — Tool calls by name
- `kiro2chat_errors_total` — Errors by type
- `kiro2chat_cw_retries_total` — Backend retry count

### Health Check

```bash
curl http://localhost:8000/health
```

## Data Directories

| Path | Purpose |
|------|---------|
| `~/.config/kiro2chat/config.toml` | Model config (Web UI editable) |
| `~/.local/share/kiro2chat/logs/` | Application logs |
| `~/.local/share/kiro2chat/output/` | Agent-generated files |
| `~/.local/share/kiro-cli/data.sqlite3` | kiro-cli auth tokens |

Override data directory with `KIRO2CHAT_DATA_DIR` environment variable.

## Security

- Secrets (API_KEY, TG_BOT_TOKEN) stored in `.env` with 600 permissions
- Never commit `.env` to git (already in `.gitignore`)
- All responses are sanitized to remove Kiro/CodeWhisperer identity leaks
