"""
Shared numeric defaults for decline curve analysis.

These are library-wide defaults; callers can override via method arguments
where supported (e.g. ``num_months`` on forecast helpers).
"""

# Default horizon when ``decline_solver`` must assume a missing ``t_max`` (months).
DEFAULT_SOLVER_T_MAX_MONTHS = 1200

# Default forecast length for oneline / flowstream / typecurve outputs (months).
DEFAULT_FORECAST_HORIZON_MONTHS = 1200
