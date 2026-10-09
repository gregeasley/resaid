"""Progress bars (tqdm, written to stderr) and result counts for each run mode."""

from __future__ import annotations

from aries_helpers import fit, make_production


def test_progress_tracking_vectorized(capsys):
    df = make_production(n_wells=5)
    dca = fit(df, three_phase=False)
    err = capsys.readouterr().err
    assert "Processing wells (vectorized mode)" in err

    params = dca.params_dataframe
    assert len(params) == df["API_UWI"].nunique()
    assert params[["qi", "di", "b"]].notna().all().all()


def test_progress_tracking_three_phase(capsys):
    df = make_production(n_wells=5)
    dca = fit(df, three_phase=True)
    err = capsys.readouterr().err
    assert "Processing wells (three-phase mode)" in err
    # One fit per well and phase.
    assert "15/15" in err

    params = dca.params_dataframe
    assert len(params) == 3 * df["API_UWI"].nunique()
    assert params[["qi", "di", "b"]].notna().all().all()
