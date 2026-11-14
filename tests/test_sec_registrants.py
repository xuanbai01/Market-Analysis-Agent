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


# Older reorganizations, each checked against SEC's submissions JSON on
# 2026-11-13. A new registrant's first 10-K carries a few years back, so
# without the link each history had ten of its eleven points.


def test_disney_follows_back_to_twdc_enterprises() -> None:
    """The Walt Disney Company moved to TWDC Holdco 613 (8-K12B
    2019-03-20); the old registrant, renamed TWDC Enterprises 18 Corp.,
    holds the 10-Ks to November 2018."""
    assert registrant_chain("0001744489") == ("0001744489", "0001001039")


def test_cigna_follows_back_to_cigna_holding() -> None:
    """Cigna moved to Halfmoon Parent with the Express Scripts deal
    (8-K12B 2018-12-20); the old registrant, renamed Cigna Holding Co,
    holds the 10-Ks to February 2018."""
    assert registrant_chain("0001739940") == ("0001739940", "0000701221")


def test_broadcom_follows_back_through_broadcom_ltd_to_avago() -> None:
    """Two moves: Broadcom Inc. (8-K12B 2018-04-04) replaced Broadcom
    Ltd (now Broadcom Pte. Ltd.), which had replaced Avago Technologies
    (8-K12B 2016-02-02)."""
    assert registrant_chain("0001730168") == ("0001730168", "0001649338", "0001441634")
