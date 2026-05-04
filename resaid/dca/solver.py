"""
Decline curve parameter solver (`decline_solver`).

This module is part of the ``resaid.dca`` package; import from ``resaid.dca`` or ``resaid``.
"""

import numpy as np
from scipy.optimize import fsolve

from ..dca_constants import DEFAULT_SOLVER_T_MAX_MONTHS

from .decline_curve import decline_curve

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

    def __init__(self, qi=None, qf=None, de=None, dmin=None, b=None, eur=None, t_max=None):
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
        self.l_dca = decline_curve()

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
            vars_to_solve: List of parameter values to evaluate
            
        Returns:
            float: Objective function value (sum of squared residuals)
        """
        for var_name, var_value in zip(self.variables_to_solve, vars_to_solve):
            setattr(self, var_name, var_value)

        self.l_dca.D_MIN = self.dmin
        t_range = np.array(range(0, int(self.t_max)))

        dca_array = np.array(self.l_dca.arps_decline(t_range, self.qi, self.de, self.b, 0))
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
        
        try:
            result = fsolve(self.dca_delta, [getattr(self, var) for var in self.variables_to_solve])
            warning_flag = False
        except Exception:
            warning_flag = True
            result = [getattr(self, var) for var in self.variables_to_solve]
            
        for var_name, var_value in zip(self.variables_to_solve, result):
            setattr(self, var_name, var_value)
            
        if self.qf is None:
            self.qf = self.l_qf
        return self.qi, self.t_max, self.qf, self.de, self.eur, warning_flag, self.delta


