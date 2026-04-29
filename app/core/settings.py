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
    # SEC EDGAR fair-access compliance. SEC's policy
    # (https://www.sec.gov/os/accessing-edgar-data) requires every request
    # to carry a ``User-Agent`` declaring NAME + EMAIL. SEC's edge layer
    # rejects UAs that lack an email-shaped token (HTTP 403) and also
    # blocks several "obviously non-deliverable" domains including
    # ``users.noreply.github.com``.
    #
    # The default below uses an ``example.com`` placeholder that satisfies
    # SEC's parser and lets a fresh clone exercise EDGAR locally. It is
    # NOT spec-compliant — ``example.com`` is RFC 2606 reserved and
    # unmonitored. **Production deployments MUST override via the
    # ``EDGAR_USER_AGENT`` env var with a monitored address**, otherwise
    # SEC has no way to reach the operator if the client misbehaves and
    # may revoke access.
    EDGAR_USER_AGENT: str = "Market Analysis Agent admin@example.com"
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
    # Research-report cache window. The /v1/research/{symbol} endpoint
    # caches successful reports in ``research_reports``; subsequent
    # requests within this many hours re-serve the cached row instead
    # of paying for a fresh LLM round trip. Default 168 (7 days)
    # matches the natural refresh cadence of equity-research data:
    # quality / capital-allocation / 10-K-derived metrics change
    # quarterly or annually, and the price-anchored bits (valuation,
    # peer P/Es, 10Y yield) being a few days stale is fine for
    # long-term diligence. ``?refresh=true`` always bypasses the
    # cache. See ADR / 2.2b plan for the trade-off discussion.
    RESEARCH_CACHE_MAX_AGE_HOURS: int = 168
    # Per-IP rate limit on /v1/research/{symbol}. 3 reports/hour is the
    # default — covers a research-pace usage pattern (a handful of
    # symbols looked up over a working session) while bounding the
    # damage if the URL leaks. The cache (Phase 2.2b) means a repeat
    # ?refresh=false request costs nothing, so the limit only kicks
    # in for genuinely new (symbol, focus) combinations or
    # ?refresh=true calls. Set to 0 to disable rate limiting entirely
    # (useful for tests and single-user dev). In-memory token bucket
    # keyed on X-Forwarded-For (when present) or direct connection IP.
    RESEARCH_RATE_LIMIT_PER_HOUR: int = 3

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
