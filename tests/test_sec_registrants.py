"""Which SEC registrants hold a company's filing history
(app/services/sec_registrants.py)."""
from __future__ import annotations

import pytest

from app.services import sec_registrants
from app.services.sec_registrants import predecessors_of, registrant_chain


def test_a_registrant_with_no_recorded_predecessor_stands_alone() -> None:
    assert predecessors_of("0000320193") == ()
    assert registrant_chain("0000320193") == ("0000320193",)


def test_exxons_holding_company_follows_back_to_exxon_mobil_corp() -> None:
    """XOM moved to a new registrant on 2026-07-01; the 10-Ks and ten
    years of XBRL facts stayed under the old one."""
    assert predecessors_of("0002115436") == ("0000034088",)
    assert registrant_chain("0002115436") == ("0002115436", "0000034088")


def test_a_chain_of_reorganizations_is_followed_to_the_end(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        sec_registrants,
        "PREDECESSOR_CIKS",
        {"0000000003": ("0000000002",), "0000000002": ("0000000001",)},
    )
    assert predecessors_of("0000000003") == ("0000000002", "0000000001")
    assert predecessors_of("0000000002") == ("0000000001",)


def test_a_loop_in_the_map_ends_instead_of_spinning(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        sec_registrants,
        "PREDECESSOR_CIKS",
        {"0000000002": ("0000000001",), "0000000001": ("0000000002",)},
    )
    assert predecessors_of("0000000002") == ("0000000001",)


def test_every_recorded_cik_is_ten_digits() -> None:
    """SEC URLs need the zero-padded form; a short CIK would 404 silently."""
    for successor, predecessors in sec_registrants.PREDECESSOR_CIKS.items():
        for cik in (successor, *predecessors):
            assert len(cik) == 10 and cik.isdigit(), cik
