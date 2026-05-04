"""
Decline curve parameter solver (`decline_solver`).

This module is part of the ``resaid.dca`` package; import from ``resaid.dca`` or ``resaid``.
"""

import numpy as np
from scipy.optimize import minimize, minimize_scalar

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


class decline_solver:
    """
    Decline curve parameter solver for optimization problems.
    
    This class solves for missing decline curve parameters given constraints
    on initial rate, final rate, decline rate, b-factor, EUR, and time horizon.
    
    Attributes:
        qi: Initial production rate
        qf: Final production rate
        de: Decline rate
        dmin: Minimum decline rate
        b: Arps b-factor
        eur: Estimated ultimate recovery
        t_max: Maximum time horizon (months). If omitted when solving, defaults to
            ``DEFAULT_SOLVER_T_MAX_MONTHS`` from ``resaid.dca_constants``.
    """

    def __init__(self, qi=None, qf=None, de=None, dmin=None, b=None, eur=None, t_max=None, l_dca=None):
        self.qi = qi
        self.qf = qf
        self.de = de
        self.dmin = dmin
        self.b = b
        self.eur = eur
        self.t_max = t_max

        self.l_qf = qf
        self.l_t_max = t_max
        self.delta = 0
        
        self.variables_to_solve = []
        self.l_dca = l_dca if l_dca is not None else _shared_l_dca()
        self._t_range = None
        self._t_range_n = None

    def determine_solve(self):
        """
        Determine which variables need to be solved based on provided parameters.
        
        Uses conditional logic to identify missing parameters and sets initial estimates
        for the optimization solver.
        """
        # Check which parameters are missing and set up initial estimates
        if self.qi is None and self.qf is None:
            self.variables_to_solve = ['qi']
            self.qi = self.de * self.eur / 2
            self.qf = 1
        elif self.qi is None and self.de is None:
            self.variables_to_solve = ['qi', 'de']
            # Set initial estimates for both variables
            self.qi = self.qf + self.dmin * self.eur
            self.de = self.dmin
        elif self.qi is None and self.eur is None:
            self.variables_to_solve = ['qi', 'eur']
            # Set initial estimates for both variables
            self.qi = self.qf * 2  # Reasonable initial guess
            self.eur = self.qi * 100  # Reasonable initial guess
        elif self.qi is None and self.t_max is None:
            self.variables_to_solve = ['qi']
            self.qi = self.qf + self.de * self.eur
            self.t_max = DEFAULT_SOLVER_T_MAX_MONTHS
        elif self.t_max is None and self.qf is None:
            self.variables_to_solve = ['qf']
            self.qf = max(self.qi - self.de * self.eur, 1)
            self.t_max = DEFAULT_SOLVER_T_MAX_MONTHS
        elif self.t_max is None and self.de is None:
            self.variables_to_solve = ['de']
            self.de = (self.qi - self.qf) / self.eur
            self.t_max = DEFAULT_SOLVER_T_MAX_MONTHS
        elif self.t_max is None and self.eur is None:
            self.variables_to_solve = ['eur']
            self.t_max = DEFAULT_SOLVER_T_MAX_MONTHS
            self.eur = (self.qi - self.qf) / self.de
        elif self.qf is None and self.de is None:
            self.variables_to_solve = ['de']
            self.de = self.qi / self.eur
            self.qf = 1
        elif self.qf is None and self.eur is None:
            self.variables_to_solve = ['eur']
            self.eur = self.qi / self.de
            self.qf = 1
        elif self.de is None and self.eur is None:
            self.variables_to_solve = ['de', 'eur']
            # Set initial estimates for both variables
            self.de = self.dmin
            self.eur = self.qi * self.t_max
        # Handle cases where only one parameter is missing
        elif self.qi is None:
            self.variables_to_solve = ['qi']
            self.qi = self.qf + self.de * self.eur
        elif self.qf is None:
            self.variables_to_solve = ['qf']
            self.qf = max(self.qi - self.de * self.eur, 1)
        elif self.de is None:
            self.variables_to_solve = ['de']
            self.de = (self.qi - self.qf) / self.eur
        elif self.eur is None:
            self.variables_to_solve = ['eur']
            self.eur = (self.qi - self.qf) / self.de
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

        self.l_dca.D_MIN = self.dmin
        tn = int(self.t_max)
        if self._t_range_n != tn or self._t_range is None:
            self._t_range = np.arange(tn, dtype=float)
            self._t_range_n = tn
        t_range = self._t_range

        dca_array = np.asarray(self.l_dca.arps_decline(t_range, self.qi, self.de, self.b, 0), dtype=float)
        dca_array = np.where(dca_array > self.qf, dca_array, 0)

        self.l_t_max = len(np.where(dca_array > 0)[0])
        if self.l_t_max > 0:
            # Calculate cumulative production and compare with EUR
            cumulative_production = np.sum(dca_array)
            self.delta = abs(cumulative_production - self.eur)
        else:
            self.delta = 1e10
            
        return self.delta

    def solve(self):
        """
        Solve for optimal decline curve parameters.
        
        Returns:
            tuple: (qi, t_max, qf, de, eur, warning_flag, delta)
        """
        self.determine_solve()
        
        if len(self.variables_to_solve) == 0:
            return self.qi, self.t_max, self.qf, self.de, self.eur, False, self.delta

        x0 = np.array([float(getattr(self, var)) for var in self.variables_to_solve], dtype=float)
        bounds = [_SOLVER_VAR_BOUNDS[v] for v in self.variables_to_solve]
        lb = np.array([b[0] for b in bounds], dtype=float)
        ub = np.array([b[1] for b in bounds], dtype=float)
        x0 = np.clip(x0, lb, ub)

        def objective(vec):
            return float(self.dca_delta(vec))

        res = None
        opt_success = True
        try:
            if len(self.variables_to_solve) == 1:
                lo, hi = bounds[0]
                if not (np.isfinite(lo) and np.isfinite(hi) and lo < hi):
                    result = x0.copy()
                    opt_success = False
                else:
                    def objective_scalar(xx):
                        return float(self.dca_delta(np.array([float(xx)])))

                    res_sc = minimize_scalar(
                        objective_scalar,
                        bounds=(lo, hi),
                        method="bounded",
                        options={"maxiter": 120, "xatol": 1e-9},
                    )
                    result = np.array(
                        [float(np.clip(res_sc.x, lo, hi))], dtype=float
                    )
                    opt_success = bool(getattr(res_sc, "success", True))
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
                opt_success = bool(res.success)
        except Exception:
            opt_success = False
            result = x0.copy()

        self.dca_delta(result)

        if len(self.variables_to_solve) == 1:
            warning_flag = bool(not opt_success and self.delta > 1e-5)
        elif res is not None:
            # L-BFGS-B may set success=False on tight ftol while the residual is negligible.
            warning_flag = bool(not res.success and self.delta > 1e-5)
        else:
            warning_flag = True

        if self.qf is None:
            self.qf = self.l_qf
        return self.qi, self.t_max, self.qf, self.de, self.eur, warning_flag, self.delta


