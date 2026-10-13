"""
Decline curve parameter solver (`decline_solver`).

This module is part of the ``resaid.dca`` package; import from ``resaid.dca`` or ``resaid``.
"""


import numpy as np
from scipy.optimize import minimize, minimize_scalar

from .._strict import StrictAttributes
from ..dca_constants import DEFAULT_SOLVER_T_MAX_MONTHS
from .decline_curve import decline_curve

# One shared engine for Arps integration — avoids constructing ``decline_curve``
# (file handles, etc.) on every ``decline_solver()`` in tight loops.
_SHARED_L_DCA = None


def _shared_l_dca():
    global _SHARED_L_DCA
    if _SHARED_L_DCA is None:
        _SHARED_L_DCA = decline_curve()
    return _SHARED_L_DCA

# Per-variable box constraints for ``minimize`` (physically plausible DCA ranges).
_SOLVER_VAR_BOUNDS = {
    "qi": (1e-30, 1e25),
    "de": (1e-12, 50.0),
    "eur": (1e-6, 1e20),
    "qf": (1e-12, 1e25),
    "t_max": (1.0, 1e6),
}

# ``solve`` sets its warning flag when |cumulative - EUR| exceeds
# max(_SOLVER_ABS_TOL, _SOLVER_REL_TOL * EUR, qf).
_SOLVER_ABS_TOL = 1e-5
_SOLVER_REL_TOL = 1e-4

# Coarse log-spaced grid size used to bracket single-variable solves.
_SOLVER_LOG_GRID_POINTS = 41


class decline_solver(StrictAttributes):
    """
    Decline curve parameter solver for optimization problems.
    
    This class solves for missing decline curve parameters given constraints
    on initial rate, final rate, decline rate, b-factor, EUR, and time horizon.
    
    Attributes:
        qi: Initial production rate
        qf: Final production rate
        de: Decline rate
        dmin: Terminal (minimum) monthly decline rate used when integrating the
            Arps curve. Defaults to ``decline_curve.MIN_DECLINE_RATE``.
        b: Arps b-factor
        eur: Estimated ultimate recovery
        t_max: Maximum time horizon (months). If omitted when solving, defaults to
            ``DEFAULT_SOLVER_T_MAX_MONTHS`` from ``resaid.dca_constants``.
    """

    def __init__(self, qi=None, qf=None, de=None, dmin=None, b=None, eur=None, t_max=None, l_dca=None):
        self.l_dca = l_dca if l_dca is not None else _shared_l_dca()
        self.qi = qi
        self.qf = qf
        self.de = de
        # Terminal decline used when integrating the Arps curve (monthly, nominal).
        self.dmin = float(dmin) if dmin is not None else float(self.l_dca.MIN_DECLINE_RATE)
        self.b = b
        self.eur = eur
        self.t_max = t_max

        self.l_qf = qf
        self.l_t_max = t_max
        self.delta = 0.0
        
        self.variables_to_solve = []
        self._t_range = None
        self._t_range_n = None
        self._given: tuple = ()

    _PARAMETERS = ("qi", "qf", "de", "eur", "t_max", "b")

    def _need(self, name: str) -> float:
        """Value of parameter ``name`` as a float; raises ``ValueError`` if it is unset."""
        value = getattr(self, name)
        if value is None:
            given_names = self._given or tuple(
                n for n in self._PARAMETERS if getattr(self, n) is not None
            )
            given = ", ".join(given_names) or "none"
            raise ValueError(
                f"decline_solver needs {name!r} to solve with the given inputs "
                f"(given: {given}). Provide b and enough of qi, qf, de, eur and t_max "
                "to determine the curve."
            )
        return float(value)

    def determine_solve(self):
        """
        Determine which variables need to be solved based on provided parameters.
        
        Uses conditional logic to identify missing parameters and sets initial estimates
        for the optimization solver.
        """
        self._given = tuple(n for n in self._PARAMETERS if getattr(self, n) is not None)

        # Check which parameters are missing and set up initial estimates
        if self.qi is None and self.qf is None:
            self.variables_to_solve = ['qi']
            self.qi = self._need('de') * self._need('eur') / 2
            self.qf = 1
        elif self.qi is None and self.de is None:
            self.variables_to_solve = ['qi', 'de']
            # Set initial estimates for both variables
            self.qi = self._need('qf') + self._need('dmin') * self._need('eur')
            self.de = self._need('dmin')
        elif self.qi is None and self.eur is None:
            self.variables_to_solve = ['qi', 'eur']
            # Set initial estimates for both variables
            self.qi = self._need('qf') * 2  # Reasonable initial guess
            self.eur = self._need('qi') * 100  # Reasonable initial guess
        elif self.qi is None and self.t_max is None:
            self.variables_to_solve = ['qi']
            self.qi = self._need('qf') + self._need('de') * self._need('eur')
            self.t_max = DEFAULT_SOLVER_T_MAX_MONTHS
        elif self.t_max is None and self.qf is None:
            self.variables_to_solve = ['qf']
            self.qf = max(self._need('qi') - self._need('de') * self._need('eur'), 1)
            self.t_max = DEFAULT_SOLVER_T_MAX_MONTHS
        elif self.t_max is None and self.de is None:
            self.variables_to_solve = ['de']
            self.de = (self._need('qi') - self._need('qf')) / self._need('eur')
            self.t_max = DEFAULT_SOLVER_T_MAX_MONTHS
        elif self.t_max is None and self.eur is None:
            self.variables_to_solve = ['eur']
            self.t_max = DEFAULT_SOLVER_T_MAX_MONTHS
            self.eur = (self._need('qi') - self._need('qf')) / self._need('de')
        elif self.qf is None and self.de is None:
            self.variables_to_solve = ['de']
            self.de = self._need('qi') / self._need('eur')
            self.qf = 1
        elif self.qf is None and self.eur is None:
            self.variables_to_solve = ['eur']
            self.eur = self._need('qi') / self._need('de')
            self.qf = 1
        elif self.de is None and self.eur is None:
            self.variables_to_solve = ['de', 'eur']
            # Set initial estimates for both variables
            self.de = self._need('dmin')
            self.eur = self._need('qi') * self._need('t_max')
        # Handle cases where only one parameter is missing
        elif self.qi is None:
            self.variables_to_solve = ['qi']
            self.qi = self._need('qf') + self._need('de') * self._need('eur')
        elif self.qf is None:
            self.variables_to_solve = ['qf']
            self.qf = max(self._need('qi') - self._need('de') * self._need('eur'), 1)
        elif self.de is None:
            self.variables_to_solve = ['de']
            self.de = (self._need('qi') - self._need('qf')) / self._need('eur')
        elif self.eur is None:
            self.variables_to_solve = ['eur']
            self.eur = (self._need('qi') - self._need('qf')) / self._need('de')
        elif self.t_max is None:
            self.variables_to_solve = ['t_max']
            self.t_max = DEFAULT_SOLVER_T_MAX_MONTHS
        else:
            self.variables_to_solve = []
        
        # Set default t_max if still None
        if self.t_max is None:
            self.t_max = DEFAULT_SOLVER_T_MAX_MONTHS


    def dca_delta(self, vars_to_solve):
        """
        Calculate the objective function for parameter optimization.
        
        Args:
            vars_to_solve: Sequence of parameter values to evaluate (same order as
                ``variables_to_solve``).
            
        Returns:
            float: Absolute difference between cumulative Arps production and target EUR.
        """
        vec = np.atleast_1d(np.asarray(vars_to_solve, dtype=float)).ravel()
        for var_name, var_value in zip(self.variables_to_solve, vec):
            setattr(self, var_name, float(var_value))

        tn = int(self._need("t_max"))
        if self._t_range_n != tn or self._t_range is None:
            self._t_range = np.arange(tn, dtype=float)
            self._t_range_n = tn
        t_range = self._t_range

        dca_array = np.asarray(
            self.l_dca.arps_decline(
                t_range, self._need("qi"), self._need("de"), self._need("b"), 0, dmin=self.dmin
            ),
            dtype=float,
        )
        dca_array = np.where(dca_array > self._need("qf"), dca_array, 0)

        self.l_t_max = len(np.where(dca_array > 0)[0])
        if self.l_t_max > 0:
            # Calculate cumulative production and compare with EUR
            cumulative_production = np.sum(dca_array)
            self.delta = float(abs(cumulative_production - self._need("eur")))
        else:
            self.delta = 1e10
            
        return self.delta

    def solve(self):
        """
        Solve for optimal decline curve parameters.
        
        Returns:
            tuple: (qi, t_max, qf, de, eur, warning_flag, delta). ``warning_flag``
            is True when the solved curve misses the EUR target by more than a
            small relative tolerance (e.g. the target is unreachable).
        """
        self.determine_solve()
        
        if len(self.variables_to_solve) == 0:
            return self._result(False)

        x0 = np.array([float(getattr(self, var)) for var in self.variables_to_solve], dtype=float)
        bounds = [_SOLVER_VAR_BOUNDS[v] for v in self.variables_to_solve]
        lb = np.array([b[0] for b in bounds], dtype=float)
        ub = np.array([b[1] for b in bounds], dtype=float)
        x0 = np.clip(x0, lb, ub)

        def objective(vec):
            return float(self.dca_delta(vec))

        try:
            if len(self.variables_to_solve) == 1:
                lo, hi = bounds[0]
                if not (np.isfinite(lo) and np.isfinite(hi) and 0 < lo < hi):
                    result = x0.copy()
                else:
                    # Bounds span many decades, so search in log space: a coarse grid
                    # (plus the initial guess) brackets the minimum, then Brent refines.
                    # A linear-scale search probes only the top of the range, where
                    # every curve looks alike, and can stall at the upper bound.
                    def objective_log(g):
                        return float(self.dca_delta(np.array([float(np.exp(g))])))

                    grid = np.linspace(np.log(lo), np.log(hi), _SOLVER_LOG_GRID_POINTS)
                    if np.isfinite(x0[0]) and x0[0] > 0:
                        grid = np.unique(np.append(grid, np.log(x0[0])))
                    vals = np.array([objective_log(g) for g in grid])
                    i_best = int(np.argmin(vals))
                    g_lo = grid[max(i_best - 1, 0)]
                    g_hi = grid[min(i_best + 1, len(grid) - 1)]
                    g_best = grid[i_best]
                    if g_lo < g_hi:
                        res_sc = minimize_scalar(
                            objective_log,
                            bounds=(g_lo, g_hi),
                            method="bounded",
                            options={"maxiter": 200, "xatol": 1e-12},
                        )
                        if float(res_sc.fun) <= vals[i_best]:
                            g_best = float(res_sc.x)
                    result = np.array(
                        [float(np.clip(np.exp(g_best), lo, hi))], dtype=float
                    )
            else:
                res = minimize(
                    objective,
                    x0,
                    method="L-BFGS-B",
                    bounds=bounds,
                    options={"ftol": 1e-9, "maxiter": 400},
                )
                result = np.atleast_1d(res.x).astype(float, copy=False).ravel()
                result = np.clip(result, lb, ub)
        except Exception:  # noqa: BLE001 - optimizer failure falls back to the initial guess
            result = x0.copy()

        self.dca_delta(result)

        # Judge the solve by its residual rather than optimizer status: bounded
        # optimizers report success when pinned at a bound on an unreachable EUR,
        # and L-BFGS-B may report failure on a tight ftol with a negligible residual.
        # Volumes are monthly sums truncated at ``qf``, so cumulative moves in steps
        # of about one month at the economic limit; residuals below that are noise.
        qf_step = float(self.qf) if self.qf is not None and np.isfinite(self.qf) else 0.0
        tol = max(_SOLVER_ABS_TOL, _SOLVER_REL_TOL * abs(self._need("eur")), qf_step)
        warning_flag = bool(not np.isfinite(self.delta) or self.delta > tol)

        if self.qf is None:
            self.qf = self.l_qf
        return self._result(warning_flag)

    def _result(self, warning_flag: bool) -> tuple[float, float, float, float, float, bool, float]:
        """Solved parameters as floats: (qi, t_max, qf, de, eur, warning_flag, delta)."""
        return (
            self._need("qi"),
            self._need("t_max"),
            self._need("qf"),
            self._need("de"),
            self._need("eur"),
            bool(warning_flag),
            float(self.delta),
        )


