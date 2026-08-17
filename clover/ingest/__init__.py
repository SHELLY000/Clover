"""Evidence readers.

A reader turns one input file into ``(rows, keys)`` where each row is a
``dict`` with at least ``sid`` and a ``scores`` mapping of *source key*
to numeric value.  Readers never see the blueprint; they only publish
source keys, and the blueprint decides what those keys mean.

Third-party readers register under the ``clover.readers`` entry-point
group, so a site can add a reader for its own student-information system
without forking the project.
"""

from __future__ import annotations

import importlib.metadata as _md
from collections.abc import Callable
from typing import Any

from ..model import Cohort, SourceFile, Student, sha256_file

ReaderFn = Callable[..., tuple[list[dict[str, Any]], list[str]]]

_REGISTRY: dict[str, ReaderFn] = {}


def register(name: str, fn: ReaderFn) -> None:
    _REGISTRY[name] = fn


def get_reader(name: str) -> ReaderFn:
    if name not in _REGISTRY:
        _load_entry_points()
    if name not in _REGISTRY:
        raise KeyError(
            f"unknown reader {name!r}; available: {', '.join(sorted(_REGISTRY))}")
    return _REGISTRY[name]


def available() -> list[str]:
    _load_entry_points()
    return sorted(_REGISTRY)


_ep_loaded = False


def _load_entry_points() -> None:
    global _ep_loaded
    if _ep_loaded:
        return
    _ep_loaded = True
    try:
        eps = _md.entry_points(group="clover.readers")
    except Exception:  # noqa: BLE001 - entry-point API differs across
        return         # interpreters; an unavailable registry is not fatal
    for ep in eps:
        try:
            register(ep.name, ep.load())
        except Exception:  # noqa: BLE001, S112 - one site's broken plugin must
            continue       # not stop the built-in readers from working


# built-in readers ---------------------------------------------------------

from . import tabular, wbu_gradebook, wbu_transcript

register("wbu_gradebook", wbu_gradebook.read)
register("wbu_transcript", wbu_transcript.read)
register("tabular", tabular.read)


# cohort assembly ----------------------------------------------------------

def build_cohort(course_code: str, term: str,
                 specs: list[dict[str, Any]]) -> Cohort:
    """Merge several source files into one cohort.

    Merging is by student id.  When two sources disagree about the same
    source key for the same student the *first* source wins and the
    disagreement is recorded in ``cohort.conflicts`` rather than silently
    dropped — a mismatch between the item-level gradebook and the
    registrar's transcript is a finding, not a nuisance.
    """
    students: dict[str, Student] = {}
    order: list[str] = []
    sources: list[SourceFile] = []
    conflicts: list[dict[str, Any]] = []

    for spec in specs:
        path = spec["path"]
        reader_name = spec["reader"]
        options = {k: v for k, v in spec.items() if k not in ("path", "reader")}
        reader = get_reader(reader_name)
        rows, keys = reader(path, **options)
        sources.append(SourceFile(path=path, reader=reader_name,
                                  sha256=sha256_file(path), rows=len(rows),
                                  keys=keys, options=options))
        for row in rows:
            sid = str(row["sid"]).strip()
            if not sid:
                continue
            st = students.get(sid)
            if st is None:
                st = Student(sid=sid, name=str(row.get("name", "")).strip(),
                             class_name=str(row.get("class_name", "")).strip(),
                             group=str(row.get("group", "")).strip())
                students[sid] = st
                order.append(sid)
            else:
                if not st.name:
                    st.name = str(row.get("name", "")).strip()
                if not st.class_name:
                    st.class_name = str(row.get("class_name", "")).strip()
                if not st.group:
                    st.group = str(row.get("group", "")).strip()
            for key, value in (row.get("scores") or {}).items():
                if value is None:
                    continue
                if key in st.scores and abs(st.scores[key] - float(value)) > 1e-9:
                    conflicts.append({
                        "sid": sid, "name": st.name, "key": key,
                        "kept": st.scores[key], "discarded": float(value),
                        "source": path,
                    })
                    continue
                st.scores[key] = float(value)

    return Cohort(course_code=course_code, term=term,
                  students=[students[s] for s in order],
                  sources=sources, conflicts=conflicts)
