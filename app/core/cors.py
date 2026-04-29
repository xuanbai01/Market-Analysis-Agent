"""
CORS configuration for the FastAPI app.

The frontend (Phase 3.1) lives on a public Vercel URL and the backend
on a public Fly URL — two distinct origins, so the browser issues a
CORS preflight ``OPTIONS`` before any non-trivial request and refuses
the response unless the server returns the right
``Access-Control-Allow-*`` headers.

Single allowlisted origin (never ``*``):

- ``*`` is incompatible with shipping an ``Authorization`` header in
  practice — browsers tighten enforcement when credentials/auth are
  involved, and even when they don't, ``*`` defeats the whole point of
  having a gate.
- We deliberately allow exactly one origin from
  ``settings.FRONTEND_ORIGIN``. To allowlist another (e.g. local
  ``http://localhost:5173`` for dev work against prod), set the env
  var to that origin in the relevant environment. Multi-origin
  allowlists can be added when there's a concrete second origin to
  serve; until then, the constraint is a feature.

The helper is a function (not inline in ``app/main.py``) so tests
can apply it to a bare throwaway FastAPI without going through the
full app wire-up.
"""
from __future__ import annotations

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware


def configure_cors(app: FastAPI, *, origin: str) -> None:
    """Install ``CORSMiddleware`` allowlisting ``origin``. No-op on empty.

    Allowed methods: ``GET, POST, OPTIONS`` — the surface the frontend
    actually uses.

    Allowed headers: ``Authorization, Content-Type`` — the bearer
    token (Phase 3.0 A1) and the JSON body header.

    Credentials disabled: we use bearer tokens in ``Authorization``,
    not cookies, so ``allow_credentials=False`` is safer (and is
    required to use a non-``*`` allow_origins safely with a credential
    surface).
    """
    if not origin:
        return  # CORS off; same-origin only

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[origin],
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
        allow_credentials=False,
    )
