"""Full ``decline_curve`` workflow aligned with ``examples/simple_example.py`` and ratio mode."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from resaid.dca import DCA_FIT_METHOD_MONOTONE_TWO_STEP, decline_curve


@pytest.mark.parametrize("three_phase_mode", [True, False])
def test_run_dca_and_oneline(combined_dca_dataframe: pd.DataFrame, three_phase_mode: bool):
    dca = decline_curve()
    dca.three_phase_mode = three_phase_mode
    dca.dataframe = combined_dca_dataframe
    dca.date_col = "DATE"
    dca.phase_col = "PHASE"
    dca.uid_col = "WELL_ID"
    dca.oil_col = "OIL"
    dca.gas_col = "GAS"
    dca.water_col = "WATER"

    dca.run_DCA()
    dca.generate_oneline(denormalize=True)

    assert not dca._params_dataframe.empty
    assert not dca._oneline.empty
    assert "UID" in dca._oneline.columns


def test_oneline_row_count_matches_wells(combined_dca_dataframe: pd.DataFrame):
    dca = decline_curve()
    dca.three_phase_mode = True
    dca.dataframe = combined_dca_dataframe
    dca.date_col = "DATE"
    dca.phase_col = "PHASE"
    dca.uid_col = "WELL_ID"
    dca.oil_col = "OIL"
    dca.gas_col = "GAS"
    dca.water_col = "WATER"
    dca.run_DCA()
    dca.generate_oneline(denormalize=True)

    n_wells = combined_dca_dataframe["WELL_ID"].nunique()
    assert len(dca._oneline) == n_wells


def test_run_dca_with_monotone_two_step_fit(combined_dca_dataframe: pd.DataFrame):
    dca = decline_curve(fit_method=DCA_FIT_METHOD_MONOTONE_TWO_STEP)
    dca.three_phase_mode = False
    dca.dataframe = combined_dca_dataframe
    dca.date_col = "DATE"
    dca.phase_col = "PHASE"
    dca.uid_col = "WELL_ID"
    dca.oil_col = "OIL"
    dca.gas_col = "GAS"
    dca.water_col = "WATER"

    dca.run_DCA()
    dca.generate_oneline(denormalize=True)

    assert not dca._params_dataframe.empty
    assert not dca._oneline.empty


def test_dca_succeeds_with_unsorted_input(combined_dca_dataframe: pd.DataFrame):
    """Unsorted production rows per well must not break DCA or oneline generation."""
    shuffled_parts = []
    for _, group in combined_dca_dataframe.groupby("WELL_ID"):
        shuffled_parts.append(group.sample(frac=1, random_state=42))
    unsorted_df = pd.concat(shuffled_parts, ignore_index=True)

    dca = decline_curve()
    dca.three_phase_mode = False
    dca.dataframe = unsorted_df
    dca.date_col = "DATE"
    dca.phase_col = "PHASE"
    dca.uid_col = "WELL_ID"
    dca.oil_col = "OIL"
    dca.gas_col = "GAS"
    dca.water_col = "WATER"

    dca.run_DCA()

    assert dca._params_dataframe["qi"].notna().any()
    assert dca._params_dataframe["t0"].notna().any()

    dca.generate_oneline(denormalize=True)
    assert not dca._oneline.empty
    assert "T0_DATE" in dca._oneline.columns


def test_typecurve_overlays_history_without_mutating_flowstream(combined_dca_dataframe: pd.DataFrame):
    """Typecurve uses historical overlay; _flowstream_dataframe stays forecast-only."""
    dca = decline_curve()
    dca.three_phase_mode = False
    dca.dataframe = combined_dca_dataframe
    dca.date_col = "DATE"
    dca.phase_col = "PHASE"
    dca.uid_col = "WELL_ID"
    dca.oil_col = "OIL"
    dca.gas_col = "GAS"
    dca.water_col = "WATER"

    dca.run_DCA()
    dca.generate_flowstream(denormalize=True)
    flow_before = dca._flowstream_dataframe.copy()

    # Force first producing month (hist T_INDEX=0 → overlay T_INDEX=1) above forecast
    hist_mask = (dca._dataframe[dca._uid_col] == dca._dataframe[dca._uid_col].iloc[0]) & (
        dca._dataframe["T_INDEX"] == 0
    )
    assert hist_mask.any(), "expected historical row at T_INDEX=0"
    uid = dca._dataframe.loc[hist_mask, dca._uid_col].iloc[0]
    bumped = float(dca._dataframe.loc[hist_mask, dca._oil_col].iloc[0]) + 1_000_000.0
    dca._dataframe.loc[hist_mask, dca._oil_col] = bumped

    overlay = dca._build_typecurve_flowstream(denormalize=True)
    overlay_row = overlay[(overlay["UID"] == uid) & (overlay["T_INDEX"] == 1)]
    assert len(overlay_row) == 1
    assert float(overlay_row["OIL"].iloc[0]) == bumped

    forecast_row = flow_before.reset_index()
    forecast_row = forecast_row[(forecast_row["UID"] == uid) & (forecast_row["T_INDEX"] == 1)]
    assert len(forecast_row) == 1
    assert float(forecast_row["OIL"].iloc[0]) != bumped

    assert overlay["OIL"].sum() > flow_before.reset_index()["OIL"].sum()

    dca.generate_typecurve(denormalize=True, return_params=True, num_months=120)
    pd.testing.assert_frame_equal(dca._flowstream_dataframe, flow_before)
    assert dca._typecurve is not None
    assert not dca._typecurve.empty
    assert hasattr(dca, "tc_params")
    assert not dca.tc_params.empty


def test_tc_params_rate_t0_is_curve_time_zero(combined_dca_dataframe: pd.DataFrame):
    """rate_t0 is empirical curve rate at first T_INDEX, not fitted Arps t0."""
    dca = decline_curve()
    dca.three_phase_mode = False
    dca.dataframe = combined_dca_dataframe.copy()
    dca.date_col = "DATE"
    dca.phase_col = "PHASE"
    dca.uid_col = "WELL_ID"
    dca.oil_col = "OIL"
    dca.gas_col = "GAS"
    dca.water_col = "WATER"

    dca.run_DCA()
    dca.generate_flowstream(denormalize=True, num_months=120)

    # Late historical peak so peak_rate and rate_t0 diverge
    uid = dca._dataframe[dca._uid_col].iloc[0]
    late = (dca._dataframe[dca._uid_col] == uid) & (dca._dataframe["T_INDEX"] == 8)
    assert late.any()
    dca._dataframe.loc[late, dca._oil_col] = (
        dca._dataframe.loc[late, dca._oil_col].astype(float) + 50_000.0
    )

    dca.generate_typecurve(
        denormalize=True, return_params=True, num_months=120, prob_levels=[0.1, 0.5, 0.9]
    )

    tc = dca.typecurve
    oil_params = dca.tc_params[dca.tc_params["phase"] == "OIL"]
    t_min = float(tc.index.min())

    for _, row in oil_params.iterrows():
        p = row["probability"]
        series = tc[("OIL", p)].astype(float)
        expected_t0 = float(series.loc[t_min])
        assert row["rate_t0"] == pytest.approx(expected_t0, rel=1e-12)
        assert row["peak_rate"] == pytest.approx(float(series.max()), rel=1e-12)
        assert row["time_to_peak_months"] == pytest.approx(float(series.idxmax()), rel=1e-12)

    # With late peak, at least one prob should have peak after time zero
    assert (oil_params["time_to_peak_months"] > t_min).any()
    late_rows = oil_params[oil_params["time_to_peak_months"] > t_min]
    assert (late_rows["rate_t0"] != late_rows["peak_rate"]).all()


def test_tc_exponential_ramp_prepeak_volume():
    from resaid.dca.decline_curve import decline_curve as DC

    # 3 pre-peak months from 100 at t=1 to 800 at t=4
    # q(1)=100, q(2)=100*(8)^(1/3), q(3)=100*(8)^(2/3)
    vol = DC._tc_exponential_ramp_prepeak_volume(100.0, 800.0, 1.0, 4.0)
    expected = 100.0 + 100.0 * (8.0 ** (1.0 / 3.0)) + 100.0 * (8.0 ** (2.0 / 3.0))
    assert vol == pytest.approx(expected, rel=1e-12)

    assert DC._tc_exponential_ramp_prepeak_volume(100.0, 800.0, 4.0, 4.0) == 0.0

    t = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    q = np.array([100.0, 200.0, 400.0, 800.0, 100.0])  # sum=1600
    target = DC._tc_postpeak_eur_target(t, q, 100.0, 800.0, 4.0)
    assert target == pytest.approx(1600.0 - expected, rel=1e-12)


def test_tc_well_eur_targets_from_oneline(combined_dca_dataframe: pd.DataFrame):
    dca = decline_curve()
    dca.three_phase_mode = True
    dca.dataframe = combined_dca_dataframe
    dca.date_col = "DATE"
    dca.phase_col = "PHASE"
    dca.uid_col = "WELL_ID"
    dca.oil_col = "OIL"
    dca.gas_col = "GAS"
    dca.water_col = "WATER"
    dca.run_DCA()
    dca.generate_oneline(denormalize=True, num_months=120)

    targets = dca._tc_well_eur_targets("OIL", [0.1, 0.5, 0.9])
    oil = dca._oneline["OIL"]
    oil = oil[np.isfinite(oil) & (oil > 0)]
    assert targets[0.5] == pytest.approx(float(oil.quantile(0.5)), rel=1e-12)
    assert targets["mean"] == pytest.approx(float(oil.mean()), rel=1e-12)


@pytest.mark.parametrize("three_phase_mode", [True, False])
def test_tc_params_eur_matches_well_eur_quantiles(
    combined_dca_dataframe: pd.DataFrame, three_phase_mode: bool
):
    """Rebuilt tc_params volume (peak_rate + adjusted di) matches oneline EUR quantiles."""
    from resaid.dca.solver import decline_solver

    num_months = 120
    prob_levels = [0.1, 0.5, 0.9]

    dca = decline_curve()
    dca.three_phase_mode = three_phase_mode
    dca.dataframe = combined_dca_dataframe
    dca.date_col = "DATE"
    dca.phase_col = "PHASE"
    dca.uid_col = "WELL_ID"
    dca.oil_col = "OIL"
    dca.gas_col = "GAS"
    dca.water_col = "WATER"

    dca.run_DCA()
    dca.generate_flowstream(denormalize=True, num_months=num_months)
    dca.generate_oneline(denormalize=True, num_months=num_months)
    dca.generate_typecurve(
        denormalize=True,
        return_params=True,
        num_months=num_months,
        prob_levels=prob_levels,
    )

    assert not dca.tc_params.empty
    phases = ["OIL", "GAS", "WATER"] if three_phase_mode else ["OIL", "GAS"]

    for phase in phases:
        phase_params = dca.tc_params[dca.tc_params["phase"] == phase]
        assert not phase_params.empty
        well_series = pd.to_numeric(dca._oneline[phase], errors="coerce")
        well_series = well_series[np.isfinite(well_series) & (well_series > 0)]
        assert not well_series.empty

        for _, row in phase_params.iterrows():
            prob = row["probability"]
            peak = float(row["peak_rate"])
            rate_t0 = float(row["rate_t0"])
            peak_t = float(row["time_to_peak_months"])
            di = float(row["nominal_initial_monthly_decline"])
            b = float(row["matched_b_factor"])
            if not (np.isfinite(peak) and peak > 0 and np.isfinite(di) and di > 0 and np.isfinite(b)):
                continue

            t_start = 1.0
            prepeak = decline_curve._tc_exponential_ramp_prepeak_volume(
                rate_t0, peak, t_start, peak_t
            )
            remaining = max(int(num_months) - int(peak_t) if np.isfinite(peak_t) else 0, 12)
            solver = decline_solver(
                qi=peak,
                qf=None,
                de=di,
                dmin=dca.MIN_DECLINE_RATE,
                b=b,
                eur=None,
                t_max=remaining,
            )
            _, _, _, _, post_eur, _, delta = solver.solve()
            reconstructed = float(prepeak) + float(post_eur)

            if prob == "mean":
                expected = float(well_series.mean())
            else:
                expected = float(well_series.quantile(float(prob)))

            assert reconstructed == pytest.approx(expected, rel=0.05), (
                f"phase={phase} prob={prob}: reconstructed={reconstructed}, "
                f"expected={expected}, delta={delta}"
            )


def test_typecurve_p90_decline_not_degenerate():
    """P90 oil TC decline should fit from peak forward, not blow up di."""
    raw = pd.read_csv("ignore_samples/test_data_raw.csv")
    raw["ProducingMonth"] = pd.to_datetime(raw["ProducingMonth"])
    raw = raw.rename(
        columns={
            "Oil": "LiquidsProd_BBL",
            "Gas": "GasProd_MCF",
            "Water": "WaterProd_BBL",
            "Lateral Length": "LateralLength_FT",
        }
    )
    raw["MAJOR"] = "OIL"

    dca = decline_curve()
    dca.backup_decline = True
    dca.STANDARD_LENGTH = 10000
    dca.DEFAULT_B = 0.99
    dca.dataframe = raw
    dca.date_col = "ProducingMonth"
    dca.phase_col = "MAJOR"
    dca.length_col = "LateralLength_FT"
    dca.uid_col = "API_UWI"
    dca.oil_col = "LiquidsProd_BBL"
    dca.gas_col = "GasProd_MCF"
    dca.water_col = "WaterProd_BBL"
    dca.min_h_b = 0.7
    dca.max_h_b = 1.2
    dca.OUTLIER_CORRECTION = False
    dca.three_phase_mode = True
    dca.generate_typecurve(return_params=True, num_months=120)

    oil = dca.tc_params[dca.tc_params["phase"] == "OIL"]
    p90 = oil[oil["probability"] == 0.9].iloc[0]
    assert p90["time_to_peak_months"] >= 1
    assert p90["nominal_initial_monthly_decline"] < 1.0
    assert p90["secant_effective_decline_pct"] < 99.0
    assert p90["peak_rate"] > p90["rate_t0"]
