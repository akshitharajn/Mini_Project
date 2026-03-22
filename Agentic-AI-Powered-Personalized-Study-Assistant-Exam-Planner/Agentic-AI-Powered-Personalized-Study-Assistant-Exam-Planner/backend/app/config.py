"""Application configuration loaded from environment / .env file."""

from __future__ import annotations

from pathlib import Path
from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
_PROJECT_ROOT = _ENV_FILE.parent


class Settings(BaseSettings):
    """Central application settings."""

    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database
    database_url: str = "sqlite+aiosqlite:///./study_assistant.db"

    # Application
    app_name: str = "Study Assistant"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    debug: bool = True

    # AI
    ai_provider: str = "rule_based"  # "rule_based" | "openai" | "groq"
    openai_api_key: str = ""
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"

    # Voice
    voice_enabled: bool = True
    tts_engine: str = "pyttsx3"

    # Notifications
    notification_enabled: bool = True

    # Email (SMTP / Gmail)
    auth_email_enabled: bool = True
    auth_email_provider: str = "resend"  # "resend" | "smtp"
    resend_api_key: str = ""
    resend_from_email: str = "onboarding@resend.dev"
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 465
    smtp_use_ssl: bool = True
    smtp_starttls: bool = False
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from_email: str = ""
    smtp_from_name: str = "Study Assistant"

    @field_validator(
        "auth_email_provider",
        "resend_api_key",
        "resend_from_email",
        "smtp_username",
        "smtp_password",
        "smtp_from_email",
        "smtp_from_name",
        mode="before",
    )
    @classmethod
    def normalize_email_settings(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("auth_email_provider", mode="after")
    @classmethod
    def validate_auth_email_provider(cls, value: str) -> str:
        lowered = value.lower()
        if lowered not in {"resend", "smtp"}:
            return "resend"
        return lowered

    @field_validator("debug", mode="before")
    @classmethod
    def parse_debug_flag(cls, value: object) -> object:
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"release", "prod", "production"}:
                return False
            if lowered in {"dev", "debug", "development"}:
                return True
        return value

    @field_validator("database_url", mode="before")
    @classmethod
    def normalize_sqlite_path(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        prefix = "sqlite+aiosqlite:///"
        if not value.startswith(prefix):
            return value
        db_path = value[len(prefix):]
        if not db_path.startswith("./"):
            return value
        absolute = (_PROJECT_ROOT / db_path[2:]).resolve()
        return f"{prefix}{absolute.as_posix()}"


@lru_cache
def get_settings() -> Settings:
    """Return cached settings singleton."""
    return Settings()
