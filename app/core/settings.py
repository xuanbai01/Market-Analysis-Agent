from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    APP_ENV: str = "dev"
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/marketdb"
    TZ: str = "America/New_York"
    # Anthropic API key. Empty default so the app boots without it locally
    # (LLM-backed routes will 503 until set); production sets it via Fly
    # secrets. Never log this — `app.core.observability` redacts by default.
    ANTHROPIC_API_KEY: str = ""
    # NewsAPI key (https://newsapi.org). Free dev tier = 100 req/day, fine
    # for on-demand research. Empty default; the news-ingestion service
    # silently skips the NewsAPI provider when missing rather than 500ing.
    NEWSAPI_KEY: str = ""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
