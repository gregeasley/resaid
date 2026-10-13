"""Low-level Arps helpers on ``decline_curve``."""

from __future__ import annotations

import itertools

import numpy as np
import pytest

from resaid.dca import decline_curve


def test_arps_decline_hyperbolic_positive_monotone():
    dca = decline_curve()
    x = np.arange(0, 24, dtype=float)
    qi, di, b, t0 = 100.0, 0.05, 0.5, 0.0
    q = np.asarray(dca.arps_decline(x, qi, di, b, t0), dtype=float)
    assert q.shape == x.shape
    assert np.all(np.isfinite(q))
    assert np.all(q >= 0)
    # Non-increasing after first period (allow flat/numerical tie at tail)
    assert np.all(np.diff(q) <= 1e-6)


def test_arps_decline_zero_qi_returns_zeros():
    dca = decline_curve()
    x = np.arange(0, 10)
    q = np.asarray(dca.arps_decline(x, 0.0, 0.1, 0.5, 0.0))
    assert np.allclose(q, 0.0)


def test_arps_decline_scalar_input_returns_scalar():
    dca = decline_curve()
    q = dca.arps_decline(3.0, 100.0, 0.05, 0.5, 0.0)
    assert isinstance(q, float)
    assert q == pytest.approx(100.0 * (1 + 0.5 * 0.05 * 3) ** (-1 / 0.5))


def test_arps_decline_matches_hyperbolic_formula_before_switch():
    dca = decline_curve()
    qi, di, b, t0 = 500.0, 0.1, 1.2, 2.0
    x = np.arange(2.0, 12.0)
    expected = qi * (1 + b * di * (x - t0)) ** (-1 / b)
    np.testing.assert_allclose(dca.arps_decline(x, qi, di, b, t0), expected, rtol=1e-12)


def test_arps_decline_switches_to_terminal_exponential():
    """Late-life month-over-month ratio equals exp(-dmin) after the switch."""
    dca = decline_curve()
    dmin = dca.MIN_DECLINE_RATE
    qi, di, b, t0 = 1000.0, 0.1, 1.0, 0.0
    t_switch = (di / dmin - 1) / (b * di) + t0
    x = np.arange(0.0, 1200.0)
    q = dca.arps_decline(x, qi, di, b, t0)
    late = x > t_switch + 1
    ratios = q[late][1:] / q[late][:-1]
    np.testing.assert_allclose(ratios, np.exp(-dmin), rtol=1e-12)
    # Before the switch the decline is steeper than terminal.
    early = q[:10]
    assert np.all(early[1:] / early[:-1] < np.exp(-dmin))


def test_arps_decline_low_initial_decline_is_exponential_from_t0():
    """di below the terminal rate: exponential at dmin anchored at (t0, qi)."""
    dca = decline_curve()
    dmin = dca.MIN_DECLINE_RATE
    qi, di, b, t0 = 800.0, dmin / 3, 1.1, 5.0
    x = np.arange(0.0, 60.0)
    q = dca.arps_decline(x, qi, di, b, t0)
    np.testing.assert_allclose(q, qi * np.exp(-dmin * (x - t0)), rtol=1e-12)
    assert dca.arps_decline(t0, qi, di, b, t0) == pytest.approx(qi)


def test_arps_decline_low_initial_decline_respects_t0_shift():
    dca = decline_curve()
    di = dca.MIN_DECLINE_RATE / 2
    x = np.arange(0.0, 40.0)
    q0 = dca.arps_decline(x, 100.0, di, 1.0, 0.0)
    q7 = dca.arps_decline(x + 7.0, 100.0, di, 1.0, 7.0)
    np.testing.assert_allclose(q0, q7, rtol=1e-12)


def test_arps_decline_zero_b_is_exponential_at_di():
    dca = decline_curve()
    qi, di = 1000.0, 0.05
    x = np.arange(0.0, 120.0)
    q = dca.arps_decline(x, qi, di, 0.0, 0.0)
    np.testing.assert_allclose(q, qi * np.exp(-di * x), rtol=1e-12)


def test_arps_decline_dmin_override_controls_terminal_decline():
    dca = decline_curve()
    x = np.arange(0.0, 1200.0)
    args = (1000.0, 0.05, 1.2, 0.0)
    for dmin in (0.01 / 12, 0.08 / 12, 0.3 / 12):
        q = dca.arps_decline(x, *args, dmin=dmin)
        np.testing.assert_allclose(q[-1] / q[-2], np.exp(-dmin), rtol=1e-9)
    # Default matches MIN_DECLINE_RATE.
    np.testing.assert_array_equal(
        dca.arps_decline(x, *args),
        dca.arps_decline(x, *args, dmin=dca.MIN_DECLINE_RATE),
    )
    # Higher terminal decline -> less volume.
    vols = [dca.arps_decline(x, *args, dmin=d).sum() for d in (0.01 / 12, 0.08 / 12, 0.3 / 12)]
    assert vols[0] > vols[1] > vols[2]


def test_arps_decline_zero_dmin_is_pure_hyperbolic():
    dca = decline_curve()
    qi, di, b = 1000.0, 0.05, 1.2
    x = np.arange(0.0, 1200.0)
    q = dca.arps_decline(x, qi, di, b, 0.0, dmin=0.0)
    np.testing.assert_allclose(q, qi * (1 + b * di * x) ** (-1 / b), rtol=1e-12)


def test_arps_decline_steep_low_b_decline_stays_near_zero():
    """
    Regression: for steep di with small b the terminal-switch rate underflows.
    It used to fall back to ``qi`` and produce a flat terminal tail at the
    initial rate, i.e. a huge volume from a near-instant decline.
    """
    dca = decline_curve()
    x = np.arange(0.0, 1200.0)
    q = dca.arps_decline(x, 16805.0, 50.0, 0.01, 0.0)
    assert q[0] == pytest.approx(16805.0)
    assert np.all(q[1:] < 1e-6)
    # Volume must fall as decline steepens.
    vols = [dca.arps_decline(x, 16805.0, d, 0.01, 0.0).sum() for d in (0.01, 0.1, 1.0, 10.0, 50.0)]
    assert all(a > b for a, b in itertools.pairwise(vols))
