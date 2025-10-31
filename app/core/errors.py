from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from flask import app
from pydantic import BaseModel
import uuid


class ProblemDetail(BaseModel):
    type: str = "about:blank"
    title: str
    status: int
    detail: str | None = None
    instance: str | None = None


def _problem(status: int, title: str, detail: str | None = None) -> dict:
    return ProblemDetail(title=title, status=status, detail=detail, instance=str(uuid.uuid4())).model_dump()


async def problem_json_exception_handler(request: Request, exc):
    return JSONResponse(_problem(500, "Internal Server Error", str(exc)), status_code=500, media_type="application/problem+json")


def add_problem_handlers(app: FastAPI):
    app.add_exception_handler(Exception, problem_json_exception_handler)