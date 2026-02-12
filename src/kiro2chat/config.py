"""Configuration management."""

import os
from pathlib import Path
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    port: int = int(os.getenv("PORT", "8000"))
    host: str = os.getenv("HOST", "0.0.0.0")
    api_key: str | None = os.getenv("API_KEY")
    log_level: str = os.getenv("LOG_LEVEL", "info")

    # kiro-cli SQLite database path
    kiro_db_path: str = os.getenv(
        "KIRO_DB_PATH",
        str(Path.home() / ".local/share/kiro-cli/data.sqlite3"),
    )

    # AWS endpoints
    idc_refresh_url: str = "https://oidc.us-east-1.amazonaws.com/token"
    codewhisperer_url: str = "https://codewhisperer.us-east-1.amazonaws.com/generateAssistantResponse"

    # CodeWhisperer profile ARN (read from kiro-cli state)
    profile_arn: str = os.getenv("PROFILE_ARN", "")

    # Model mapping: OpenAI model name -> CodeWhisperer model ID
    model_map: dict[str, str] = field(default_factory=lambda: {
        "claude-sonnet-4-5": "CLAUDE_SONNET_4_5_20250929_V1_0",
        "claude-sonnet-4-5-20250929": "CLAUDE_SONNET_4_5_20250929_V1_0",
        "claude-sonnet-4": "CLAUDE_SONNET_4_20250514_V1_0",
        "claude-sonnet-4-20250514": "CLAUDE_SONNET_4_20250514_V1_0",
        "claude-3.7-sonnet": "CLAUDE_3_7_SONNET_20250219_V1_0",
        "claude-3-7-sonnet-20250219": "CLAUDE_3_7_SONNET_20250219_V1_0",
        "claude-3-5-haiku-20241022": "auto",
        "claude-haiku-4-5": "auto",
    })

    # Default model when client doesn't specify
    default_model: str = "claude-sonnet-4-20250514"


config = Config()
