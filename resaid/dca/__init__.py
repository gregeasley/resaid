"""
Decline curve analysis (DCA) — public API.

Import ``decline_curve`` and ``decline_solver`` from ``resaid.dca`` (same as ``resaid``).
"""

from .decline_curve import (
    DCA_FIT_METHOD_LEGACY,
    DCA_FIT_METHOD_MONOTONE_TWO_STEP,
    decline_curve,
)
from .solver import decline_solver

__all__ = [
    "decline_curve",
    "decline_solver",
    "DCA_FIT_METHOD_LEGACY",
    "DCA_FIT_METHOD_MONOTONE_TWO_STEP",
]

