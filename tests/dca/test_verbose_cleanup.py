"""
Per-well diagnostics are emitted only when verbose; the run summary is always
written to the run log; verbosity never changes results.
"""

from __future__ import annotations

import io
import logging

import pandas as pd
import pytest

from aries_helpers import fit, make_production

LOGGER = "resaid.dca.decline_curve"


@pytest.fixture(scope="module")
def df():
    return make_production(n_wells=5, months=12)


def _per_well_messages(caplog):
    return [r.getMessage() for r in caplog.records if r.getMessage().startswith("Well ARIES_WELL_")]


def test_default_run_has_no_per_well_logs(df, caplog):
    caplog.set_level(logging.INFO, logger=LOGGER)
    fit(df, three_phase=False)
    assert _per_well_messages(caplog) == []


def test_verbose_run_logs_each_well(df, caplog):
    caplog.set_level(logging.INFO, logger=LOGGER)
    fit(df, three_phase=False, verbose=True)
    msgs = _per_well_messages(caplog)
    for uid in df["API_UWI"].unique():
        assert any(m.startswith(f"Well {uid}: After peak detection") for m in msgs), uid


@pytest.mark.parametrize("verbose", [False, True])
def test_summary_always_written_to_run_log(df, verbose):
    buf = io.StringIO()
    fit(df, three_phase=False, verbose=verbose, STAT_FILE=buf)
    log = buf.getvalue()
    assert "DCA summary (vectorized major-phase mode)" in log
    assert f"Total fits attempted: {df['API_UWI'].nunique()}" in log
    assert ("Generating decline parameters." in log) is verbose


def test_verbose_does_not_change_results(df):
    quiet = fit(df, three_phase=False).params_dataframe
    loud = fit(df, three_phase=False, verbose=True).params_dataframe
    cols = ["UID", "qi", "di", "b", "t0"]
    pd.testing.assert_frame_equal(
        quiet[cols].reset_index(drop=True), loud[cols].reset_index(drop=True)
    )
