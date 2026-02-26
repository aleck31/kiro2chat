#!/bin/bash
# kiro2chat launcher — loads env and starts the API server
set -e
cd "$(dirname "$0")"

# Load env
if [ -f ~/.config/kiro2chat/env ]; then
    set -a; source ~/.config/kiro2chat/env; set +a
fi

exec uv run python -c "
from src.app import app
import uvicorn
uvicorn.run(app, host='${HOST:-0.0.0.0}', port=int('${PORT:-8800}'), log_level='${LOG_LEVEL:-info}')
"
