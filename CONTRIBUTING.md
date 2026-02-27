# Contributing to kiro2chat

## Development Setup

```bash
git clone https://github.com/aleck31/kiro2chat.git
cd kiro2chat
uv sync
cp .env.example .env  # edit with your config
```

## Running

```bash
uv run kiro2chat api       # API server
uv run kiro2chat webui     # Web UI
uv run kiro2chat bot       # Telegram Bot
uv run kiro2chat all       # All together
```

## Testing & Linting

```bash
uv run pytest tests/ -v    # 28 tests
uv run ruff check src/     # linter
```

Both are enforced by CI on push/PR.

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
- kiro-cli version
- Error logs (redact any API keys or tokens)
- Steps to reproduce
