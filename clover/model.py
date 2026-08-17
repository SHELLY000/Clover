"""Core data model.

The model has three layers that stay strictly separated:

``Blueprint``
    *What is supposed to be measured.*  Declarative, versioned, and
    independent of any particular cohort or file format.
``Cohort``
    *What was actually observed.*  A set of students, each carrying raw
    scores keyed by source key, plus provenance for every input file.
``AttainmentResult`` / ``DiagnosticReport``
    *What can be concluded*, and *how much of it is trustworthy*.

Keeping these apart is what makes an assessment replayable: the same
cohort can be re-scored under a different blueprint version, and the
same blueprint can be applied to a later cohort, without editing code.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any

# --------------------------------------------------------------------------
# Blueprint side
# --------------------------------------------------------------------------

@dataclass
class Indicator:
    """A graduation-requirement indicator point (毕业要求指标点)."""

    id: str
    text: str
    requirement: str = ""
    requirement_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Objective:
    """A course learning outcome (课程目标 / 课程学习成果)."""

    id: str
    text: str
    indicator: str
    label: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Item:
    """One assessment item and how its points are allocated to objectives.

    ``allocations`` maps objective id to *target points* on the course's
    100-point scale.  The sum of allocations over all items must equal
    ``policy.total_points`` (100 by convention); this is checked by
    :meth:`Blueprint.validate`.

    Two flags matter for identifiability and are deliberately part of the
    blueprint rather than inferred from data:

    ``aggregate``
        The observed score is a roll-up that the instructor cannot
        decompose (e.g. a single "final coursework" mark standing in for
        a five-dimension rubric).  Any two items derived from the same
        aggregate are structurally confounded.
    ``group_assigned``
        The score is awarded to a project group, so every member shares
        it and within-group variance is zero by construction.
    """

    id: str
    name: str
    source: str
    full_mark: float = 100.0
    allocations: dict[str, float] = field(default_factory=dict)
    kind: str = "coursework"
    aggregate: bool = False
    group_assigned: bool = False
    derived_from: str | None = None
    note: str = ""

    @property
    def points(self) -> float:
        return float(sum(self.allocations.values()))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Policy:
    """Evaluation policy: the knobs a department is allowed to turn."""

    qualifying_standard: float = 0.65
    total_points: float = 100.0
    method: str = "score_ratio"          # score_ratio | threshold
    expectation_level: float = 0.60      # used by the threshold method
    bootstrap_iterations: int = 2000
    bootstrap_confidence: float = 0.95
    seed: int = 20260816
    ceiling_ratio: float = 0.95          # item mean above this counts as ceiling
    ceiling_sd: float = 5.0              # ...and sd below this (points)
    min_items_per_objective: int = 2
    collinearity_warn: float = 0.90      # |r| above this warns
    collinearity_fail: float = 0.98
    grade_rounding: str = "none"         # none | integer — see report.distributions
    include_per_student: bool = True     # write per-student rows into the record      # |r| above this fails

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CourseInfo:
    code: str
    name: str
    name_en: str = ""
    institution: str = ""
    program: str = ""
    term: str = ""
    credits: str = ""
    hours: str = ""
    nature: str = ""
    department: str = ""
    assessment_mode: str = ""
    instructor: str = ""
    cohort_label: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# --------------------------------------------------------------------------
# Observation side
# --------------------------------------------------------------------------

@dataclass
class SourceFile:
    """Provenance record for one ingested file."""

    path: str
    reader: str
    sha256: str
    rows: int
    keys: list[str] = field(default_factory=list)
    options: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Student:
    """One student's raw evidence, keyed by *source key* (not item id).

    Source keys are stable strings emitted by readers, e.g.
    ``classroom.3`` or ``final.total``.  Blueprint items point at them
    through ``Item.source``, which is what lets the same cohort be
    scored under several blueprints.
    """

    sid: str
    name: str
    class_name: str = ""
    scores: dict[str, float] = field(default_factory=dict)
    group: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Cohort:
    course_code: str
    term: str
    students: list[Student] = field(default_factory=list)
    sources: list[SourceFile] = field(default_factory=list)
    conflicts: list[dict[str, Any]] = field(default_factory=list)

    @property
    def classes(self) -> list[str]:
        seen: list[str] = []
        for s in self.students:
            if s.class_name and s.class_name not in seen:
                seen.append(s.class_name)
        return seen

    def available_keys(self) -> set[str]:
        keys: set[str] = set()
        for s in self.students:
            keys.update(s.scores)
        return keys

    def to_dict(self) -> dict[str, Any]:
        return {
            "course_code": self.course_code,
            "term": self.term,
            "students": [s.to_dict() for s in self.students],
            "sources": [s.to_dict() for s in self.sources],
            "conflicts": self.conflicts,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Cohort:
        return cls(
            course_code=d["course_code"],
            term=d["term"],
            students=[Student(**s) for s in d["students"]],
            sources=[SourceFile(**s) for s in d.get("sources", [])],
            conflicts=d.get("conflicts", []),
        )


# --------------------------------------------------------------------------
# Result side
# --------------------------------------------------------------------------

@dataclass
class ObjectiveResult:
    id: str
    text: str
    indicator: str
    target_points: float
    mean_points: float
    attainment: float
    ci_low: float
    ci_high: float
    threshold_attainment: float
    n_students: int
    n_items: int
    below_standard: bool
    risk: float                      # bootstrap P(attainment < standard)
    grade: str = "?"                 # identifiability grade, filled by diagnose

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class IndicatorResult:
    id: str
    text: str
    requirement: str
    target_points: float
    mean_points: float
    attainment: float
    objectives: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ItemStat:
    id: str
    name: str
    kind: str
    points: float
    mean_ratio: float
    sd: float
    min: float
    max: float
    n: int
    ceiling: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AttainmentResult:
    blueprint_id: str
    blueprint_hash: str
    cohort_hash: str
    course: CourseInfo
    policy: Policy
    method: str
    n_students: int
    objectives: list[ObjectiveResult]
    indicators: list[IndicatorResult]
    items: list[ItemStat]
    course_attainment: float
    course_mean_points: float
    per_student: list[dict[str, Any]] = field(default_factory=list)
    distributions: dict[str, Any] = field(default_factory=dict)
    incomplete: list[dict[str, Any]] = field(default_factory=list)
    generated_at: str = ""
    tool_version: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d


@dataclass
class Check:
    """One diagnostic finding."""

    code: str
    level: str                       # pass | warn | fail
    scope: str                       # blueprint | objective:<id> | item:<id>
    message: str
    value: Any = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DiagnosticReport:
    blueprint_id: str
    checks: list[Check]
    effective_rank: float
    participation_ratio: float
    rank99: int
    n_objectives: int
    separation_index: float
    between_objective_sd: float
    between_student_sd: float
    correlation: list[list[float]]
    objective_ids: list[str]
    grades: dict[str, str]
    confounded_pairs: list[list[str]]
    sensitivity: dict[str, float]

    @property
    def worst_level(self) -> str:
        levels = {c.level for c in self.checks}
        for lv in ("fail", "warn", "pass"):
            if lv in levels:
                return lv
        return "pass"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["worst_level"] = self.worst_level
        return d


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_obj(obj: Any) -> str:
    payload = json.dumps(obj, sort_keys=True, ensure_ascii=False,
                         separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
