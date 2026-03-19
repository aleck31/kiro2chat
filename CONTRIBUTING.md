# Contributing to kiro2chat

## Development Setup

```bash
git clone https://github.com/aleck31/kiro2chat.git
cd kiro2chat
uv sync
cp .env.example .env  # set TG_BOT_TOKEN
```

Prerequisites: [kiro-cli](https://kiro.dev/docs/cli/) installed and logged in.

## Running

```bash
uv run kiro2chat bot       # Telegram Bot (foreground)
kiro2chat start            # background via tmux
```

## Testing & Linting

```bash
uv run pytest tests/ -v    # tests
uv run ruff check src/     # linter
```

Both are enforced by CI on push/PR.

## Project Structure

```
src/
├── app.py              # Entry point, CLI, tmux management
├── config.py           # Configuration
├── acp/
│   ├── client.py       # ACP JSON-RPC client (kiro-cli subprocess)
│   └── bridge.py       # Session management, event routing
└── adapters/
    ├── base.py         # Adapter interface
    └── telegram.py     # Telegram adapter (aiogram)
```

## Adding a New Platform Adapter

1. Create `src/adapters/your_platform.py`
2. Implement `BaseAdapter` interface (see `base.py`)
3. Wire it up in `app.py` with a new `run_xxx()` function
4. Add config entries in `config.py`

## Code Conventions

- Standard `logging` (not loguru)
- Type hints everywhere
- Secrets in `.env`, app config in `config.toml`
- Chinese UI text are fine

## Pull Requests

1. Create a feature branch (`git checkout -b feature/my-feature`)
2. Run tests and ruff before committing
3. Write a concise commit message
4. Open a PR against `master`

## Reporting Issues

Please include:
- Python version
- kiro-cli version (`kiro-cli --version`)
- Error logs (redact any tokens)
- Steps to reproduce
