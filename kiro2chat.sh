#!/bin/bash
SESSION="kiro2chat"
DIR="$(cd "$(dirname "$0")" && pwd)"

case "$1" in
  start)
    if tmux has-session -t "$SESSION" 2>/dev/null; then
      echo "Already running (tmux session: $SESSION)"
      exit 1
    fi
    tmux new-session -d -s "$SESSION" -c "$DIR" "uv run kiro2chat all"
    sleep 2
    if tmux has-session -t "$SESSION" 2>/dev/null; then
      echo "Started (tmux session: $SESSION)"
      echo "Logs: tail -f $HOME/.local/share/kiro2chat/logs/kiro2chat.log"
      echo "Attach: $0 attach  |  Detach: Ctrl+B then D"
    else
      echo "Failed to start, check: $0 attach"
      exit 1
    fi
    ;;
  stop)
    if ! tmux has-session -t "$SESSION" 2>/dev/null; then
      echo "Not running"
      exit 1
    fi
    tmux kill-session -t "$SESSION"
    echo "Stopped"
    ;;
  restart)
    "$0" stop 2>/dev/null; sleep 1; "$0" start
    ;;
  status)
    if tmux has-session -t "$SESSION" 2>/dev/null; then
      PID=$(tmux list-panes -t "$SESSION" -F "#{pane_pid}" 2>/dev/null | head -1)
      echo "Running (pid: $PID)"
      echo "tmux session: $SESSION"
      [ -f "$DIR/.env" ] && source "$DIR/.env"
      API_PORT="${PORT:-8000}"
      ss -tlnp 2>/dev/null | grep ":$API_PORT\|:7860" | awk '{print "Listening: "$4}'
    else
      echo "Not running"
    fi
    ;;
  attach)
    tmux attach -t "$SESSION"
    ;;
  *)
    echo "Usage: $0 {start|stop|restart|status|attach}"
    exit 1
    ;;
esac
