"""Full ``decline_curve`` workflow aligned with ``examples/simple_example.py`` and ratio mode."""

from __future__ import annotations

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
