"""Settings: config.yaml + profile.yaml (owner-editable) and secrets from .env / environment.

config.yaml is shared with v1: the `settings:` and `sources:` sections mean the same thing
in both versions. The `service:` section is v2 only.
"""
from __future__ import annotations

import os
import re
from datetime import time
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def project_root() -> Path:
    """Where config.yaml, profile.yaml and data/ live. RADAR_HOME overrides (Docker sets /app)."""
    env = os.getenv("RADAR_HOME")
    return Path(env).resolve() if env else Path(__file__).resolve().parents[2]


_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class Settings(BaseModel):
    """v1 `settings:` block. Same names and meaning as v1."""

    model_config = ConfigDict(extra="ignore")

    scorer_model: str = "claude-haiku-5-5"
    research_model: str = "claude-sonnet-5-5"
    web_search_tool: str = "web_search_20260209"
    alert_score: int = Field(75, ge=0, le=100)
    digest_score: int = Field(50, ge=0, le=100)
    max_alerts_per_run: int = Field(5, ge=0)
    max_items_per_run: int = Field(60, ge=1)
    max_age_days: int = Field(7, ge=0)
    research_max_searches: int = Field(8, ge=1, le=20)
    batch_size: int = Field(12, ge=1, le=50)
    exclude: list[str] = Field(default_factory=list)


class SourceConfig(BaseModel):
    """One entry of `sources:`. Unknown keys are kept for later phases (e.g. per-source cadence)."""

    model_config = ConfigDict(extra="allow")

    name: str
    type: str = "rss"
    url: str
    keywords: list[str] | None = None
    title_must_match: str | None = None
    exclude: list[str] = Field(default_factory=list)
    enabled: bool = True

    @field_validator("keywords", mode="before")
    @classmethod
    def _keywords_as_strings(cls, v):
        return [str(w) for w in v] if v else None


class ServiceConfig(BaseModel):
    """v2 `service:` block: how the always-on service schedules its work."""

    model_config = ConfigDict(extra="ignore")

    watch_every_minutes: int = Field(30, ge=5, le=24 * 60)
    digest_time: str = "07:00"
    timezone: str = "Africa/Lagos"
    db_path: str = "data/radar.db"
    backup_dir: str = "data/backups"
    backup_time: str = "03:30"
    backup_keep_days: int = Field(14, ge=1)
    startup_message: bool = True

    @field_validator("digest_time", "backup_time")
    @classmethod
    def _hhmm(cls, v: str) -> str:
        v = str(v).strip()
        if not _HHMM.match(v):
            raise ValueError("use 24-hour HH:MM, e.g. 07:00")
        return v

    @staticmethod
    def as_time(value: str) -> time:
        hour, minute = value.split(":")
        return time(int(hour), int(minute))


class AppConfig(BaseModel):
    settings: Settings = Field(default_factory=Settings)
    sources: list[SourceConfig] = Field(default_factory=list)
    service: ServiceConfig = Field(default_factory=ServiceConfig)

    @property
    def enabled_sources(self) -> list[SourceConfig]:
        return [s for s in self.sources if s.enabled]


class Secrets(BaseSettings):
    """Secrets come only from the environment or .env. SecretStr keeps them out of reprs and logs."""

    model_config = SettingsConfigDict(env_file=None, extra="ignore", env_ignore_empty=True)

    anthropic_api_key: SecretStr | None = None
    telegram_bot_token: SecretStr | None = None
    telegram_chat_id: int | None = None
    telegram_owner_id: int | None = None  # Salam's Telegram user id; defaults to the chat id
    email_user: str | None = None
    email_app_password: SecretStr | None = None
    email_to: str | None = None
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 465

    @property
    def owner_id(self) -> int | None:
        return self.telegram_owner_id or self.telegram_chat_id

    @property
    def telegram_ready(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_chat_id and self.owner_id)

    @property
    def email_ready(self) -> bool:
        return bool(self.email_user and self.email_app_password)

    def secret_values(self) -> list[str]:
        """Raw secret strings, used only to redact them from logs."""
        out = []
        for field in (self.anthropic_api_key, self.telegram_bot_token, self.email_app_password):
            if field and field.get_secret_value():
                out.append(field.get_secret_value())
        return out


class Paths:
    def __init__(self, root: Path, service: ServiceConfig):
        self.root = root
        self.config = root / "config.yaml"
        self.profile = root / "profile.yaml"
        self.goals = root / "goals.yaml"
        self.db = self._resolve(service.db_path)
        self.backups = self._resolve(service.backup_dir)
        self.v1_state = root / "state"

    def _resolve(self, value: str) -> Path:
        p = Path(value)
        return p if p.is_absolute() else self.root / p


class Config:
    """Everything the service needs to know. Secrets and `service:` are read at start-up only."""

    def __init__(self, root: Path | None = None, env_file: Path | str | None = "auto"):
        self.root = root or project_root()
        self.app = self._load_app()
        if env_file == "auto":
            env_file = self.root / ".env"
        self.secrets = Secrets(_env_file=env_file if env_file and Path(env_file).exists() else None)
        self.paths = Paths(self.root, self.app.service)

    def _load_app(self) -> AppConfig:
        raw = yaml.safe_load((self.root / "config.yaml").read_text(encoding="utf-8")) or {}
        return AppConfig.model_validate(
            {"settings": raw.get("settings") or {}, "sources": raw.get("sources") or [],
             "service": raw.get("service") or {}}
        )

    def reload(self) -> str | None:
        """Re-reads config.yaml so edits apply on the next run without a restart.

        Returns an error message (and keeps the previous config) if the new file is invalid.
        Schedule changes in `service:` still need a restart.
        """
        try:
            new = self._load_app()
        except Exception as exc:  # noqa: BLE001 — a typo in config.yaml must not stop the service
            return f"config.yaml not reloaded ({exc.__class__.__name__}: {str(exc)[:300]})"
        changed_service = new.service != self.app.service
        new.service = self.app.service  # the running schedule; changing it needs a restart
        self.app = new
        if changed_service:
            return "config.yaml: the service: section changed; restart the service to apply it"
        return None

    @property
    def settings(self) -> Settings:
        return self.app.settings

    @property
    def service(self) -> ServiceConfig:
        return self.app.service

    @property
    def profile_text(self) -> str:
        """Read fresh each time, so profile edits apply on the next run."""
        return self.paths.profile.read_text(encoding="utf-8")
