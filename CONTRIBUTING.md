# Contributing to kiro2chat

Thank you for your interest in contributing! Here's how to get started.

## Development Setup

```bash
git clone https://github.com/neosun100/kiro2chat.git
cd kiro2chat
uv sync
```

## Running Tests

```bash
uv run pytest tests/ -v
```

## Code Style

We use [ruff](https://docs.astral.sh/ruff/) for linting:

```bash
uv run ruff check src/
```

## Pull Requests

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/my-feature`)
3. Make your changes
4. Run tests (`uv run pytest tests/ -v`)
5. Commit with a descriptive message
6. Push and open a Pull Request

## Reporting Issues

Please include:
- Python version
- kiro-cli version
- Error logs (redact any API keys or tokens)
- Steps to reproduce
