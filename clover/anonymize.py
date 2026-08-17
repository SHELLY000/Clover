"""Pseudonymisation for sharing cohorts.

Attainment work is done on files full of named minors' marks.  Anything
that leaves the instructor's machine — an example dataset, a bug report,
a replication package — should go through here first.

Identifiers are replaced by a keyed HMAC truncated to a fixed width, so
the same student maps to the same pseudonym across files in one release
(joins survive) but the mapping cannot be reversed without the key, and a
different key produces an unlinkable release.  Scores are untouched:
perturbing them would defeat the purpose of shipping the example.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

from .model import Cohort, Student


def _tag(key: bytes, value: str, width: int = 8) -> str:
    return hmac.new(key, value.encode("utf-8"), hashlib.sha256).hexdigest()[:width]


def anonymize_cohort(cohort: Cohort, key: str | None = None,
                     keep_class: bool = True) -> tuple[Cohort, str]:
    """Return a pseudonymised copy of *cohort* and the key that was used."""
    key = key or secrets.token_hex(16)
    kb = key.encode("utf-8")

    class_map: dict[str, str] = {}
    students: list[Student] = []
    for st in cohort.students:
        cls = st.class_name
        if not keep_class and cls:
            cls = class_map.setdefault(cls, f"CLASS-{len(class_map) + 1:02d}")
        students.append(Student(
            sid=f"S{_tag(kb, st.sid)}",
            name=f"学生{_tag(kb, st.sid, 6)}",
            class_name=cls,
            group=(f"G{_tag(kb, st.group, 4)}" if st.group else ""),
            scores=dict(st.scores),
        ))

    out = Cohort(course_code=cohort.course_code, term=cohort.term,
                 students=students, sources=[], conflicts=[])
    return out, key


def cohort_to_long_csv(cohort: Cohort, path: str) -> str:
    """Write a cohort in the portable long layout the tabular reader accepts."""
    import csv

    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["sid", "name", "class", "group", "item", "score"])
        for st in cohort.students:
            for key in sorted(st.scores):
                w.writerow([st.sid, st.name, st.class_name, st.group,
                            key, st.scores[key]])
    return path
