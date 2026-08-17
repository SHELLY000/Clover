"""Portable reader for plain CSV / XLSX evidence.

Two shapes are accepted, chosen with ``layout``:

``long`` (default)
    one row per (student, item): ``sid, name, class, item, score``
``wide``
    one row per student, one column per source key; the column header is
    taken verbatim as the source key.

This is the format any institution can export to without writing a
plugin, and it is what the shipped example dataset uses.
"""

from __future__ import annotations

from typing import Any

import pandas as pd


def _read_frame(path: str) -> pd.DataFrame:
    if path.lower().endswith((".xlsx", ".xlsm")):
        return pd.read_excel(path, dtype=str)
    return pd.read_csv(path, dtype=str)


def read(path: str, layout: str = "long",
         sid_column: str = "sid", name_column: str = "name",
         class_column: str = "class", group_column: str = "group",
         item_column: str = "item", score_column: str = "score",
         **_: Any) -> tuple[list[dict[str, Any]], list[str]]:
    df = _read_frame(path)
    df.columns = [str(c).strip() for c in df.columns]
    keys: set[str] = set()

    if layout == "long":
        required = {sid_column, item_column, score_column}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"{path}: missing column(s) {sorted(missing)}")
        acc: dict[str, dict[str, Any]] = {}
        order: list[str] = []
        for _, row in df.iterrows():
            sid = str(row[sid_column]).strip()
            if not sid or sid.lower() == "nan":
                continue
            rec = acc.get(sid)
            if rec is None:
                rec = {"sid": sid,
                       "name": str(row.get(name_column, "") or "").strip(),
                       "class_name": str(row.get(class_column, "") or "").strip(),
                       "group": str(row.get(group_column, "") or "").strip(),
                       "scores": {}}
                acc[sid] = rec
                order.append(sid)
            key = str(row[item_column]).strip()
            raw = row[score_column]
            if raw is None or str(raw).strip() in ("", "nan"):
                continue
            rec["scores"][key] = float(raw)
            keys.add(key)
        return [acc[s] for s in order], sorted(keys)

    if layout == "wide":
        meta = {sid_column, name_column, class_column, group_column}
        rows: list[dict[str, Any]] = []
        for _, row in df.iterrows():
            sid = str(row.get(sid_column, "") or "").strip()
            if not sid or sid.lower() == "nan":
                continue
            scores: dict[str, float] = {}
            for col in df.columns:
                if col in meta:
                    continue
                raw = row[col]
                if raw is None or str(raw).strip() in ("", "nan"):
                    continue
                scores[col] = float(raw)
                keys.add(col)
            rows.append({"sid": sid,
                         "name": str(row.get(name_column, "") or "").strip(),
                         "class_name": str(row.get(class_column, "") or "").strip(),
                         "group": str(row.get(group_column, "") or "").strip(),
                         "scores": scores})
        return rows, sorted(keys)

    raise ValueError(f"unknown layout {layout!r}; expected 'long' or 'wide'")
