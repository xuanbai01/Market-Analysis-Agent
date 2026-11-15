"""The owner's trade copy is encrypted per row (ADR 0009, amended): AES-256-GCM
under OWNER_VAULT_KEY, a fresh nonce each time, and the transaction id as
associated data, so a ciphertext moved onto another row doesn't open."""
from __future__ import annotations

import base64

import pytest
from pydantic import SecretStr, ValidationError

from app.core import settings as settings_module
from app.core.settings import Settings
from app.services import owner_vault as vault

KEY = base64.b64encode(bytes(range(32))).decode()
OTHER = base64.b64encode(bytes(range(1, 33))).decode()


@pytest.fixture(autouse=True)
def keyed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings_module.settings, "OWNER_VAULT_KEY", SecretStr(KEY))


def test_a_row_round_trips() -> None:
    payload = {"symbol": "NVDA  261218C00175000", "net-value": "-412.35", "account": 1}
    nonce, ciphertext = vault.seal(payload, 4242)
    assert len(nonce) == vault.NONCE_BYTES
    assert vault.unseal(nonce, ciphertext, 4242) == payload


def test_nothing_readable_is_stored() -> None:
    _nonce, ciphertext = vault.seal({"symbol": "ZZQXDISTINCT", "description": "Sold 1 ZZQXDISTINCT"}, 1)
    assert b"ZZQXDISTINCT" not in ciphertext


def test_each_seal_has_its_own_nonce() -> None:
    first, _ = vault.seal({"a": 1}, 1)
    second, _ = vault.seal({"a": 1}, 1)
    assert first != second


def test_a_ciphertext_moved_to_another_row_does_not_open() -> None:
    nonce, ciphertext = vault.seal({"a": 1}, 1)
    with pytest.raises(vault.VaultUnavailable):
        vault.unseal(nonce, ciphertext, 2)


def test_another_key_does_not_open_it(monkeypatch: pytest.MonkeyPatch) -> None:
    nonce, ciphertext = vault.seal({"a": 1}, 1)
    monkeypatch.setattr(settings_module.settings, "OWNER_VAULT_KEY", SecretStr(OTHER))
    with pytest.raises(vault.VaultUnavailable):
        vault.unseal(nonce, ciphertext, 1)


def test_without_a_key_it_refuses_and_writes_nothing_in_the_clear(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings_module.settings, "OWNER_VAULT_KEY", SecretStr(""))
    assert vault.is_configured() is False
    with pytest.raises(vault.VaultUnavailable):
        vault.seal({"a": 1}, 1)


@pytest.mark.parametrize(
    ("overrides", "problem"),
    [
        ({"OWNER_VAULT_KEY": "not base64!"}, "OWNER_VAULT_KEY"),
        ({"OWNER_VAULT_KEY": base64.b64encode(bytes(16)).decode()}, "32 bytes"),
        ({"OWNER_VAULT_KEY": KEY, "OWNER_KEY": KEY}, "differ"),
    ],
)
def test_a_bad_vault_key_refuses_to_start(overrides: dict[str, str], problem: str) -> None:
    with pytest.raises(ValidationError, match=problem):
        Settings(_env_file=None, **overrides)  # type: ignore[arg-type]
    Settings(_env_file=None, OWNER_VAULT_KEY=KEY)  # a 32-byte key is fine
