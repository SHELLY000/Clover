"""Attainment computation.

Given a blueprint and a cohort, build

* ``R`` — the ``n × m`` matrix of item score *ratios* in [0, 1]
* ``P = R · W`` — the ``n × k`` matrix of points each student earned
  toward each objective, where ``W`` is the blueprint weight matrix
* the attainment of objective *j*, under the two methods in common use.

**Score-ratio method** (评分法, the default) is the cohort mean of earned
points over target points::

    A_j = mean_s ( P[s, j] ) / sum_i W[i, j]

**Threshold method** (合格率法) is the fraction of students whose ratio
reaches the expectation level::

    A_j = ( 1 / n ) · #{ s : P[s, j] / sum_i W[i, j] >= L }

Both are reported for every objective, because they answer different
questions and institutions differ on which one they require.  Each is
accompanied by a percentile bootstrap interval over students, which is
what turns a bare three-decimal number into a statement with a stated
precision — the cohort is a sample, and a value of 0.87 computed from 92
students is not the same evidence as 0.87 computed from 12.
"""

from __future__ import annotations

import datetime as _dt
import warnings
from typing import Any

import numpy as np

from .blueprint import Blueprint
from .model import (
    AttainmentResult,
    Cohort,
    IndicatorResult,
    ItemStat,
    ObjectiveResult,
    sha256_obj,
)

__all__ = ["ScoreMatrix", "build_matrix", "compute_attainment", "grade_bands"]


class MissingEvidence(ValueError):
    pass


class ScoreMatrix:
    """The numeric core: item ratios, objective points, and their indices."""

    def __init__(self, bp: Blueprint, cohort: Cohort,
                 require_complete: bool = False):
        self.blueprint = bp
        self.item_ids = bp.item_ids
        self.objective_ids = bp.objective_ids
        self.W = bp.weight_matrix()

        available = cohort.available_keys()
        wanted = {it.source for it in bp.items}
        missing = sorted(wanted - available)
        if missing:
            raise MissingEvidence(
                "cohort has no evidence for source key(s): " + ", ".join(missing)
                + f"\navailable keys: {', '.join(sorted(available))}")

        rows: list[list[float]] = []
        self.students: list[Any] = []
        self.incomplete: list[dict[str, Any]] = []
        for st in cohort.students:
            vals: list[float] = []
            gaps: list[str] = []
            for it in bp.items:
                v = st.scores.get(it.source)
                if v is None:
                    gaps.append(it.id)
                    vals.append(np.nan)
                else:
                    vals.append(float(v) / it.full_mark)
            if gaps:
                self.incomplete.append({"sid": st.sid, "name": st.name,
                                        "missing_items": gaps})
                if require_complete:
                    continue
            rows.append(vals)
            self.students.append(st)

        if not rows:
            raise MissingEvidence("no student records survived ingestion")

        self.R = np.asarray(rows, dtype=float)
        # An absent item is scored as absent, not as zero: zero-filling a
        # missing assignment silently converts a data problem into a (wrong)
        # low attainment value. Each student's objective ratio is therefore
        # normalised over the items actually observed for that student, and
        # only then rescaled onto the full target so that the 100-point scale
        # is preserved for reporting.
        self.mask = ~np.isnan(self.R)
        filled = np.where(self.mask, self.R, 0.0)
        earned = filled @ self.W
        self.observed_target = self.mask.astype(float) @ self.W
        self.target = self.W.sum(axis=0)
        with np.errstate(divide="ignore", invalid="ignore"):
            self.ratio = np.where(self.observed_target > 0,
                                  earned / self.observed_target, np.nan)
        self.P = self.ratio * self.target

    @property
    def n(self) -> int:
        return self.R.shape[0]

    def total_points(self) -> np.ndarray:
        return self.P.sum(axis=1)


def build_matrix(bp: Blueprint, cohort: Cohort, **kw: Any) -> ScoreMatrix:
    return ScoreMatrix(bp, cohort, **kw)


def _bootstrap(ratio: np.ndarray, iterations: int, confidence: float,
               seed: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Percentile bootstrap over students for the column means of *ratio*."""
    n, k = ratio.shape
    if n < 2 or iterations <= 0:
        m = np.nanmean(ratio, axis=0)
        return m, m, np.zeros(k)
    rng = np.random.default_rng(seed)
    draws = np.empty((iterations, k), dtype=float)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        for b in range(iterations):
            idx = rng.integers(0, n, n)
            draws[b] = np.nanmean(ratio[idx], axis=0)
    alpha = (1.0 - confidence) / 2.0
    lo = np.quantile(draws, alpha, axis=0)
    hi = np.quantile(draws, 1.0 - alpha, axis=0)
    return lo, hi, draws


def _distribution(values: np.ndarray, rounding: str = "none") -> dict[str, Any]:
    """Band counts and moments for a vector of marks under one rounding rule.

    Registrars round each student's overall mark to an integer before
    tabulating it, while a blueprint total is a sum of un-rounded component
    points. The two disagree by a few tenths of a mark and by a handful of
    students at band boundaries. That is a difference of convention, not of
    arithmetic, so both are computed and reported rather than one being
    quietly preferred.
    """
    v = np.asarray(values, dtype=float)
    v = v[~np.isnan(v)]
    if rounding == "integer":
        # Half-up, not NumPy's default half-to-even. Grade totals land on .5
        # constantly — here, 44 of 92 students — and banker's rounding sends
        # half of those down, which no registrar does. Getting this wrong
        # shifts the cohort mean by ~0.16 marks and makes the generated form
        # disagree with the student records system for no visible reason.
        v = np.floor(v + 0.5)
    elif rounding != "none":
        raise ValueError(f"unknown grade_rounding {rounding!r}; "
                         f"expected 'none' or 'integer'")
    return {"bands": grade_bands(v), "mean": float(np.mean(v)) if v.size else float("nan"),
            "sd": float(np.std(v)) if v.size else float("nan"),
            "n": int(v.size), "rounding": rounding}


def grade_bands(values: np.ndarray) -> dict[str, int]:
    """Count scores into the six bands used by the institutional form."""
    bands = [("100-90", 90, 101), ("89-80", 80, 90), ("79-70", 70, 80),
             ("69-60", 60, 70), ("59-30", 30, 60), ("<30", -1, 30)]
    out: dict[str, int] = {}
    v = np.asarray(values, dtype=float)
    v = v[~np.isnan(v)]
    for label, lo, hi in bands:
        out[label] = int(((v >= lo) & (v < hi)).sum())
    return out


def compute_attainment(bp: Blueprint, cohort: Cohort,
                       matrix: ScoreMatrix | None = None,
                       tool_version: str = "") -> AttainmentResult:
    sm = matrix or build_matrix(bp, cohort)
    pol = bp.policy
    ratio = sm.ratio
    n = sm.n

    mean_ratio = np.nanmean(ratio, axis=0)
    lo, hi, draws = _bootstrap(ratio, pol.bootstrap_iterations,
                               pol.bootstrap_confidence, pol.seed)
    thresh = (ratio >= pol.expectation_level).mean(axis=0)
    risk = ((draws < pol.qualifying_standard).mean(axis=0)
            if draws.ndim == 2 else np.zeros_like(mean_ratio))

    objectives: list[ObjectiveResult] = []
    for j, oid in enumerate(sm.objective_ids):
        o = bp.objective(oid)
        objectives.append(ObjectiveResult(
            id=oid, text=o.text, indicator=o.indicator,
            target_points=float(sm.target[j]),
            mean_points=float(np.nanmean(sm.P[:, j])),
            attainment=float(mean_ratio[j]),
            ci_low=float(lo[j]), ci_high=float(hi[j]),
            threshold_attainment=float(thresh[j]),
            n_students=n,
            n_items=len(bp.items_for_objective(oid)),
            below_standard=bool(mean_ratio[j] < pol.qualifying_standard),
            risk=float(risk[j]),
        ))

    indicators: list[IndicatorResult] = []
    for ind in bp.indicators:
        cols = [sm.objective_ids.index(o.id)
                for o in bp.objectives_for_indicator(ind.id)]
        if not cols:
            continue
        tgt = float(sm.target[cols].sum())
        earned = float(np.nanmean(sm.P[:, cols].sum(axis=1)))
        indicators.append(IndicatorResult(
            id=ind.id, text=ind.text, requirement=ind.requirement,
            target_points=tgt, mean_points=earned,
            attainment=(earned / tgt if tgt else float("nan")),
            objectives=[sm.objective_ids[c] for c in cols],
        ))

    items: list[ItemStat] = []
    for i, it in enumerate(bp.items):
        col = sm.R[:, i]
        valid = col[~np.isnan(col)]
        if valid.size == 0:
            valid = np.array([np.nan])
        pts = valid * it.full_mark
        ceiling = bool(np.nanmean(valid) >= pol.ceiling_ratio
                       and np.nanstd(pts) <= pol.ceiling_sd)
        items.append(ItemStat(
            id=it.id, name=it.name, kind=it.kind, points=it.points,
            mean_ratio=float(np.nanmean(valid)), sd=float(np.nanstd(pts)),
            min=float(np.nanmin(pts)), max=float(np.nanmax(pts)),
            n=int(np.sum(~np.isnan(col))), ceiling=ceiling,
        ))

    totals = sm.total_points()
    course_mean = float(np.nanmean(totals))
    course_att = course_mean / float(sm.target.sum())

    per_student = []
    for s, st in enumerate(sm.students):
        per_student.append({
            "sid": st.sid, "name": st.name, "class_name": st.class_name,
            "points": {oid: float(sm.P[s, j])
                       for j, oid in enumerate(sm.objective_ids)},
            "total": float(totals[s]),
        })

    final_source = next((it.source for it in bp.items if it.kind == "final"), None)
    final_marks = np.array([st.scores.get(final_source, np.nan)
                            for st in sm.students], dtype=float) \
        if final_source else np.array([])

    other = "integer" if pol.grade_rounding == "none" else "none"
    distributions = {
        "total": _distribution(totals, pol.grade_rounding),
        "total_alternate_rounding": _distribution(totals, other),
    }
    if final_marks.size and not np.all(np.isnan(final_marks)):
        distributions["final"] = _distribution(final_marks, pol.grade_rounding)

    return AttainmentResult(
        blueprint_id=bp.id,
        blueprint_hash=bp.hash(),
        cohort_hash=sha256_obj(cohort.to_dict()),
        course=bp.course,
        policy=pol,
        method=pol.method,
        n_students=n,
        objectives=objectives,
        indicators=indicators,
        items=items,
        course_attainment=course_att,
        course_mean_points=course_mean,
        per_student=(per_student if pol.include_per_student else []),
        distributions=distributions,
        incomplete=list(sm.incomplete),
        generated_at=_dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        tool_version=tool_version,
    )
