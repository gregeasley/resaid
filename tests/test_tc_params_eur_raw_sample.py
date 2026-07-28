"""Validate tc_params EUR against well P10/P50/P90 on ignore_samples/test_data_raw.csv."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from resaid.dca import decline_curve

RAW_PATH = Path("ignore_samples/test_data_raw.csv")


@pytest.fixture(scope="module")
def raw_dca_bundle():
    if not RAW_PATH.exists():
        pytest.skip(f"missing {RAW_PATH}")

    raw = pd.read_csv(RAW_PATH)
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

    num_months = 120
    prob_levels = [0.1, 0.5, 0.9]

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

    dca.run_DCA()
    dca.generate_flowstream(denormalize=True, num_months=num_months)
    dca.generate_oneline(denormalize=True, num_months=num_months)
    dca.generate_typecurve(
        denormalize=True,
        return_params=True,
        num_months=num_months,
        prob_levels=prob_levels,
    )
    return dca, num_months, prob_levels


def _reconstruct_eur(dca: decline_curve, row: pd.Series, num_months: int) -> float:
    return float(
        dca._tc_curve_eur_from_params(
            row["peak_rate"],
            row["rate_t0"],
            row["time_to_peak_months"],
            row["nominal_initial_monthly_decline"],
            row["matched_b_factor"],
            num_months,
        )
    )


def test_raw_sample_tc_params_match_empirical_well_eur_quantiles(raw_dca_bundle):
    """
    Rebuilt tc_params volumes must match sample P10/P50/P90 (and mean) of well EURs.

    Targets are empirical oneline quantiles (the P10/P50/P90 of the well EUR set),
    not a parametric lognormal fit to those EURs.
    """
    dca, num_months, _prob_levels = raw_dca_bundle
    assert not dca.tc_params.empty

    for phase in ["OIL", "GAS", "WATER"]:
        well_series = pd.to_numeric(dca._oneline[phase], errors="coerce")
        well_series = well_series[np.isfinite(well_series) & (well_series > 0)]
        if well_series.empty:
            continue

        phase_params = dca.tc_params[dca.tc_params["phase"] == phase]
        assert not phase_params.empty

        for _, row in phase_params.iterrows():
            peak = float(row["peak_rate"])
            if not (np.isfinite(peak) and peak > 0):
                # Rate-quantile profile can be all zeros (e.g. WATER P10 with sparse water).
                continue

            prob = row["probability"]
            if prob == "mean":
                expected = float(well_series.mean())
            else:
                expected = float(well_series.quantile(float(prob)))

            reconstructed = _reconstruct_eur(dca, row, num_months)
            assert reconstructed == pytest.approx(expected, rel=1e-6, abs=1e-3), (
                f"{phase} prob={prob}: reconstructed={reconstructed}, expected={expected}"
            )
            assert "curve_eur" in row.index
            assert row["curve_eur"] == pytest.approx(reconstructed, rel=1e-12)
            assert row["standard_length"] == dca.STANDARD_LENGTH


def test_raw_sample_empirical_vs_lognormal_targets_differ(raw_dca_bundle):
    """Document that parametric lognormal P10/P50/P90 != sample quantiles on this set."""
    from scipy.stats import norm

    dca, _num_months, prob_levels = raw_dca_bundle
    oil = pd.to_numeric(dca._oneline["OIL"], errors="coerce")
    oil = oil[np.isfinite(oil) & (oil > 0)].astype(float)
    assert len(oil) >= 3

    log_oil = np.log(oil)
    mu = float(log_oil.mean())
    sigma = float(log_oil.std(ddof=1))
    assert sigma > 0

    # At least one probability should differ materially between methods on this sample.
    diffs = []
    for p in prob_levels:
        emp = float(oil.quantile(p))
        ln = float(np.exp(mu + norm.ppf(p) * sigma))
        diffs.append(abs(emp - ln) / emp)
    assert max(diffs) > 0.05
