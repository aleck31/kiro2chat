#!/bin/bash
# kiro2chat supervisor — auto-restarts on crash
set -e
cd "$(dirname "$0")"

MAX_RESTARTS=100
RESTART_DELAY=3
count=0

while [ $count -lt $MAX_RESTARTS ]; do
    echo "[$(date)] Starting kiro2chat (restart #$count)..."
    
    uv run python -c "
from src.app import app
import uvicorn, os
uvicorn.run(app,
    host=os.environ.get('HOST', '0.0.0.0'),
    port=int(os.environ.get('PORT', '8800')),
    log_level=os.environ.get('LOG_LEVEL', 'info'))
" 2>&1 || true
    
    count=$((count + 1))
    echo "[$(date)] Process exited. Restarting in ${RESTART_DELAY}s..."
    sleep $RESTART_DELAY
done

echo "[$(date)] Max restarts ($MAX_RESTARTS) reached. Giving up."
