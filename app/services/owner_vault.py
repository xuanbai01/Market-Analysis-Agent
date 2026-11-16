"""The owner's trade copy, encrypted (ADR 0009, amended 2026-11-15).

Each stored transaction is sealed on its own: AES-256-GCM under
``OWNER_VAULT_KEY`` (a Fly secret: 32 random bytes, base64) with a fresh
12-byte nonce. The associated data binds the ciphertext to its row: the
transaction id, the key version and the estimated-fee flag, the only things
stored in the clear, so a ciphertext copied onto another row, or a flag
changed in the table, doesn't open. Neon and its backups hold only
ciphertext (its length shows roughly how long each record is); the key
never leaves Fly. With no key there is no copy: ``seal`` refuses rather
than write anything in the clear.

Losing the key loses only the copy: tastytrade keeps the history, so the
table can be emptied and filled again under a new key.
"""
from __future__ import annotations

import base64
import json
import os
from functools import lru_cache
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


@lru_cache(maxsize=2)
def _cipher_for(raw: str) -> AESGCM:
    return AESGCM(base64.b64decode(raw, validate=True))  # 32 bytes: checked at start-up


def _cipher() -> AESGCM:
    raw = settings.OWNER_VAULT_KEY.get_secret_value()
    if not raw:
        raise VaultUnavailable("the trade copy's key isn't set on the server")
    return _cipher_for(raw)


def _associated(row_id: int, key_version: int, estimated_fee: bool) -> bytes:
    return f"owner-transaction:v{key_version}:{row_id}:{int(estimated_fee)}".encode()


def seal(payload: dict[str, Any], row_id: int, *, estimated_fee: bool) -> tuple[bytes, bytes]:
    """(nonce, ciphertext) of ``payload`` for the row ``row_id`` with that flag."""
    cipher = _cipher()
    nonce = os.urandom(NONCE_BYTES)
    plain = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    return nonce, cipher.encrypt(nonce, plain, _associated(row_id, KEY_VERSION, estimated_fee))


def unseal(nonce: bytes, ciphertext: bytes, row_id: int, *, key_version: int, estimated_fee: bool) -> dict[str, Any]:
    """The payload sealed for that row; ``VaultUnavailable`` when it doesn't
    open (another key or key version, another row's ciphertext, a changed
    flag, or a damaged row)."""
    if key_version != KEY_VERSION:
        raise VaultUnavailable("a stored trade is under another key version")
    if len(nonce) != NONCE_BYTES:
        raise VaultUnavailable("a stored trade is damaged")
    try:
        plain = _cipher().decrypt(nonce, ciphertext, _associated(row_id, key_version, estimated_fee))
        payload = json.loads(plain)
    except (InvalidTag, ValueError) as exc:
        raise VaultUnavailable("a stored trade doesn't open with this key") from exc
    if not isinstance(payload, dict):
        raise VaultUnavailable("a stored trade isn't a record")
    return payload
