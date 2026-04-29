from fastapi import FastAPI

from app.api.v1.routers import (
    analysis,
    forecasts,
    market,
    news,
    reports,
    research,
    symbol,
)
from app.api.v1.routers.health import router as health_router
from app.core.errors import add_problem_handlers

app = FastAPI(
    title="Market Analysis Agent API",
    version="1.0.0",
    docs_url="/docs",
    openapi_url="/openapi.json",
)

# RFC 7807 error responses
add_problem_handlers(app)

# v1 routers
app.include_router(health_router, prefix="/v1")
app.include_router(market.router, prefix="/v1")
app.include_router(news.router, prefix="/v1")
app.include_router(analysis.router, prefix="/v1")
app.include_router(reports.router, prefix="/v1")
app.include_router(forecasts.router, prefix="/v1")
app.include_router(research.router, prefix="/v1")
app.include_router(symbol.router, prefix="/v1")

@app.get("/")
def root():
    return {"message": "Hello from Market Analysis Agent"}
