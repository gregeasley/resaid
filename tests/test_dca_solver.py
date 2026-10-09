"""``decline_solver`` — same numeric scenario as ``dca.py`` ``__main__`` demo."""

from __future__ import annotations

import math

import numpy as np

from resaid.dca import decline_curve, decline_solver


def test_decline_solver_smoke_main_example():
    """End-to-end solve returns a full tuple whose curve reproduces the EUR."""
    dmin = 0.01 / 12
    solver = decline_solver(
        qi=16805,
        qf=3000,
        eur=1_104_336.17516371,
        b=0.01,
        dmin=dmin,
    )
    qi, t_max, qf, de, eur, warning_flag, delta = solver.solve()

    assert isinstance(warning_flag, bool)
    assert isinstance(delta, (int, float)) and not math.isnan(delta)
    for val in (qi, t_max, qf, de, eur):
        assert isinstance(val, (int, float))
        assert math.isfinite(float(val))

    assert warning_flag is False
    q = decline_curve().arps_decline(np.arange(int(t_max), dtype=float), qi, de, 0.01, 0, dmin=dmin)
    cum = float(np.sum(np.where(q > qf, q, 0.0)))
    # Within one month of volume at the economic limit.
    assert abs(cum - eur) <= qf
