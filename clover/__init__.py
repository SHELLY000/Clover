"""CLOVER — Course Learning-Outcome Validation, Evaluation and Reporting.

Outcome-based accreditation asks every course to report, each term, how
far each declared learning objective was attained.  In practice that
report is assembled by hand in a spreadsheet, and the number it produces
is unauditable (nobody can re-derive it), unqualified (a point estimate
from a sample of thirty, printed to three decimals), and often
unidentifiable (six objectives computed as six fixed shares of two
aggregate marks, so they cannot differ from one another in any way the
evidence could detect).

CLOVER makes the computation declarative, reproducible, and — the part
that matters — self-checking:

>>> from clover import load_blueprint, build_cohort, run
>>> bp = load_blueprint("blueprints/course.yaml")
>>> cohort = build_cohort(bp.course.code, bp.course.term, sources)
>>> result, report, recs = run(bp, cohort)
>>> report.grades
{'CO1': 'C', 'CO2': 'C', ...}
"""

from __future__ import annotations

__version__ = "1.1.0"

from .blueprint import Blueprint, BlueprintError, load_blueprint, parse_blueprint
from .compute import ScoreMatrix, build_matrix, compute_attainment
from .diagnose import diagnose, recommendations
from .ingest import build_cohort
from .model import AttainmentResult, Check, Cohort, DiagnosticReport, Student

__all__ = [
    "AttainmentResult",
    "Blueprint",
    "BlueprintError",
    "Check",
    "Cohort",
    "DiagnosticReport",
    "ScoreMatrix",
    "Student",
    "__version__",
    "build_cohort",
    "build_matrix",
    "compute_attainment",
    "diagnose",
    "load_blueprint",
    "parse_blueprint",
    "recommendations",
    "run",
]


def run(blueprint, cohort, require_complete: bool = False):
    """Convenience: matrix → attainment → diagnostics → recommendations."""
    import numpy as np

    from .compute import _bootstrap

    sm = build_matrix(blueprint, cohort, require_complete=require_complete)
    result = compute_attainment(blueprint, cohort, sm, tool_version=__version__)
    _, _, draws = _bootstrap(sm.ratio, blueprint.policy.bootstrap_iterations,
                             blueprint.policy.bootstrap_confidence,
                             blueprint.policy.seed)
    report = diagnose(
        blueprint, sm,
        attainment=np.array([o.attainment for o in result.objectives]),
        bootstrap_draws=draws,
        threshold=np.array([o.threshold_attainment for o in result.objectives]))
    for o in result.objectives:
        o.grade = report.grades.get(o.id, "?")
    return result, report, recommendations(blueprint, report)
