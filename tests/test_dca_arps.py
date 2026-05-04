"""Low-level Arps helpers on ``decline_curve``."""

from __future__ import annotations

import numpy as np

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
