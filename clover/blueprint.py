"""Loading, validating and hashing assessment blueprints.

A blueprint is a single YAML file that declares, for one course and one
term, the chain

    assessment item  --points-->  course objective  --->  indicator point

together with the evaluation policy.  Nothing about file formats,
spreadsheet layouts or student names appears here, which is what allows
one blueprint to be reused across cohorts and one cohort to be re-scored
under a revised blueprint.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import yaml

from .model import CourseInfo, Indicator, Item, Objective, Policy, sha256_obj

SCHEMA_VERSION = "1.0"


class BlueprintError(ValueError):
    """Raised when a blueprint cannot be loaded or is structurally invalid."""


@dataclass
class Blueprint:
    id: str
    schema_version: str
    course: CourseInfo
    policy: Policy
    indicators: list[Indicator]
    objectives: list[Objective]
    items: list[Item]
    raw: dict[str, Any] = field(default_factory=dict)

    # -- lookups ---------------------------------------------------------

    @property
    def objective_ids(self) -> list[str]:
        return [o.id for o in self.objectives]

    @property
    def item_ids(self) -> list[str]:
        return [i.id for i in self.items]

    def objective(self, oid: str) -> Objective:
        for o in self.objectives:
            if o.id == oid:
                return o
        raise KeyError(oid)

    def indicator(self, iid: str) -> Indicator:
        for i in self.indicators:
            if i.id == iid:
                return i
        raise KeyError(iid)

    def item(self, iid: str) -> Item:
        for i in self.items:
            if i.id == iid:
                return i
        raise KeyError(iid)

    def objectives_for_indicator(self, iid: str) -> list[Objective]:
        return [o for o in self.objectives if o.indicator == iid]

    def items_for_objective(self, oid: str) -> list[Item]:
        return [i for i in self.items if i.allocations.get(oid, 0) > 0]

    # -- derived structures ----------------------------------------------

    def weight_matrix(self) -> np.ndarray:
        """``W[i, j]`` = target points that item *i* contributes to objective *j*."""
        W = np.zeros((len(self.items), len(self.objectives)), dtype=float)
        index = {o: j for j, o in enumerate(self.objective_ids)}
        for item in self.items:
            for oid in item.allocations:
                if oid not in index:
                    raise BlueprintError(
                        f"item {item.id} allocates points to unknown objective "
                        f"{oid!r}")
        for i, item in enumerate(self.items):
            for oid, pts in item.allocations.items():
                W[i, index[oid]] = float(pts)
        return W

    def objective_points(self) -> dict[str, float]:
        W = self.weight_matrix()
        return dict(zip(self.objective_ids, W.sum(axis=0)))

    def indicator_points(self) -> dict[str, float]:
        pts = self.objective_points()
        out: dict[str, float] = {}
        for o in self.objectives:
            out[o.indicator] = out.get(o.indicator, 0.0) + pts[o.id]
        return out

    def total_points(self) -> float:
        return float(self.weight_matrix().sum())

    def hash(self) -> str:
        return sha256_obj(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "blueprint_id": self.id,
            "schema_version": self.schema_version,
            "course": self.course.to_dict(),
            "policy": self.policy.to_dict(),
            "indicators": [i.to_dict() for i in self.indicators],
            "objectives": [o.to_dict() for o in self.objectives],
            "items": [i.to_dict() for i in self.items],
        }

    # -- validation ------------------------------------------------------

    def validate(self, strict: bool = True) -> list[str]:
        """Return a list of structural problems; raise if *strict* and non-empty."""
        problems: list[str] = []

        if not self.objectives:
            problems.append("blueprint declares no course objectives")
        if not self.items:
            problems.append("blueprint declares no assessment items")

        oids = self.objective_ids
        if len(set(oids)) != len(oids):
            problems.append("duplicate course objective ids")
        iids = self.item_ids
        if len(set(iids)) != len(iids):
            problems.append("duplicate item ids")

        known_ind = {i.id for i in self.indicators}
        for o in self.objectives:
            if o.indicator not in known_ind:
                problems.append(
                    f"objective {o.id} maps to unknown indicator {o.indicator!r}")

        for it in self.items:
            if it.full_mark <= 0:
                problems.append(f"item {it.id} has non-positive full mark")
            if not it.allocations:
                problems.append(f"item {it.id} allocates points to no objective")
            for oid, pts in it.allocations.items():
                if oid not in oids:
                    problems.append(
                        f"item {it.id} allocates points to unknown objective {oid!r}")
                if pts < 0:
                    problems.append(f"item {it.id} has a negative allocation to {oid}")
            if it.derived_from:
                # derived_from must name either another item or a raw source key
                # that some item reads; a dangling reference would silently
                # disable the evidence-collapsing logic in the diagnostics.
                known = set(iids) | {x.source for x in self.items}
                if it.derived_from not in known:
                    problems.append(
                        f"item {it.id} declares derived_from={it.derived_from!r}, "
                        f"which is neither an item id nor a source key used by "
                        f"any item")

        total = sum(sum(it.allocations.values()) for it in self.items)
        if not math.isclose(total, self.policy.total_points, abs_tol=1e-6):
            problems.append(
                f"item allocations sum to {total:g}, expected "
                f"{self.policy.total_points:g}")

        if strict and problems:
            raise BlueprintError(
                "blueprint is invalid:\n  - " + "\n  - ".join(problems))

        pts = self.objective_points() if not problems else {}
        for oid, p in pts.items():
            if p <= 0:
                problems.append(f"objective {oid} receives no points from any item")

        for ind in self.indicators:
            if not self.objectives_for_indicator(ind.id):
                problems.append(f"indicator {ind.id} is supported by no objective")

        if not 0 < self.policy.qualifying_standard < 1:
            problems.append("policy.qualifying_standard must lie strictly in (0, 1)")

        if strict and problems:
            raise BlueprintError(
                "blueprint is invalid:\n  - " + "\n  - ".join(problems))
        return problems


# --------------------------------------------------------------------------


def load_blueprint(path: str, strict: bool = True) -> Blueprint:
    with open(path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    return parse_blueprint(raw, strict=strict)


def parse_blueprint(raw: dict[str, Any], strict: bool = True) -> Blueprint:
    if not isinstance(raw, dict):
        raise BlueprintError("blueprint root must be a mapping")

    version = str(raw.get("schema_version", SCHEMA_VERSION))
    if version.split(".")[0] != SCHEMA_VERSION.split(".")[0]:
        raise BlueprintError(
            f"unsupported blueprint schema_version {version!r}; "
            f"this build understands {SCHEMA_VERSION}")

    course = CourseInfo(**{k: str(v) for k, v in (raw.get("course") or {}).items()})
    policy = Policy(**(raw.get("policy") or {}))

    indicators = [
        Indicator(
            id=str(d["id"]),
            text=str(d.get("text", "")),
            requirement=str(d.get("requirement", "")),
            requirement_id=str(d.get("requirement_id", "")),
        )
        for d in (raw.get("indicators") or [])
    ]

    objectives = [
        Objective(
            id=str(d["id"]),
            text=str(d.get("text", "")),
            indicator=str(d["indicator"]),
            label=str(d.get("label", "")),
        )
        for d in (raw.get("objectives") or [])
    ]

    items = []
    for d in (raw.get("items") or []):
        items.append(Item(
            id=str(d["id"]),
            name=str(d.get("name", d["id"])),
            source=str(d["source"]),
            full_mark=float(d.get("full_mark", 100.0)),
            allocations={str(k): float(v) for k, v in (d.get("allocations") or {}).items()},
            kind=str(d.get("kind", "coursework")),
            aggregate=bool(d.get("aggregate", False)),
            group_assigned=bool(d.get("group_assigned", False)),
            derived_from=(str(d["derived_from"]) if d.get("derived_from") else None),
            note=str(d.get("note", "")),
        ))

    bp = Blueprint(
        id=str(raw.get("blueprint_id", "unnamed")),
        schema_version=version,
        course=course,
        policy=policy,
        indicators=indicators,
        objectives=objectives,
        items=items,
        raw=raw,
    )
    bp.validate(strict=strict)
    return bp
