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
    # SEC EDGAR fair-access compliance. SEC requires every request carry a
    # User-Agent identifying the client; the policy text is at
    # https://www.sec.gov/os/accessing-edgar-data. Default points to the
    # public repo so SEC operators can reach the maintainer if needed.
    EDGAR_USER_AGENT: str = (
        "Market Analysis Agent "
        "(https://github.com/xuanbai01/Market-Analysis-Agent)"
    )
    # On-disk cache for SEC filings. Filings are immutable (amendments get
    # new accession numbers), so the cache never invalidates — write on
    # miss, read on hit. Override per-test via tmp_path. Fly's filesystem
    # is ephemeral on auto-stop, so this still wins within a machine's
    # lifetime; switch to a Fly volume only when cross-restart hit-rate
    # measurably matters.
    EDGAR_CACHE_DIR: str = ".edgar_cache"
    # FRED API key (https://fred.stlouisfed.org/docs/api/api_key.html).
    # Free tier is 120 req/min, plenty for on-demand research. Optional —
    # when missing, fetch_macro silently emits metadata claims (sector,
    # series_list) with None-valued data claims rather than 500ing.
    # Mirrors the NEWSAPI_KEY graceful-degradation pattern.
    FRED_API_KEY: str = ""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
