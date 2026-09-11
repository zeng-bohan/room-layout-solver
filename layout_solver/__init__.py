"""Take-home layout solver package: geometry, search, SVG output, validation."""

from .solver import Problem, Solver
from .validate import check as validate_result
from .visualize import render_svg

__all__ = ["Problem", "Solver", "validate_result", "render_svg"]
