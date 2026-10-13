"""
ARIES export decline-type selection (hyperbolic / exponential / flat).

Every phase line written by ``generate_aries_export`` is checked against an
independent model of the selection rules, across scenarios chosen so that each
branch is exercised.
"""

from __future__ import annotations

import pytest
from aries_helpers import expected_aries, fit, make_production, parse_aries

SCENARIO = "TEST"


def _export_and_compare(dca, tmp_path, dmin, write_water=True):
    path = tmp_path / f"aries_{dmin}.txt"
    dca.generate_aries_export(file_path=str(path), scenario=SCENARIO, dmin=dmin, write_water=write_water)
    actual = parse_aries(path, SCENARIO)
    expected = expected_aries(dca, dmin, write_water)

    assert set(actual) == set(expected)
    for uid, exp in expected.items():
        got = actual[uid]
        assert got["start"] == exp["start"], uid
        assert set(got["phases"]) == set(exp["phases"]), uid
        for label, exp_line in exp["phases"].items():
            got_line = got["phases"][label]
            assert got_line["kind"] == exp_line["kind"], (uid, label, got_line, exp_line)
            for key, value in exp_line.items():
                if key != "kind":
                    assert got_line[key] == pytest.approx(value), (uid, label, key)
    return actual


@pytest.mark.parametrize("three_phase", [True, False], ids=["three_phase", "ratio"])
def test_hyperbolic_lines_match_model(tmp_path, three_phase):
    dca = fit(make_production(), three_phase)
    actual = _export_and_compare(dca, tmp_path, dmin=6)
    kinds = {p["kind"] for w in actual.values() for p in w["phases"].values()}
    assert "hyperbolic" in kinds


def test_low_b_uses_exponential_at_revised_decline(tmp_path):
    # Force b <= 0.05 so the hyperbolic branch is not eligible.
    dca = fit(make_production(), True, min_h_b=0.01, max_h_b=0.04)
    actual = _export_and_compare(dca, tmp_path, dmin=6)
    lines = [p for w in actual.values() for p in w["phases"].values()]
    assert lines and all(p["kind"] == "exponential" for p in lines)
    assert any(p["de"] > 6 for p in lines)


def test_decline_below_dmin_uses_terminal_exponential(tmp_path):
    # With a very high terminal decline every revised decline is below dmin.
    dca = fit(make_production(), True)
    actual = _export_and_compare(dca, tmp_path, dmin=99)
    lines = [p for w in actual.values() for p in w["phases"].values()]
    assert lines and all(p["kind"] == "exponential" and p["de"] == 99 for p in lines)


def test_shut_in_well_is_flat(tmp_path):
    shut_in = "ARIES_WELL_001"
    dca = fit(make_production(shut_in_well=shut_in), True)
    actual = _export_and_compare(dca, tmp_path, dmin=6)
    flat = [label for label, p in actual[shut_in]["phases"].items() if p["kind"] == "flat"]
    assert flat, actual[shut_in]
    others = [p for uid, w in actual.items() if uid != shut_in for p in w["phases"].values()]
    assert all(p["kind"] != "flat" for p in others)


@pytest.mark.parametrize("dmin", [6, 12, 18])
def test_dmin_written_on_hyperbolic_and_continuation_lines(tmp_path, dmin):
    dca = fit(make_production(), True)
    actual = _export_and_compare(dca, tmp_path, dmin=dmin)
    hyperbolic = [p for w in actual.values() for p in w["phases"].values() if p["kind"] == "hyperbolic"]
    assert hyperbolic
    assert all(p["dmin"] == dmin and p["continuation"] == dmin for p in hyperbolic)


def test_water_omitted_unless_requested(tmp_path):
    dca = fit(make_production(), True)
    actual = _export_and_compare(dca, tmp_path, dmin=6, write_water=False)
    assert all("WTR" not in w["phases"] for w in actual.values())
