import uuid

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel


class ProblemDetail(BaseModel):
    type: str = "about:blank"
    title: str
    status: int
    detail: str | None = None
    instance: str | None = None


_PROBLEM_MEDIA_TYPE = "application/problem+json"


def _problem_response(
    status: int,
    title: str,
    detail: str | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body = ProblemDetail(
        title=title,
        status=status,
        detail=detail,
        instance=str(uuid.uuid4()),
    ).model_dump()
    return JSONResponse(
        body,
        status_code=status,
        media_type=_PROBLEM_MEDIA_TYPE,
        headers=headers,
    )


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    # Preserve the caller's status code (404, 422, etc.) — don't flatten to 500.
    # Also propagate ``exc.headers`` so things like Retry-After (on 429),
    # Allow (on 405), WWW-Authenticate (on 401) survive the wrap.
    return _problem_response(
        status=exc.status_code,
        title=exc.detail if isinstance(exc.detail, str) else "HTTP Error",
        detail=exc.detail if not isinstance(exc.detail, str) else None,
        headers=exc.headers,
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return _problem_response(
        status=422,
        title="Unprocessable Entity",
        detail=str(exc.errors()),
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    return _problem_response(status=500, title="Internal Server Error", detail=str(exc))


def add_problem_handlers(app: FastAPI) -> None:
    """Register RFC 7807 problem+json handlers on the FastAPI app."""
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
