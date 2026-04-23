from fastapi import FastAPI
from app.core.settings import settings
from app.api.v1.routers.health import router as health_router
from app.core.errors import problem_json_exception_handler, ProblemDetail, add_problem_handlers
from app.api.v1.routers import market, news, analysis, reports, forecasts, symbol

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
app.include_router(symbol.router, prefix="/v1")

@app.get("/")
def root():
    return {"message": "Hello from Market Analysis Agent"}
