import os
from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    llm_provider: str = "openrouter"
    openrouter_api_key: str | None = None
    openrouter_model: str = "openai/gpt-4o-mini"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-3-5-haiku-latest"

    api_base_url: str = "http://localhost:8000"
    max_log_bytes: int = 2_097_152

    slack_webhook_url: str | None = None
    slack_bot_token: str | None = None
    slack_channel_id: str | None = None

    jira_base_url: str | None = None
    jira_email: str | None = None
    jira_api_token: str | None = None
    jira_project_key: str | None = None

    resend_api_key: str | None = None

    email_from: str | None = None
    email_to: str | None = None

    runs_dir: str = "runs"

    @model_validator(mode="after")
    def apply_platform_defaults(self) -> "Settings":

        if os.environ.get("VERCEL"):
            self.runs_dir = "/tmp/runs"
            vercel_url = os.environ.get("VERCEL_URL")
            if vercel_url:
                self.api_base_url = f"https://{vercel_url}"
        return self

    @property
    def slack_configured(self) -> bool:
        return bool(self.slack_webhook_url or (self.slack_bot_token and self.slack_channel_id))

    @property
    def jira_configured(self) -> bool:
        return bool(
            self.jira_base_url
            and self.jira_email
            and self.jira_api_token
            and self.jira_project_key
        )

    @property
    def email_configured(self) -> bool:
        return bool(
            self.resend_api_key
            and self.email_from
            and self.email_to
        )

    @property
    def llm_configured(self) -> bool:
        if self.llm_provider == "anthropic":
            return bool(self.anthropic_api_key)
        if self.llm_provider == "openrouter":
            return bool(self.openrouter_api_key)
        return False


@lru_cache
def get_settings() -> Settings:
    return Settings()
