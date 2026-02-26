"""Configuration management."""

import os
from pathlib import Path
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()


def _load_toml_defaults() -> dict:
    """Load defaults from config.toml (if exists)."""
    try:
        from .config_manager import load_config_file
        return load_config_file()
    except Exception:
        return {}


_file_cfg = _load_toml_defaults()


def _get(key: str, env_key: str | None = None, default: str | None = None) -> str | None:
    """Get config value: env var > toml file > default."""
    env = env_key or key.upper()
    val = os.getenv(env)
    if val is not None:
        return val
    val = _file_cfg.get(key)
    if val is not None:
        return str(val)
    return default


@dataclass
class Config:
    port: int = int(_get("port", "PORT", "8000"))
    host: str = _get("host", "HOST", "0.0.0.0")
    api_key: str | None = _get("api_key", "API_KEY")
    log_level: str = _get("log_level", "LOG_LEVEL", "info")

    # kiro-cli SQLite database path
    kiro_db_path: str = _get(
        "kiro_db_path",
        "KIRO_DB_PATH",
        str(Path.home() / ".local/share/kiro-cli/data.sqlite3"),
    )

    # Telegram bot
    tg_bot_token: str | None = _get("tg_bot_token", "TG_BOT_TOKEN")

    # AWS endpoints
    idc_refresh_url: str = _get(
        "idc_refresh_url", "IDC_REFRESH_URL",
        "https://oidc.us-east-1.amazonaws.com/token",
    )
    codewhisperer_url: str = _get(
        "codewhisperer_url", "CODEWHISPERER_URL",
        "https://codewhisperer.us-east-1.amazonaws.com/generateAssistantResponse",
    )

    # CodeWhisperer profile ARN (read from kiro-cli state)
    profile_arn: str = os.getenv("PROFILE_ARN", "")

    # Model mapping: all names accepted, backend always uses Opus 4.6 1M
    # This map is only used for /v1/models listing
    model_map: dict[str, str] = field(default_factory=lambda: {
        # Opus 4.6 (actual backend model)
        "claude-opus-4.6-1m": "claude-opus-4.6-1m",
        "claude-opus-4.6": "claude-opus-4.6-1m",
        # Sonnet 4.6
        "claude-sonnet-4.6": "claude-opus-4.6-1m",
        "claude-sonnet-4.6-1m": "claude-opus-4.6-1m",
        # Opus 4.5
        "claude-opus-4.5": "claude-opus-4.6-1m",
        "claude-opus-4-5": "claude-opus-4.6-1m",
        "claude-opus-4-5-20251101": "claude-opus-4.6-1m",
        # Sonnet 4.5
        "claude-sonnet-4.5": "claude-opus-4.6-1m",
        "claude-sonnet-4.5-1m": "claude-opus-4.6-1m",
        "claude-sonnet-4-5": "claude-opus-4.6-1m",
        "claude-sonnet-4-5-20250929": "claude-opus-4.6-1m",
        # Sonnet 4
        "claude-sonnet-4": "claude-opus-4.6-1m",
        "claude-sonnet-4-20250514": "claude-opus-4.6-1m",
        # Haiku 4.5
        "claude-haiku-4.5": "claude-opus-4.6-1m",
        "claude-haiku-4-5": "claude-opus-4.6-1m",
        "claude-3-5-haiku-20241022": "claude-opus-4.6-1m",
        # Sonnet 3.7
        "claude-3.7-sonnet": "claude-opus-4.6-1m",
        "claude-3-7-sonnet-20250219": "claude-opus-4.6-1m",
        # Auto
        "auto": "claude-opus-4.6-1m",
        # Third-party models in Kiro
        "deepseek-3.2": "claude-opus-4.6-1m",
        "kimi-k2.5": "claude-opus-4.6-1m",
        "minimax-m2.1": "claude-opus-4.6-1m",
        "glm-4.7": "claude-opus-4.6-1m",
        "glm-4.7-flash": "claude-opus-4.6-1m",
        "qwen3-coder-next": "claude-opus-4.6-1m",
        "agi-nova-beta-1m": "claude-opus-4.6-1m",
        # OpenAI-style aliases
        "gpt-4o": "claude-opus-4.6-1m",
        "gpt-4o-mini": "claude-opus-4.6-1m",
        "gpt-4-turbo": "claude-opus-4.6-1m",
        "gpt-4": "claude-opus-4.6-1m",
        "gpt-3.5-turbo": "claude-opus-4.6-1m",
    })

    # Default model when client doesn't specify
    default_model: str = _get("default_model", "DEFAULT_MODEL", "claude-opus-4-6")


config = Config()
