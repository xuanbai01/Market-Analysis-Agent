from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import uuid


class ProblemDetail(BaseModel):
    type: str = "about:blank"
    title: str
    status: int
    detail: str | None = None
    instance: str | None = None


def _problem(status: int, title: str, detail: str | None = None) -> dict:
    return ProblemDetail(
        title=title,
        status=status,
        detail=detail,
        instance=str(uuid.uuid4()),
    ).model_dump()


async def problem_json_exception_handler(request: Request, exc: Exception):
    """
    Catch-all exception handler that returns RFC 7807-style JSON.
    For now we treat all unhandled exceptions as 500.
    """
    return JSONResponse(
        _problem(500, "Internal Server Error", str(exc)),
        status_code=500,
        media_type="application/problem+json",
    )


def add_problem_handlers(app: FastAPI):
    """
    Register problem+json handlers on the FastAPI app.
    Later you can add more specific handlers (HTTPException, ValidationError, etc.).
    """
    app.add_exception_handler(Exception, problem_json_exception_handler)
