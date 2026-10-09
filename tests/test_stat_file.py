"""Run-log (``DCA_LOG.txt``) lifecycle on ``decline_curve``."""

from __future__ import annotations

import io

import pytest

from resaid.dca import decline_curve, decline_solver


@pytest.fixture
def in_tmp(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _configured(df):
    dca = decline_curve()
    dca.dataframe = df
    dca.date_col = "DATE"
    dca.uid_col = "WELL_ID"
    dca.oil_col = "OIL"
    dca.gas_col = "GAS"
    dca.water_col = "WATER"
    dca.backup_decline = True
    return dca


@pytest.fixture
def small_df(combined_dca_dataframe):
    return combined_dca_dataframe


def test_construction_does_not_create_log(in_tmp):
    dca = decline_curve()
    decline_solver(qi=1000, qf=1, eur=60_000, b=1.2, t_max=1200).solve()
    assert not (in_tmp / "DCA_LOG.txt").exists()
    assert dca._stat_file is None


def test_log_opened_on_first_write_and_closed(in_tmp, small_df):
    dca = _configured(small_df)
    dca.run_DCA()
    log = in_tmp / "DCA_LOG.txt"
    assert log.exists()
    assert "Total fits attempted" in log.read_text(encoding="utf-8")
    handle = dca._stat_file
    assert handle is not None and not handle.closed
    dca.close()
    assert handle.closed
    dca.close()  # idempotent


def test_context_manager_closes_log(in_tmp, small_df):
    with _configured(small_df) as dca:
        dca.run_DCA()
        handle = dca._stat_file
    assert handle.closed


def test_stat_file_none_disables_logging(in_tmp, small_df):
    dca = _configured(small_df)
    dca.STAT_FILE = None
    dca.run_DCA()
    assert dca.STAT_FILE is None
    assert not (in_tmp / "DCA_LOG.txt").exists()


def test_assigned_stream_receives_log_and_is_not_closed(in_tmp, small_df):
    buf = io.StringIO()
    dca = _configured(small_df)
    dca.STAT_FILE = buf
    dca.run_DCA()
    dca.close()
    assert not buf.closed
    assert "Total fits attempted" in buf.getvalue()
    assert not (in_tmp / "DCA_LOG.txt").exists()


def test_custom_log_path(tmp_path, small_df):
    target = tmp_path / "logs" / "run.txt"
    target.parent.mkdir()
    dca = _configured(small_df)
    dca.stat_file_path = target
    dca.run_DCA()
    dca.close()
    assert "Total fits attempted" in target.read_text(encoding="utf-8")
