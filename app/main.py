from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response

from app.api.v1.routers import demo, lens, market, news, options, owner, research, symbol
from app.api.v1.routers.health import router as health_router
from app.core.cors import configure_cors
from app.core.errors import add_problem_handlers
from app.core.logging import configure_logging
from app.core.settings import settings

# app.* INFO to stderr, so `fly logs` shows each external call's latency.
configure_logging()

app = FastAPI(
    title="Market Analysis Agent API",
    version="1.0.0",
    docs_url="/docs",
    openapi_url="/openapi.json",
)

# CORS for the React frontend (Phase 3). No-op when FRONTEND_ORIGIN is
# unset — installs CORSMiddleware allowlisting exactly one origin
# otherwise. See app/core/cors.py for the why.
configure_cors(app, origin=settings.FRONTEND_ORIGIN)

# RFC 7807 error responses
add_problem_handlers(app)


# The owner's account data never sits in a browser's or a proxy's cache:
# every response under /v1/owner says so, its 401/403/429/503s included.
@app.middleware("http")
async def owner_responses_are_never_stored(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    response = await call_next(request)
    if request.url.path.startswith(f"/v1{owner.OWNER_PREFIX}"):
        response.headers["Cache-Control"] = "no-store"
    return response


# v1 routers
app.include_router(health_router, prefix="/v1")
app.include_router(market.router, prefix="/v1")
app.include_router(news.router, prefix="/v1")
app.include_router(research.router, prefix="/v1")
app.include_router(symbol.router, prefix="/v1")
app.include_router(lens.router, prefix="/v1")
app.include_router(options.router, prefix="/v1")
# The owner's account data: the shared secret and the owner key (ADR 0009).
app.include_router(owner.router, prefix="/v1")
# Public read-only demo: open by design, off unless DEMO_SYMBOLS is set.
app.include_router(demo.router, prefix="/v1")

@app.get("/")
def root():
    return {"message": "Hello from Market Analysis Agent"}
