"""Economics: ``npv_calc`` and minimal ``well_econ`` flowstream."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from resaid.econ import npv_calc, well_econ


def test_npv_calc_constant_cashflow():
    cf = np.array([-100.0, 30.0, 30.0, 30.0, 30.0])
    calc = npv_calc(cf)
    npv0 = calc.get_npv(0.0)
    assert np.isclose(npv0, np.sum(cf))


def test_npv_calc_irr_simple_positive():
    # Upfront cost then uniform positive returns — IRR should be positive (annualized)
    cf = np.array([-1000.0, 400.0, 400.0, 400.0, 400.0])
    irr = npv_calc(cf).get_irr()
    assert irr > 0


def test_well_econ_minimal_flowstream():
    n = 12
    flow = pd.DataFrame(
        {
            "UWI": ["W1"] * n,
            "T_INDEX": np.arange(1, n + 1),
            "OIL": np.linspace(100.0, 85.0, n),
            "GAS": np.linspace(400.0, 350.0, n),
            "WATER": np.linspace(10.0, 12.0, n),
            "MAJOR": ["OIL"] * n,
        }
    )
    econ = well_econ(verbose=False)
    econ.flowstreams = flow
    econ.flowstream_uwi_col = "UWI"
    econ.flowstream_t_index = "T_INDEX"
    econ.oil_pri = 60.0
    econ.gas_pri = 2.5
    econ.discount_rate = 0.08 / 12
    econ.royalty = 0.1875

    out = econ.well_flowstream("W1")
    assert not out.empty
    assert "revenue" in out.columns
    assert "cf" in out.columns
    assert "dcf" in out.columns
    assert (out["revenue"] >= 0).all()
