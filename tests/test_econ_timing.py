"""Cashflow timing (start delay, spud to online, economic limit), price inputs and indicators."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import resaid.econ as econ_mod
from resaid.econ import npv_calc, well_econ

MONTHS = 6


def _econ(t_first=1, oil=100.0, opc_t=7.0, start=None, spud=None, capex=None, months=MONTHS):
    """One oil well with a flat forecast; T_INDEX starts at 1 like decline_curve flowstreams."""
    e = well_econ()
    e.flowstreams = pd.DataFrame({
        "UWI": "A", "T_INDEX": np.arange(t_first, t_first + months), "MAJOR": "OIL",
        "OIL": oil, "GAS": 0.0, "WATER": 0.0,
    })
    e.flowstream_uwi_col, e.flowstream_t_index = "UWI", "T_INDEX"
    e.discount_rate = 0.0
    e.oil_pri = 50.0
    e.opc_t = opc_t
    header = {"UWI": ["A"]}
    if start is not None:
        header["START"] = [start]
        e.t_start_column = "START"
    if capex is not None:
        header["CAPEX"] = [capex]
        e.capex_col = "CAPEX"
    if len(header) > 1:
        e.header_data = pd.DataFrame(header)
        e.header_uwi_col = "UWI"
    if spud:
        e.spud_to_online = spud
    return e


def _indicators(e: well_econ) -> pd.DataFrame:
    assert e.indicators is not None, "run generate_indicators() first"
    return e.indicators


def test_every_producing_month_is_kept():
    # The economic limit is a row position; it used to be compared with T_INDEX, which
    # starts at 1, so the last producing month was dropped.
    flow = _econ().well_flowstream("A")
    assert flow["OIL"].tolist() == [100.0] * MONTHS
    assert flow["revenue"].sum() == pytest.approx(MONTHS * 100 * 50)


def test_economic_limit_cuts_after_last_positive_month():
    e = _econ()
    flow = e.flowstreams
    assert flow is not None
    flow["OIL"] = [100.0, 100.0, 100.0, 0.1, 0.1, 0.1]  # last three below opc_t
    flow = e.well_flowstream("A")
    assert flow["OIL"].tolist() == [100.0, 100.0, 100.0, 0.0, 0.0, 0.0]


@pytest.mark.parametrize("t_first", [0, 1])
@pytest.mark.parametrize("start, spud", [(0, 3), (2, 0), (2, 3)])
def test_delay_months_have_no_volume_or_expense(t_first, start, spud):
    flow = _econ(t_first=t_first, start=start, spud=spud, capex=1000.0).well_flowstream("A")
    n_delay = start + spud
    assert len(flow) == n_delay + MONTHS
    # T_INDEX stays contiguous from the flowstream's first index.
    assert flow["T_INDEX"].tolist() == list(range(t_first, t_first + n_delay + MONTHS))
    assert flow["OIL"].tolist() == [0.0] * n_delay + [100.0] * MONTHS
    assert flow["expense"].tolist() == [0.0] * n_delay + [7.0] * MONTHS
    assert flow["fixed_expense"].tolist() == [0.0] * n_delay + [7.0] * MONTHS
    # Capex is charged at spud: after the start delay, before spud_to_online.
    assert flow["capex"].tolist() == [0.0] * start + [1000.0] + [0.0] * (n_delay + MONTHS - start - 1)


def test_start_delay_discounts_the_well():
    def dcf(start):
        e = _econ(start=start, capex=1000.0)
        e.discount_rate = 0.01
        e.generate_indicators()
        return _indicators(e)["DCF"].iloc[0]

    assert dcf(12) == pytest.approx(dcf(0) / 1.01**12)


@pytest.mark.parametrize(
    "prices", [[60.0, 55.0], (60.0, 55.0), np.array([60.0, 55.0]), pd.Series([60.0, 55.0])]
)
def test_price_sequences(prices):
    e = _econ()
    e.oil_pri = prices
    e.oil_diff = -2.0
    np.testing.assert_allclose(e.generate_oil_price(np.arange(4)), [58.0, 53.0, 53.0, 53.0])
    e.gas_pri = prices
    np.testing.assert_allclose(e.generate_gas_price(np.arange(1)), [60.0])


def test_scalar_and_numpy_scalar_prices():
    e = _econ()
    e.oil_pri = np.float64(70.0)
    np.testing.assert_allclose(e.generate_oil_price(np.arange(3)), [70.0] * 3)


def test_payout_distinguishes_first_month_from_never():
    pays_now = _econ()  # no capex: positive from the first month
    pays_now.generate_indicators()
    assert _indicators(pays_now)["PAYOUT"].iloc[0] == 0

    later = _econ(capex=50_000.0)  # 5,000 - 7 per month: pays out in month 10
    later.flowstreams = _econ(months=24).flowstreams
    later.generate_indicators()
    assert _indicators(later)["PAYOUT"].iloc[0] == 10

    never = _econ(capex=1e9)
    never.generate_indicators()
    assert np.isnan(_indicators(never)["PAYOUT"].iloc[0])


def test_irr_without_investment_is_nan():
    e = _econ()  # no capex: every month positive, IRR undefined
    e.generate_indicators()
    assert np.isnan(_indicators(e)["IRR"].iloc[0])


def test_irr_falls_back_when_newton_fails(monkeypatch):
    cf = np.array([-100.0] + [10.0] * 24)
    expected = npv_calc(cf).get_irr()

    def failing_newton(*args, **kwargs):
        raise RuntimeError("Failed to converge")

    monkeypatch.setattr(econ_mod, "newton", failing_newton)
    assert npv_calc(cf).get_irr() == pytest.approx(expected, rel=1e-6)


def test_irr_negative_return_is_zero():
    assert npv_calc(np.array([-100.0, 40.0, 40.0])).get_irr() == 0
