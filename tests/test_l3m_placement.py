"""The L3M adjustment places the last-three-month average at the midpoint of those months."""

from __future__ import annotations

import numpy as np
import pytest

from resaid.dca import decline_curve


@pytest.fixture
def dca():
    d = decline_curve()
    d.STAT_FILE = None
    return d


@pytest.mark.parametrize("factor", [0.7, 1.4], ids=["bulk_shift_down", "solved_up"])
def test_l3m_average_is_matched_at_the_midpoint(dca, factor):
    qi, di, b, t0 = 10000.0, 0.08, 1.1, 0.0
    x = np.arange(36, dtype=float)
    y = dca.arps_decline(x, qi, di, b, t0) * factor
    q_new, di_new = dca._adjust_default_fit_to_recent_l3m(qi, di, b, t0, x, y)
    t_mid = float(np.mean(x[-3:]))                        # month 34, not the last month (35)
    q_mid = dca._arps_rate_from_tau(q_new, di_new, b, t_mid - t0)
    assert q_mid == pytest.approx(float(np.mean(y[-3:])), rel=1e-6)


def test_zero_months_count_in_the_average(dca):
    qi, di, b, t0 = 10000.0, 0.08, 1.1, 0.0
    x = np.arange(36, dtype=float)
    y = dca.arps_decline(x, qi, di, b, t0)
    y[-1] = 0.0                                           # a shut-in month is part of the L3M
    q_new, di_new = dca._adjust_default_fit_to_recent_l3m(qi, di, b, t0, x, y)
    q_mid = dca._arps_rate_from_tau(q_new, di_new, b, float(np.mean(x[-3:])) - t0)
    assert q_mid == pytest.approx(float(np.mean(y[-3:])), rel=1e-6)


@pytest.mark.parametrize("t0", [0.0, 4.0, 9.0])
def test_upside_rejoin_point_is_anchored_to_the_window_start(dca, t0):
    # Equally good fits can place t0 anywhere in the window; the solved upside curve must
    # rejoin the fit as far after the L3M midpoint as the midpoint is after the window start.
    qi, di, b, t_ref = 10000.0, 0.08, 1.1, 0.0
    x = np.arange(36, dtype=float)
    y = dca.arps_decline(x, qi, di, b, t0) * 1.05
    q_new, di_new = dca._adjust_default_fit_to_recent_l3m(qi, di, b, t0, x, y, t_ref=t_ref)
    t_mid = float(np.mean(x[-3:]))
    t_rejoin = 2 * t_mid - t_ref
    assert dca._arps_rate_from_tau(q_new, di_new, b, t_rejoin - t0) == pytest.approx(
        dca._arps_rate_from_tau(qi, di, b, t_rejoin - t0), rel=1e-6
    )
    assert dca._arps_rate_from_tau(q_new, di_new, b, t_mid - t0) == pytest.approx(
        float(np.mean(y[-3:])), rel=1e-6
    )
