from pathlib import Path
from typing import List, Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # Environment
    app_env: str = Field(default="development", alias="APP_ENV")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    secret_key: str = Field(default="dev-secret-key-change-in-production", alias="SECRET_KEY")

    # Reactive Resume
    reactive_resume_base_url: str = Field(
        default="https://rxresu.me/api/openapi",
        alias="REACTIVE_RESUME_BASE_URL"
    )
    reactive_resume_api_key: str = Field(default="", alias="REACTIVE_RESUME_API_KEY")
    # The master CV lives in config/candidate-profile.yaml, under reactive_resume.
    # It is chosen from the dashboard, so it is deliberately not an env var.

    # Telegram
    telegram_bot_token: str = Field(default="", alias="TELEGRAM_BOT_TOKEN")
    telegram_chat_id: str = Field(default="", alias="TELEGRAM_CHAT_ID")

    # LLM Providers
    default_llm_provider: str = Field(default="openai", alias="DEFAULT_LLM_PROVIDER")
    openai_api_key: Optional[str] = Field(default=None, alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-4o", alias="OPENAI_MODEL")
    anthropic_api_key: Optional[str] = Field(default=None, alias="ANTHROPIC_API_KEY")
    anthropic_model: str = Field(default="claude-3-5-sonnet-20241022", alias="ANTHROPIC_MODEL")
    gemini_api_key: Optional[str] = Field(default=None, alias="GEMINI_API_KEY")
    gemini_model: str = Field(default="gemini-1.5-pro", alias="GEMINI_MODEL")
    openrouter_api_key: Optional[str] = Field(default=None, alias="OPENROUTER_API_KEY")
    ollama_base_url: str = Field(default="http://localhost:11434", alias="OLLAMA_BASE_URL")

    # InfoJobs API (https://developer.infojobs.net)
    infojobs_client_id: str = Field(default="", alias="INFOJOBS_CLIENT_ID")
    infojobs_client_secret: str = Field(default="", alias="INFOJOBS_CLIENT_SECRET")
    infojobs_access_token: str = Field(default="", alias="INFOJOBS_ACCESS_TOKEN")
    infojobs_refresh_token: str = Field(default="", alias="INFOJOBS_REFRESH_TOKEN")
    infojobs_redirect_uri: str = Field(default="", alias="INFOJOBS_REDIRECT_URI")
    infojobs_curriculum_code: str = Field(default="", alias="INFOJOBS_CURRICULUM_CODE")

    # Database & Message Queue
    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/jobagent",
        alias="DATABASE_URL"
    )
    database_url_sync: str = Field(
        default="postgresql://postgres:postgres@localhost:5432/jobagent",
        alias="DATABASE_URL_SYNC"
    )
    rabbitmq_url: str = Field(
        default="amqp://guest:guest@localhost:5672//",
        alias="RABBITMQ_URL"
    )

    # Browser Automation
    playwright_headless: bool = Field(default=True, alias="PLAYWRIGHT_HEADLESS")
    playwright_timeout_ms: int = Field(default=30000, alias="PLAYWRIGHT_TIMEOUT_MS")
    browser_user_data_dir: str = Field(default="./browser_sessions", alias="BROWSER_USER_DATA_DIR")

    # API Settings
    api_host: str = Field(default="0.0.0.0", alias="API_HOST")
    api_port: int = Field(default=8000, alias="API_PORT")
    cors_origins: str = Field(
        default="http://localhost:3000,http://localhost:5173",
        alias="CORS_ORIGINS"
    )

    # Browser extension
    extension_auth_required: bool = Field(default=True, alias="EXTENSION_AUTH_REQUIRED")
    dashboard_url: str = Field(default="http://localhost:3000", alias="DASHBOARD_URL")

    # Candidate Profile Path
    candidate_profile_path: Path = Field(
        default=Path("config/candidate-profile.yaml"),
        alias="CANDIDATE_PROFILE_PATH"
    )

    @property
    def cors_origins_list(self) -> List[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()
