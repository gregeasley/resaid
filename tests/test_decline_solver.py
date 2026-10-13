"""Tests for ``decline_solver``: solved parameters must reproduce the EUR target."""

from __future__ import annotations

import numpy as np
import pytest

from resaid.dca import decline_curve, decline_solver


def _cumulative(qi, de, b, dmin, qf, t_max):
    """Independent re-integration of the solved curve (same convention as the solver)."""
    q = decline_curve().arps_decline(np.arange(int(t_max), dtype=float), qi, de, b, 0, dmin=dmin)
    return float(np.sum(np.where(q > qf, q, 0.0)))


def _assert_eur_matched(qi, t_max, qf, de, eur, warning, delta, *, b, dmin):
    assert not warning, f"solver flagged a miss: delta={delta}"
    cum = _cumulative(qi, de, b, dmin, qf, t_max)
    assert abs(cum - eur) == pytest.approx(delta, abs=1e-6)
    # Residual within one month at the economic limit, or tiny relative error.
    assert delta <= max(qf, 1e-4 * eur)


DMIN = 0.01 / 12


@pytest.mark.parametrize(
    "kwargs, solved",
    [
        ({"qf": 1000, "de": 0.1 / 12, "eur": 50000, "b": 1.0}, ["qi"]),
        ({"de": 0.15 / 12, "eur": 75000, "b": 0.8}, ["qi"]),
        ({"qf": 2000, "de": 0.2 / 12, "b": 0.9}, ["qi", "eur"]),
        ({"qf": 5000, "de": 0.05 / 12, "eur": 1_000_000, "b": 0.8}, ["qi"]),
        ({"qi": 1000, "qf": 1, "eur": 100_000, "b": 1.0, "t_max": 600}, ["de"]),
        ({"qi": 1000, "qf": 1, "de": 0.05, "b": 1.0}, ["eur"]),
    ],
)
def test_solves_match_eur(kwargs, solved):
    solver = decline_solver(dmin=DMIN, **kwargs)
    qi, t_max, qf, de, eur, warning, delta = solver.solve()

    assert solver.variables_to_solve == solved
    out = {"qi": qi, "t_max": t_max, "qf": qf, "de": de, "eur": eur}
    for name, value in kwargs.items():
        if name in out:
            assert out[name] == pytest.approx(value), f"{name} should be unchanged"
    assert qi > 0 and de > 0 and eur > 0
    _assert_eur_matched(qi, t_max, qf, de, eur, warning, delta, b=kwargs["b"], dmin=DMIN)


def test_two_variable_solve_qi_de():
    solver = decline_solver(qf=500, eur=30000, b=1.2, dmin=DMIN)
    qi, t_max, qf, de, eur, warning, delta = solver.solve()
    assert solver.variables_to_solve == ["qi", "de"]
    assert qf == pytest.approx(500) and eur == pytest.approx(30000)
    assert qi > qf and de > 0
    _assert_eur_matched(qi, t_max, qf, de, eur, warning, delta, b=1.2, dmin=DMIN)


def test_all_parameters_provided_returns_inputs():
    solver = decline_solver(qi=5000, qf=100, de=0.12 / 12, eur=100000, b=1.1, dmin=DMIN, t_max=600)
    qi, t_max, qf, de, eur, warning, _delta = solver.solve()
    assert (qi, t_max, qf, de, eur) == pytest.approx((5000, 600, 100, 0.01, 100000))
    assert warning is False


def test_unreachable_eur_sets_warning():
    """Max volume at de -> 0 over 600 months is ~147k; 200k cannot be matched."""
    solver = decline_solver(qi=1000, eur=200_000, b=1.0, t_max=600)
    _qi, _t_max, _qf, _de, eur, warning, delta = solver.solve()
    assert warning is True
    assert delta > 0.1 * eur


def test_solver_main_example_converges():
    """
    Regression: this README example used to stall at the de upper bound (50/month)
    with a residual ~10x the EUR and no warning.
    """
    solver = decline_solver(qi=16805, qf=3000, eur=1_104_336.17516371, b=0.01, dmin=DMIN)
    qi, t_max, qf, de, eur, warning, delta = solver.solve()
    assert solver.variables_to_solve == ["de"]
    assert 0.005 < de < 0.05
    _assert_eur_matched(qi, t_max, qf, de, eur, warning, delta, b=0.01, dmin=DMIN)


def test_dmin_changes_solution():
    """Regression: ``dmin`` used to be ignored when integrating the curve."""
    common = {"qi": 1000, "qf": 1, "eur": 60_000, "b": 1.2, "t_max": 1200}
    de_low = decline_solver(dmin=0.01 / 12, **common).solve()[3]
    de_high = decline_solver(dmin=0.10 / 12, **common).solve()[3]
    # A steeper terminal decline removes tail volume, so the initial decline must be
    # shallower to reach the same EUR.
    assert de_high < de_low
    for dmin, de in ((0.01 / 12, de_low), (0.10 / 12, de_high)):
        cum = _cumulative(1000, de, 1.2, dmin, 1, 1200)
        assert cum == pytest.approx(60_000, rel=1e-4)


def test_default_dmin_is_min_decline_rate():
    solver = decline_solver(qi=1000, qf=1, eur=60_000, b=1.2, t_max=1200)
    assert solver.dmin == pytest.approx(decline_curve().MIN_DECLINE_RATE)
    # Branches that seed initial guesses from dmin must not fail when it is omitted.
    decline_solver(qf=500, eur=30000, b=1.2).solve()
    decline_solver(qi=1000, qf=10, b=1.0, t_max=600).solve()


def test_solver_is_repeatable():
    results = [
        decline_solver(qf=1500, de=0.08 / 12, eur=50000, b=1.0, dmin=DMIN).solve()
        for _ in range(3)
    ]
    for r in results[1:]:
        assert r == pytest.approx(results[0])


def test_dca_delta_is_absolute_eur_residual():
    solver = decline_solver(qi=3000, qf=100, de=0.1 / 12, eur=50000, b=1.0, dmin=DMIN, t_max=1200)
    solver.variables_to_solve = ["qi", "de"]
    delta = solver.dca_delta([3000, 0.1 / 12])
    cum = _cumulative(3000, 0.1 / 12, 1.0, DMIN, 100, 1200)
    assert delta == pytest.approx(abs(cum - 50000))
