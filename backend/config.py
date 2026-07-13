"""Configuration: secrets and access from env; branding from org_config.json."""
from __future__ import annotations

import json
import os
from functools import lru_cache
from typing import Any, Dict, List

from pydantic_settings import BaseSettings, SettingsConfigDict

_ROOT = os.path.dirname(os.path.dirname(__file__))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    secret_key: str = "dev-insecure-secret-change-me"
    database_url: str = ""

    allowed_email_domains: str = "example.org"
    initial_admin_emails: str = ""
    dev_auth: bool = True

    google_client_id: str = ""
    google_client_secret: str = ""
    base_url: str = "http://localhost:8000"

    anthropic_api_key: str = ""
    strong_model: str = "claude-sonnet-5"
    fast_model: str = "claude-haiku-4-5"
    recal_model: str = "claude-opus-4-8"

    recal_cadence_days: int = 90
    recal_min_outcomes: int = 15

    @property
    def allowed_domains(self) -> List[str]:
        return [d.strip().lower() for d in self.allowed_email_domains.split(",") if d.strip()]

    @property
    def admin_emails(self) -> List[str]:
        return [e.strip().lower() for e in self.initial_admin_emails.split(",") if e.strip()]

    @property
    def use_google_oauth(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret)

    @property
    def mock_mode(self) -> bool:
        return not bool(self.anthropic_api_key)

    @property
    def sqlalchemy_url(self) -> str:
        url = self.database_url.strip()
        if not url:
            return "sqlite:///./fit_scorer.db"
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)
        return url


DEFAULT_ORG_CONFIG: Dict[str, Any] = {
    "org_name": "Your Organization",
    "tool_name": "Funding Fit Scorer",
    "tagline": "Score funding opportunities against our strategy.",
    "brand_color": "#0f766e",
    "brand_color_dark": "#115e59",
    "currency": "USD",
}


@lru_cache
def get_org_config() -> Dict[str, Any]:
    """Read org_config.json if present, else the example, else built-in defaults."""
    for name in ("org_config.json", "org_config.example.json"):
        path = os.path.join(_ROOT, name)
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                return {**DEFAULT_ORG_CONFIG, **data}
            except Exception:  # noqa: BLE001
                pass
    return dict(DEFAULT_ORG_CONFIG)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
org_config = get_org_config()
