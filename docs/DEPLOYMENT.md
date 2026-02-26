# Deployment Guide

## Prerequisites

- Python ≥ 3.13
- [uv](https://docs.astral.sh/uv/) package manager
- kiro-cli installed and logged in (`kiro-cli login`)

## Quick Deploy

```bash
git clone https://github.com/neosun100/kiro2chat.git
cd kiro2chat
uv sync
```

## systemd Service (Recommended)

### 1. Create environment file

```bash
sudo tee /etc/kiro2chat.env > /dev/null << 'EOF'
API_KEY=your-api-key-here
EOF
sudo chmod 600 /etc/kiro2chat.env
```

### 2. Create service file

```bash
sudo tee /etc/systemd/system/kiro2chat.service > /dev/null << EOF
[Unit]
Description=kiro2chat API Gateway
After=network.target

[Service]
Type=simple
User=$(whoami)
WorkingDirectory=$(pwd)
Environment=HOME=$HOME
Environment=PATH=$(dirname $(which uv)):$PATH
Environment=PORT=8800
Environment=HOST=0.0.0.0
Environment=LOG_LEVEL=info
EnvironmentFile=/etc/kiro2chat.env
ExecStart=$(which uv) run python -c "from src.app import app; import uvicorn; uvicorn.run(app, host='0.0.0.0', port=8800, log_level='info')"
Restart=always
RestartSec=3
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF
```

### 3. Enable and start

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now kiro2chat
```

### 4. Verify

```bash
sudo systemctl status kiro2chat
curl http://localhost:8800/
```

## Management Commands

```bash
# Status
sudo systemctl status kiro2chat

# Restart
sudo systemctl restart kiro2chat

# Logs (live)
sudo journalctl -u kiro2chat -f

# Logs (last 100 lines)
sudo journalctl -u kiro2chat -n 100

# Stop
sudo systemctl stop kiro2chat
```

## Nginx Reverse Proxy

Recommended Nginx configuration for production:

```nginx
server {
    listen 443 ssl;
    server_name your-domain.com;

    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;

    location / {
        proxy_pass http://127.0.0.1:8800;
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

The `/metrics` endpoint exposes Prometheus-compatible metrics:

```bash
curl http://localhost:8800/metrics
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
curl http://localhost:8800/health
```

## Security

- API key is stored in `/etc/kiro2chat.env` with 600 permissions
- Never commit API keys to git
- The `.gitignore` excludes `.env`, `*.sqlite3`, `config.toml`
- All responses are sanitized to remove Kiro/CodeWhisperer references
