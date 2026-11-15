"""The owner's trade copy, encrypted (ADR 0009, amended 2026-11-15).

Each stored transaction is sealed on its own: AES-256-GCM under
``OWNER_VAULT_KEY`` (a Fly secret: 32 random bytes, base64), a fresh 12-byte
nonce each time, and the transaction's id as associated data, so a
ciphertext copied onto another row doesn't open. Neon and its backups hold
only ciphertext; the key never leaves Fly. With no key there is no copy:
``seal`` refuses rather than write anything in the clear.

Losing the key loses only the copy: tastytrade keeps the history, so the
table can be emptied and filled again under a new key.
"""
from __future__ import annotations

import base64
import json
import os
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.settings import settings

KEY_VERSION = 1
NONCE_BYTES = 12


class VaultUnavailable(Exception):
    """No usable key, or a stored row that doesn't open with it."""


def is_configured() -> bool:
    return bool(settings.OWNER_VAULT_KEY.get_secret_value())


def _cipher() -> AESGCM:
    raw = settings.OWNER_VAULT_KEY.get_secret_value()
    if not raw:
        raise VaultUnavailable("the trade copy's key isn't set on the server")
    return AESGCM(base64.b64decode(raw, validate=True))  # 32 bytes: checked at start-up


def _associated(row_id: int) -> bytes:
    return f"owner-transaction:{row_id}".encode()


def seal(payload: dict[str, Any], row_id: int) -> tuple[bytes, bytes]:
    """(nonce, ciphertext) of ``payload`` for the row ``row_id``."""
    cipher = _cipher()
    nonce = os.urandom(NONCE_BYTES)
    plain = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    return nonce, cipher.encrypt(nonce, plain, _associated(row_id))


def unseal(nonce: bytes, ciphertext: bytes, row_id: int) -> dict[str, Any]:
    """The payload sealed for ``row_id``; ``VaultUnavailable`` when it doesn't
    open (another key, or a ciphertext from another row)."""
    try:
        plain = _cipher().decrypt(nonce, ciphertext, _associated(row_id))
    except InvalidTag as exc:
        raise VaultUnavailable("a stored trade doesn't open with this key") from exc
    payload = json.loads(plain)
    if not isinstance(payload, dict):
        raise VaultUnavailable("a stored trade isn't a record")
    return payload
