"""Machine-readable attainment record and its verifier.

The record is the citable artefact: it carries the attainment values, the
diagnostics, the blueprint that produced them, the hash of every input
file, and the tool version.  ``clover verify`` re-reads the named inputs,
recomputes, and reports whether the numbers still come out the same —
which is what lets a reviewer check a submitted attainment table without
taking anyone's word for it.
"""

from __future__ import annotations

import json
import os
from collections import Counter
from typing import Any

import numpy as np

from ..model import AttainmentResult, Cohort, DiagnosticReport


def build_record(result: AttainmentResult, report: DiagnosticReport,
                 cohort: Cohort, blueprint_dict: dict[str, Any],
                 recommendations: list[str] | None = None) -> dict[str, Any]:
    return {
        "record_type": "clover.attainment",
        "record_version": "1.0",
        "tool_version": result.tool_version,
        "generated_at": result.generated_at,
        "blueprint": blueprint_dict,
        "blueprint_hash": result.blueprint_hash,
        "cohort_hash": result.cohort_hash,
        "sources": [s.to_dict() for s in cohort.sources],
        "conflicts": cohort.conflicts,
        "attainment": result.to_dict(),
        "diagnostics": report.to_dict(),
        "recommendations": recommendations or [],
    }


def write_record(path: str, record: dict[str, Any]) -> str:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(record, fh, ensure_ascii=False, indent=2, default=str)
    return path


def verify_record(path: str, tolerance: float = 1e-6,
                  recompute: bool = True) -> dict[str, Any]:
    """Re-derive a record from its declared inputs and compare.

    Three things are checked, in order of how badly each would compromise
    an audit: that every input file still hashes to the value recorded;
    that the blueprint embedded in the record still validates and hashes
    to the recorded value; and that recomputation reproduces every
    attainment figure within *tolerance*.
    """
    from ..blueprint import parse_blueprint
    from ..compute import build_matrix, compute_attainment
    from ..diagnose import diagnose
    from ..ingest import build_cohort
    from ..model import sha256_file

    with open(path, "r", encoding="utf-8") as fh:
        record = json.load(fh)

    findings: list[dict[str, Any]] = []
    ok = True

    for src in record.get("sources", []):
        p = src["path"]
        if not os.path.exists(p):
            findings.append({"check": "source-present", "status": "fail",
                             "detail": f"input file missing: {p}"})
            ok = False
            continue
        digest = sha256_file(p)
        same = digest == src["sha256"]
        ok &= same
        findings.append({"check": "source-hash",
                         "status": "pass" if same else "fail",
                         "detail": p,
                         "expected": src["sha256"][:16],
                         "actual": digest[:16]})

    bp = parse_blueprint(record["blueprint"], strict=False)
    bp_ok = bp.hash() == record["blueprint_hash"]
    ok &= bp_ok
    findings.append({"check": "blueprint-hash",
                     "status": "pass" if bp_ok else "fail",
                     "expected": record["blueprint_hash"][:16],
                     "actual": bp.hash()[:16]})

    if recompute and all(os.path.exists(s["path"]) for s in record.get("sources", [])):
        specs = [{"path": s["path"], "reader": s["reader"], **(s.get("options") or {})}
                 for s in record["sources"]]
        cohort = build_cohort(bp.course.code, bp.course.term, specs)
        sm = build_matrix(bp, cohort)
        fresh = compute_attainment(bp, cohort, sm,
                                   tool_version=record.get("tool_version", ""))
        old = {o["id"]: o for o in record["attainment"]["objectives"]}
        drift = ci_drift = 0.0
        for o in fresh.objectives:
            prev = old.get(o.id)
            if prev is None:
                continue
            drift = max(drift, abs(o.attainment - prev["attainment"]))
            ci_drift = max(ci_drift,
                           abs(o.ci_low - prev["ci_low"]),
                           abs(o.ci_high - prev["ci_high"]))
        same = drift <= tolerance
        ok &= same
        findings.append({"check": "recompute-objectives",
                         "status": "pass" if same else "fail",
                         "max_abs_drift": drift})
        # The interval is part of the claim, so it is part of what is verified:
        # an unseeded or differently-seeded bootstrap would reproduce the point
        # estimate exactly and the interval not at all.
        ci_ok = ci_drift <= tolerance
        ok &= ci_ok
        findings.append({"check": "recompute-intervals",
                         "status": "pass" if ci_ok else "fail",
                         "max_abs_drift": ci_drift})
        course_drift = abs(fresh.course_attainment
                           - record["attainment"]["course_attainment"])
        ok &= course_drift <= tolerance
        findings.append({"check": "recompute-course",
                         "status": "pass" if course_drift <= tolerance else "fail",
                         "abs_drift": course_drift})
        rep = diagnose(bp, sm,
                       threshold=np.array([o.threshold_attainment
                                           for o in fresh.objectives]))
        same_grades = rep.grades == record["diagnostics"]["grades"]
        ok &= same_grades
        findings.append({"check": "recompute-grades",
                         "status": "pass" if same_grades else "fail",
                         "detail": rep.grades})
        # Compare the findings themselves, not only the grades they roll up to:
        # two blueprints can earn the same grades for different reasons.
        def _sig(checks):
            return sorted(Counter((c["code"] if isinstance(c, dict) else c.code,
                                   c["level"] if isinstance(c, dict) else c.level)
                                  for c in checks).items())
        same_checks = _sig(rep.checks) == _sig(record["diagnostics"]["checks"])
        ok &= same_checks
        findings.append({"check": "recompute-diagnostics",
                         "status": "pass" if same_checks else "fail",
                         "detail": f"{len(rep.checks)} checks"})

    return {"record": path, "verified": bool(ok), "findings": findings}
