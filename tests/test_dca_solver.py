"""``decline_solver`` — same numeric scenario as ``dca.py`` ``__main__`` demo."""

from __future__ import annotations

import math

import pytest

from resaid.dca import decline_solver


def test_decline_solver_smoke_main_example():
    """End-to-end solve returns a full tuple with finite primary outputs."""
    solver = decline_solver(
        qi=16805,
        qf=3000,
        eur=1_104_336.17516371,
        b=0.01,
        dmin=0.01 / 12,
    )
    qi, t_max, qf, de, eur, warning_flag, delta = solver.solve()

    assert isinstance(warning_flag, bool)
    assert isinstance(delta, (int, float)) and not math.isnan(delta)
    for val in (qi, t_max, qf, de, eur):
        assert isinstance(val, (int, float))
        assert math.isfinite(float(val))
