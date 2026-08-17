"""Command-line interface.

    clover run       --config run.yaml -o out/     end-to-end
    clover ingest    --config run.yaml -o cohort.json
    clover compute   --cohort c.json --blueprint b.yaml -o attainment.json
    clover diagnose  --cohort c.json --blueprint b.yaml
    clover report    --record record.json -o out/
    clover verify    --record record.json
    clover anonymize --cohort c.json -o example.csv
    clover blueprint --check b.yaml
    clover readers
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

import yaml

from . import __version__
from .anonymize import anonymize_cohort, cohort_to_long_csv
from .blueprint import BlueprintError, load_blueprint, parse_blueprint
from .compute import MissingEvidence, build_matrix, compute_attainment
from .diagnose import diagnose, recommendations
from .ingest import available as available_readers
from .ingest import build_cohort
from .model import Cohort
from .report import write_dashboard, write_evaluation_form, write_record, write_workbook
from .report.record import build_record, verify_record

_LEVEL_MARK = {"pass": "  ok  ", " warn": " warn ", "fail": " FAIL "}


def _c(text: str, code: str) -> str:
    if not sys.stdout.isatty():
        return text
    return f"\033[{code}m{text}\033[0m"


def _load_config(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _resolve(base: str, path: str) -> str:
    return path if os.path.isabs(path) else os.path.normpath(os.path.join(base, path))


def _cohort_from_config(cfg: dict[str, Any], base: str, bp) -> Cohort:
    specs = []
    for s in cfg.get("sources", []):
        spec = dict(s)
        spec["path"] = _resolve(base, spec["path"])
        specs.append(spec)
    if not specs:
        raise SystemExit("config declares no sources")
    return build_cohort(bp.course.code, bp.course.term, specs)


def _print_summary(bp, result, report, recs) -> None:
    pol = bp.policy
    print()
    print(_c(f"{bp.course.name}  {bp.course.code}  {bp.course.term}", "1"))
    print(f"blueprint {bp.id}  ({bp.hash()[:12]})   students {result.n_students}")
    print("-" * 78)
    print(f"{'objective':<10}{'points':>8}{'attainment':>12}"
          f"{'95% CI':>20}{'threshold':>11}{'grade':>7}")
    for o in result.objectives:
        g = report.grades.get(o.id, "?")
        colour = {"A": "32", "B": "33", "C": "31"}.get(g, "0")
        print(f"{o.id:<10}{o.target_points:>8.2f}{o.attainment:>12.4f}"
              f"{f'[{o.ci_low:.3f}, {o.ci_high:.3f}]':>20}"
              f"{o.threshold_attainment:>11.3f}{_c(g, colour):>7}")
    print("-" * 78)
    verdict = ("meets" if result.course_attainment >= pol.qualifying_standard
               else "BELOW")
    print(f"course attainment {result.course_attainment:.4f}  "
          f"({verdict} standard {pol.qualifying_standard:.2f})")
    print(f"effective rank {report.effective_rank:.2f} of {report.n_objectives} "
          f"objectives   separation index {report.separation_index:.3f}")
    d, alt = (result.distributions.get("total"),
              result.distributions.get("total_alternate_rounding"))
    if d and alt and abs(d["mean"] - alt["mean"]) > 5e-3:
        print(f"grade distribution: mean {d['mean']:.2f} under "
              f"rounding='{d['rounding']}', {alt['mean']:.2f} under "
              f"'{alt['rounding']}' — registrar tables usually use 'integer'")

    fails = [c for c in report.checks if c.level == "fail"]
    warns = [c for c in report.checks if c.level == "warn"]
    if fails or warns:
        print()
        for ck in fails + warns:
            mark = _c("FAIL", "31") if ck.level == "fail" else _c("warn", "33")
            print(f"  [{mark}] {ck.code:<9} {ck.message}")
    if recs:
        print()
        print(_c("recommended blueprint changes", "1"))
        for i, r in enumerate(recs, 1):
            print(f"  {i}. {r}")
    print()


# --------------------------------------------------------------------------
# subcommands
# --------------------------------------------------------------------------

def cmd_run(args) -> int:
    cfg = _load_config(args.config)
    base = os.path.dirname(os.path.abspath(args.config))
    bp = load_blueprint(_resolve(base, cfg["blueprint"]))
    cohort = _cohort_from_config(cfg, base, bp)

    if args.no_per_student:
        bp.policy.include_per_student = False
    sm = build_matrix(bp, cohort, require_complete=args.require_complete)
    result = compute_attainment(bp, cohort, sm, tool_version=__version__)
    import numpy as np

    from .compute import _bootstrap
    _, _, draws = _bootstrap(sm.ratio, bp.policy.bootstrap_iterations,
                             bp.policy.bootstrap_confidence, bp.policy.seed)
    report = diagnose(
        bp, sm,
        attainment=np.array([o.attainment for o in result.objectives]),
        bootstrap_draws=draws,
        threshold=np.array([o.threshold_attainment for o in result.objectives]))
    for o in result.objectives:
        o.grade = report.grades.get(o.id, "?")
    recs = recommendations(bp, report)

    outdir = args.output
    os.makedirs(outdir, exist_ok=True)
    stem = f"{bp.course.code}_{bp.course.term}"
    paths = []
    if sm.incomplete:
        print(_c(f"note: {len(sm.incomplete)} student(s) have missing items; "
                 f"absent items are excluded, not scored as zero", "33"))
    if cohort.conflicts:
        print(_c(f"note: {len(cohort.conflicts)} value conflict(s) between sources "
                 f"(see the record)", "33"))

    paths.append(write_workbook(os.path.join(outdir, f"{stem}_达成度计算表.xlsx"),
                                bp, sm, result, report))
    paths.append(write_evaluation_form(
        os.path.join(outdir, f"{stem}_达成度评价表.docx"),
        bp, result, report, recs,
        analysis=cfg.get("analysis", ""), improvement=cfg.get("improvement", "")))
    paths.append(write_dashboard(os.path.join(outdir, f"{stem}_dashboard.html"),
                                 bp, result, report, recs,
                                 classes="、".join(cohort.classes)))
    record = build_record(result, report, cohort, bp.to_dict(), recs)
    paths.append(write_record(os.path.join(outdir, f"{stem}_record.json"), record))

    _print_summary(bp, result, report, recs)
    print("written:")
    for p in paths:
        print("  " + p)
    return 1 if report.worst_level == "fail" and args.strict else 0


def cmd_ingest(args) -> int:
    cfg = _load_config(args.config)
    base = os.path.dirname(os.path.abspath(args.config))
    bp = load_blueprint(_resolve(base, cfg["blueprint"]))
    cohort = _cohort_from_config(cfg, base, bp)
    with open(args.output, "w", encoding="utf-8") as fh:
        json.dump(cohort.to_dict(), fh, ensure_ascii=False, indent=2)
    print(f"{len(cohort.students)} students, "
          f"{len(cohort.available_keys())} source keys -> {args.output}")
    for s in cohort.sources:
        print(f"  {s.reader:<16} {s.rows:>4} rows  {s.sha256[:12]}  {s.path}")
    if cohort.conflicts:
        print(f"  {len(cohort.conflicts)} conflict(s) recorded")
    return 0


def _load_cohort(path: str) -> Cohort:
    with open(path, "r", encoding="utf-8") as fh:
        return Cohort.from_dict(json.load(fh))


def cmd_compute(args) -> int:
    bp = load_blueprint(args.blueprint)
    cohort = _load_cohort(args.cohort)
    sm = build_matrix(bp, cohort)
    result = compute_attainment(bp, cohort, sm, tool_version=__version__)
    with open(args.output, "w", encoding="utf-8") as fh:
        json.dump(result.to_dict(), fh, ensure_ascii=False, indent=2, default=str)
    print(f"course attainment {result.course_attainment:.4f} -> {args.output}")
    return 0


def cmd_diagnose(args) -> int:
    bp = load_blueprint(args.blueprint)
    cohort = _load_cohort(args.cohort)
    sm = build_matrix(bp, cohort)
    result = compute_attainment(bp, cohort, sm, tool_version=__version__)
    import numpy as np

    from .compute import _bootstrap
    _, _, draws = _bootstrap(sm.ratio, bp.policy.bootstrap_iterations,
                             bp.policy.bootstrap_confidence, bp.policy.seed)
    report = diagnose(
        bp, sm,
        attainment=np.array([o.attainment for o in result.objectives]),
        bootstrap_draws=draws,
        threshold=np.array([o.threshold_attainment for o in result.objectives]))
    recs = recommendations(bp, report)
    _print_summary(bp, result, report, recs)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            json.dump({"diagnostics": report.to_dict(), "recommendations": recs},
                      fh, ensure_ascii=False, indent=2, default=str)
    return 1 if report.worst_level == "fail" and args.strict else 0


def cmd_verify(args) -> int:
    out = verify_record(args.record, tolerance=args.tolerance)
    for f in out["findings"]:
        mark = _c("ok", "32") if f["status"] == "pass" else _c("FAIL", "31")
        extra = {k: v for k, v in f.items() if k not in ("check", "status")}
        print(f"[{mark}] {f['check']:<22} {extra}")
    print()
    print(_c("VERIFIED", "32") if out["verified"] else _c("VERIFICATION FAILED", "31"))
    return 0 if out["verified"] else 1


def cmd_report(args) -> int:
    with open(args.record, "r", encoding="utf-8") as fh:
        record = json.load(fh)
    bp = parse_blueprint(record["blueprint"], strict=False)
    os.makedirs(args.output, exist_ok=True)
    from .model import (
        AttainmentResult,
        Check,
        CourseInfo,
        DiagnosticReport,
        IndicatorResult,
        ItemStat,
        ObjectiveResult,
        Policy,
    )
    a = record["attainment"]
    result = AttainmentResult(
        blueprint_id=a["blueprint_id"], blueprint_hash=a["blueprint_hash"],
        cohort_hash=a["cohort_hash"], course=CourseInfo(**a["course"]),
        policy=Policy(**a["policy"]), method=a["method"],
        n_students=a["n_students"],
        objectives=[ObjectiveResult(**o) for o in a["objectives"]],
        indicators=[IndicatorResult(**i) for i in a["indicators"]],
        items=[ItemStat(**i) for i in a["items"]],
        course_attainment=a["course_attainment"],
        course_mean_points=a["course_mean_points"],
        per_student=a.get("per_student", []),
        distributions=a.get("distributions", {}),
        generated_at=a.get("generated_at", ""),
        tool_version=a.get("tool_version", ""))
    d = record["diagnostics"]
    report = DiagnosticReport(
        blueprint_id=d["blueprint_id"],
        checks=[Check(**c) for c in d["checks"]],
        effective_rank=d["effective_rank"],
        participation_ratio=d.get("participation_ratio", float("nan")),
        rank99=d["rank99"],
        n_objectives=d["n_objectives"], separation_index=d["separation_index"],
        between_objective_sd=d["between_objective_sd"],
        between_student_sd=d["between_student_sd"],
        correlation=d["correlation"], objective_ids=d["objective_ids"],
        grades=d["grades"], confounded_pairs=d["confounded_pairs"],
        sensitivity=d["sensitivity"])
    stem = f"{bp.course.code}_{bp.course.term}"
    p1 = write_evaluation_form(os.path.join(args.output, f"{stem}_达成度评价表.docx"),
                               bp, result, report, record.get("recommendations"))
    p2 = write_dashboard(os.path.join(args.output, f"{stem}_dashboard.html"),
                         bp, result, report, record.get("recommendations"))
    print("written:\n  " + p1 + "\n  " + p2)
    return 0


def cmd_anonymize(args) -> int:
    cohort = _load_cohort(args.cohort)
    anon, key = anonymize_cohort(cohort, key=args.key)
    cohort_to_long_csv(anon, args.output)
    print(f"{len(anon.students)} students -> {args.output}")
    print(f"key = {key}   (store separately; without it the mapping is not "
          f"reversible)")
    return 0


def cmd_blueprint(args) -> int:
    try:
        bp = load_blueprint(args.path, strict=False)
    except BlueprintError as exc:
        print(_c(str(exc), "31"))
        return 1
    problems = bp.validate(strict=False)
    print(f"{bp.id}  schema {bp.schema_version}  hash {bp.hash()[:16]}")
    print(f"  {len(bp.indicators)} indicators, {len(bp.objectives)} objectives, "
          f"{len(bp.items)} items, {bp.total_points():g} points")
    for oid, pts in bp.objective_points().items():
        srcs = {it.derived_from or it.source for it in bp.items_for_objective(oid)}
        print(f"    {oid:<8}{pts:>7.2f} pts   {len(srcs)} evidence stream(s): "
              f"{', '.join(sorted(srcs))}")
    if problems:
        print(_c("problems:", "31"))
        for p in problems:
            print("  - " + p)
        return 1
    print(_c("blueprint is structurally valid", "32"))
    return 0


def cmd_readers(args) -> int:
    for name in available_readers():
        print(name)
    return 0


# --------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="clover",
        description="Reproducible, auditable course-outcome attainment assessment.")
    p.add_argument("--version", action="version", version=f"clover {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    r = sub.add_parser("run", help="ingest, compute, diagnose and report")
    r.add_argument("--config", required=True)
    r.add_argument("-o", "--output", default="out")
    r.add_argument("--require-complete", action="store_true",
                   help="drop students with any missing item")
    r.add_argument("--strict", action="store_true",
                   help="exit non-zero if any diagnostic fails")
    r.add_argument("--no-per-student", action="store_true",
                   help="omit named per-student rows from the JSON record, so "
                        "the record can be shared without carrying identifiable "
                        "marks")
    r.set_defaults(func=cmd_run)

    i = sub.add_parser("ingest", help="merge evidence files into a cohort")
    i.add_argument("--config", required=True)
    i.add_argument("-o", "--output", default="cohort.json")
    i.set_defaults(func=cmd_ingest)

    c = sub.add_parser("compute", help="compute attainment from a cohort")
    c.add_argument("--cohort", required=True)
    c.add_argument("--blueprint", required=True)
    c.add_argument("-o", "--output", default="attainment.json")
    c.set_defaults(func=cmd_compute)

    d = sub.add_parser("diagnose", help="check whether the values are identifiable")
    d.add_argument("--cohort", required=True)
    d.add_argument("--blueprint", required=True)
    d.add_argument("-o", "--output")
    d.add_argument("--strict", action="store_true")
    d.set_defaults(func=cmd_diagnose)

    v = sub.add_parser("verify", help="re-derive a record from its inputs")
    v.add_argument("--record", required=True)
    v.add_argument("--tolerance", type=float, default=1e-6)
    v.set_defaults(func=cmd_verify)

    rp = sub.add_parser("report", help="re-render artefacts from a record")
    rp.add_argument("--record", required=True)
    rp.add_argument("-o", "--output", default="out")
    rp.set_defaults(func=cmd_report)

    a = sub.add_parser("anonymize", help="pseudonymise a cohort for sharing")
    a.add_argument("--cohort", required=True)
    a.add_argument("-o", "--output", required=True)
    a.add_argument("--key")
    a.set_defaults(func=cmd_anonymize)

    b = sub.add_parser("blueprint", help="validate and summarise a blueprint")
    b.add_argument("path")
    b.set_defaults(func=cmd_blueprint)

    rd = sub.add_parser("readers", help="list available evidence readers")
    rd.set_defaults(func=cmd_readers)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (BlueprintError, MissingEvidence) as exc:
        print(_c(str(exc), "31"), file=sys.stderr)
        return 2
    except FileNotFoundError as exc:
        print(_c(f"file not found: {exc.filename}", "31"), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
