"""Identifiability and validity diagnostics.

An attainment report can be arithmetically correct and still be
uninformative.  The common failure is *structural*: if every objective's
score is the same linear function of the same one or two aggregate marks,
then the k reported per-objective values are k rescalings of one number.
They will differ in the third decimal, they will all clear the qualifying
standard together, and they will justify a continuous-improvement action
plan that the evidence cannot support.

This module makes that failure computable.  Each check returns a
:class:`~clover.model.Check` at level ``pass`` / ``warn`` / ``fail``:

===========  =========================================================
code         question it answers
===========  =========================================================
``ID-CONF``  Are two objectives *structurally* confounded — i.e. do
             their weight columns point the same way, so that no data
             could ever separate them?
``ID-RANK``  How many independent dimensions does the observed
             objective-score matrix actually span?
``ID-CORR``  Which objective pairs are empirically collinear?
``EV-COUNT`` Is each objective supported by enough distinct items?
``EV-AGG``   Is an objective's evidence entirely an undecomposed
             aggregate?
``EV-GRP``   Is it entirely group-assigned, so individual attainment is
             not individually measured?
``DS-CEIL``  Which items sit at the ceiling and therefore discriminate
             between nobody?
``DS-SEP``   Does between-objective variation exceed between-student
             variation, or is the profile flat?
``SN-LOO``   How much does each objective move if its single largest
             item is dropped?
``TH-RISK``  What is the bootstrap probability of falling below the
             qualifying standard?
``TH-DEGEN`` Does the expectation level separate anybody, or does the
             threshold method return the same value for every objective?
===========  =========================================================

The per-objective **grade** condenses these: ``A`` identified and
robust, ``B`` weakly identified, ``C`` not identified from the evidence
declared.  A ``C`` does not mean the teaching was poor; it means the
number should not be read as a measurement of that objective.
"""

from __future__ import annotations

import numpy as np

from .blueprint import Blueprint
from .compute import ScoreMatrix
from .model import Check, DiagnosticReport

_EPS = 1e-12


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _effective_rank(S: np.ndarray) -> tuple[float, float, int, np.ndarray]:
    """Effective rank, participation ratio, and the 99 %-variance rank.

    The effective rank is Roy and Vetterli's definition: the exponential of
    the Shannon entropy of the singular-value distribution, ``exp(H(p))``
    with ``p_i = s_i / sum_j s_j``.  It is the quantity that carries that
    name in the literature, so it is the one reported.

    The participation ratio ``(sum s)^2 / sum s^2`` is computed alongside it.
    The two agree on the extremes — both give 1 for a rank-one matrix and k
    for k equal singular values — but they weight intermediate spectra
    differently, the participation ratio more harshly.  Reporting both, under
    their own names, avoids the error of quoting one and citing the other.
    """
    Sc = S - S.mean(axis=0, keepdims=True)
    if Sc.shape[0] < 2:
        return 1.0, 1.0, 1, np.zeros(S.shape[1])
    sv = np.linalg.svd(Sc, compute_uv=False)
    sv = sv[sv > _EPS * max(sv.max(), 1.0)]
    if sv.size == 0:
        return 0.0, 0.0, 0, np.zeros(S.shape[1])
    p = sv / sv.sum()
    er = float(np.exp(-np.sum(p * np.log(p))))
    pr = float(sv.sum() ** 2 / (sv ** 2).sum())
    var = sv ** 2 / (sv ** 2).sum()
    rank99 = int(np.searchsorted(np.cumsum(var), 0.99) + 1)
    return er, pr, rank99, var


def _safe_corr(S: np.ndarray) -> np.ndarray:
    k = S.shape[1]
    C = np.eye(k)
    sd = S.std(axis=0)
    for a in range(k):
        for b in range(a + 1, k):
            if sd[a] < _EPS or sd[b] < _EPS:
                C[a, b] = C[b, a] = np.nan
            else:
                C[a, b] = C[b, a] = float(np.corrcoef(S[:, a], S[:, b])[0, 1])
    return C


def _column_cosine(W: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(W, axis=0)
    norms = np.where(norms < _EPS, 1.0, norms)
    U = W / norms
    return U.T @ U


def _evidence_signature(bp: Blueprint, oid: str) -> frozenset[str]:
    """The set of *independent* evidence streams backing an objective.

    Items derived from the same undecomposed aggregate collapse to one
    signature entry, which is precisely why they cannot separate the
    objectives they feed.
    """
    sig = set()
    for it in bp.items_for_objective(oid):
        sig.add(it.derived_from or it.source)
    return frozenset(sig)


# --------------------------------------------------------------------------
# main entry point
# --------------------------------------------------------------------------

def diagnose(bp: Blueprint, sm: ScoreMatrix,
             attainment: np.ndarray | None = None,
             bootstrap_draws: np.ndarray | None = None,
             threshold: np.ndarray | None = None) -> DiagnosticReport:
    checks: list[Check] = []
    oids = sm.objective_ids
    k = len(oids)
    S = sm.ratio
    W = sm.W
    pol = bp.policy

    # ---- ID-CONF: structural confounding -------------------------------
    cos = _column_cosine(W)
    confounded: list[list[str]] = []
    for a in range(k):
        for b in range(a + 1, k):
            if cos[a, b] > 1 - 1e-9:
                confounded.append([oids[a], oids[b]])
    if confounded:
        for pair in confounded:
            checks.append(Check(
                "ID-CONF", "fail", f"objective:{pair[0]}",
                f"{pair[0]} and {pair[1]} draw on identical evidence in identical "
                f"proportions; their attainment values are the same number twice "
                f"and no amount of data can separate them",
                value=pair))
    else:
        checks.append(Check("ID-CONF", "pass", "blueprint",
                            "no two objectives have proportional weight columns",
                            value=float(np.max(cos - np.eye(k)))))

    # ---- ID-RANK: dimensionality actually spanned -----------------------
    er, pr, rank99, var = _effective_rank(S)
    half = int(np.ceil(k / 2))
    degenerate = k > 1 and (er < 1.5 or rank99 < half)
    if degenerate:
        level = "fail"
        msg = (f"the {k} objective scores span an effective rank of {er:.2f} and "
               f"(participation ratio {pr:.2f}) and need only {rank99} "
               f"dimension(s) to explain 99% of their variance; "
               f"they are a handful of aggregate marks re-expressed {k} ways")
    elif er < 0.5 * k:
        level = "warn"
        msg = (f"effective rank {er:.2f} against {k} declared objectives; "
               f"the objectives are far less independent than the blueprint implies")
    else:
        level = "pass"
        msg = f"effective rank {er:.2f} against {k} declared objectives"
    checks.append(Check("ID-RANK", level, "blueprint", msg,
                        value={"effective_rank": er, "participation_ratio": pr,
                               "rank99": rank99,
                               "variance_ratio": [float(x) for x in var]}))

    # ---- ID-CORR: empirical collinearity --------------------------------
    C = _safe_corr(S)
    off = [abs(C[a, b]) for a in range(k) for b in range(a + 1, k)
           if not np.isnan(C[a, b])]
    mean_off = float(np.mean(off)) if off else float("nan")
    for a in range(k):
        for b in range(a + 1, k):
            r = C[a, b]
            if np.isnan(r):
                continue
            if abs(r) >= pol.collinearity_fail and [oids[a], oids[b]] not in confounded:
                checks.append(Check(
                    "ID-CORR", "fail", f"objective:{oids[a]}",
                    f"{oids[a]} and {oids[b]} correlate at r={r:.3f} across students; "
                    f"reporting them as distinct attainment values overstates what "
                    f"was measured", value=float(r)))
            elif abs(r) >= pol.collinearity_warn:
                checks.append(Check(
                    "ID-CORR", "warn", f"objective:{oids[a]}",
                    f"{oids[a]} and {oids[b]} correlate at r={r:.3f}",
                    value=float(r)))
    separation = float(1.0 - mean_off) if off else float("nan")

    # ---- EV-COUNT / EV-AGG / EV-GRP -------------------------------------
    for oid in oids:
        items = bp.items_for_objective(oid)
        sig = _evidence_signature(bp, oid)
        if len(sig) < pol.min_items_per_objective:
            checks.append(Check(
                "EV-COUNT", "warn" if len(sig) == 1 else "fail",
                f"objective:{oid}",
                f"{oid} rests on {len(sig)} independent evidence stream(s) "
                f"({', '.join(sorted(sig))}); at least "
                f"{pol.min_items_per_objective} are needed for a defensible claim",
                value=len(sig)))
        if items and all(it.aggregate for it in items):
            checks.append(Check(
                "EV-AGG", "fail", f"objective:{oid}",
                f"every item backing {oid} is an undecomposed aggregate; the value "
                f"reported for {oid} is a share of a mark that was never awarded "
                f"per objective", value=[it.id for it in items]))
        if items and all(it.group_assigned for it in items):
            checks.append(Check(
                "EV-GRP", "fail", f"objective:{oid}",
                f"all evidence for {oid} is group-assigned, so within-group "
                f"variance is zero and individual attainment is not individually "
                f"measured", value=[it.id for it in items]))

    # ---- DS-CEIL: ceiling effects ---------------------------------------
    ceiling_pts = 0.0
    for i, it in enumerate(bp.items):
        col = sm.R[:, i]
        col = col[~np.isnan(col)]
        if col.size == 0:
            continue
        marks = col * it.full_mark
        if col.mean() >= pol.ceiling_ratio and marks.std() <= pol.ceiling_sd:
            ceiling_pts += it.points
            checks.append(Check(
                "DS-CEIL", "warn", f"item:{it.id}",
                f"{it.name} sits at the ceiling (mean {col.mean() * 100:.1f}%, "
                f"sd {marks.std():.1f}); it separates almost no students",
                value={"mean_ratio": float(col.mean()), "sd": float(marks.std())}))
    if ceiling_pts > 0:
        share = ceiling_pts / max(bp.total_points(), _EPS)
        checks.append(Check(
            "DS-CEIL", "fail" if share > 0.4 else "warn", "blueprint",
            f"{share * 100:.0f}% of the 100-point scale is carried by items at the "
            f"ceiling; attainment on those points is nearly constant by construction",
            value=float(share)))

    # ---- DS-SEP: is the objective profile flat? --------------------------
    per_student_spread = float(np.nanmean(np.nanstd(S, axis=1)))
    between_student = float(np.nanstd(np.nanmean(S, axis=1)))
    if per_student_spread < 0.5 * between_student:
        checks.append(Check(
            "DS-SEP", "warn", "blueprint",
            f"within-student spread across objectives ({per_student_spread:.4f}) is "
            f"small next to between-student spread ({between_student:.4f}); the "
            f"report describes students, not objectives",
            value={"between_objective_sd": per_student_spread,
                   "between_student_sd": between_student}))
    else:
        checks.append(Check(
            "DS-SEP", "pass", "blueprint",
            f"objective profiles vary within students "
            f"(sd {per_student_spread:.4f})",
            value={"between_objective_sd": per_student_spread,
                   "between_student_sd": between_student}))

    # ---- SN-LOO: leave-one-item-out sensitivity ---------------------------
    sensitivity: dict[str, float] = {}
    base = np.nanmean(S, axis=0)
    for j, oid in enumerate(oids):
        idx = [i for i in range(len(bp.items)) if W[i, j] > 0]
        if len(idx) < 2:
            # Dropping the only item leaves nothing to compute; that is a
            # coverage problem, already reported by EV-COUNT, not a
            # sensitivity of 1.0.
            sensitivity[oid] = float("nan")
            continue
        worst = 0.0
        for drop in idx:
            keep = [i for i in idx if i != drop]
            if W[keep, j].sum() <= 0:
                worst = max(worst, 1.0)
                continue
            filled = np.where(sm.mask[:, keep], sm.R[:, keep], 0.0)
            tgt = sm.mask[:, keep].astype(float) @ W[keep, j]
            with np.errstate(divide="ignore", invalid="ignore"):
                col = np.where(tgt > 0, (filled @ W[keep, j]) / tgt, np.nan)
            alt = float(np.nanmean(col))
            worst = max(worst, abs(alt - base[j]))
        sensitivity[oid] = worst
        if worst > 0.05:
            checks.append(Check(
                "SN-LOO", "warn", f"objective:{oid}",
                f"dropping a single item moves {oid} by {worst:.3f}; the value is "
                f"dominated by one piece of evidence", value=worst))

    # ---- TH-RISK: distance from the qualifying standard --------------------
    if attainment is not None:
        for j, oid in enumerate(oids):
            a = float(attainment[j])
            margin = a - pol.qualifying_standard
            if a < pol.qualifying_standard:
                checks.append(Check(
                    "TH-RISK", "fail", f"objective:{oid}",
                    f"{oid} attainment {a:.3f} is below the qualifying standard "
                    f"{pol.qualifying_standard:.2f}", value=a))
            elif bootstrap_draws is not None and bootstrap_draws.ndim == 2:
                p = float((bootstrap_draws[:, j] < pol.qualifying_standard).mean())
                if p > 0.05:
                    checks.append(Check(
                        "TH-RISK", "warn", f"objective:{oid}",
                        f"{oid} clears the standard by {margin:.3f}, but the "
                        f"bootstrap puts {p * 100:.1f}% of resamples below it",
                        value=p))

    # ---- TH-DEGEN: does the expectation level separate anyone? -------------
    if threshold is None:
        threshold = (S >= pol.expectation_level).mean(axis=0)
    thr = np.asarray(threshold, dtype=float)
    if thr.size and (np.allclose(thr, 1.0) or np.allclose(thr, 0.0)):
        edge = "above" if np.allclose(thr, 1.0) else "below"
        checks.append(Check(
            "TH-DEGEN", "warn", "blueprint",
            f"the threshold method returns {thr[0]:.3f} for every objective: at an "
            f"expectation level of {pol.expectation_level:.2f} every student sits "
            f"{edge} the line, so this method carries no information about this "
            f"cohort and should not be quoted as a second, independent estimate",
            value=float(thr[0])))
    else:
        checks.append(Check(
            "TH-DEGEN", "pass", "blueprint",
            f"the threshold method separates students at expectation level "
            f"{pol.expectation_level:.2f} (range "
            f"{thr.min():.3f}–{thr.max():.3f})",
            value=[float(x) for x in thr]))

    # ---- grades ------------------------------------------------------------
    grades: dict[str, str] = {}
    for oid in oids:
        rel = [c for c in checks if c.scope == f"objective:{oid}"]
        codes_fail = {c.code for c in rel if c.level == "fail"}
        codes_warn = {c.code for c in rel if c.level == "warn"}
        if codes_fail & {"ID-CONF", "EV-AGG", "EV-GRP", "ID-CORR"}:
            grades[oid] = "C"
        elif codes_warn or codes_fail:
            grades[oid] = "B"
        else:
            grades[oid] = "A"
    if degenerate:
        grades = {oid: "C" for oid in oids}

    return DiagnosticReport(
        blueprint_id=bp.id,
        checks=checks,
        effective_rank=er,
        participation_ratio=pr,
        rank99=rank99,
        n_objectives=k,
        separation_index=separation,
        between_objective_sd=per_student_spread,
        between_student_sd=between_student,
        correlation=[[None if np.isnan(x) else round(float(x), 4) for x in row]
                     for row in C],
        objective_ids=list(oids),
        grades=grades,
        confounded_pairs=confounded,
        sensitivity={k_: (None if np.isnan(v) else round(v, 5))
                     for k_, v in sensitivity.items()},
    )


def recommendations(bp: Blueprint, report: DiagnosticReport) -> list[str]:
    """Turn findings into concrete, actionable blueprint changes.

    Grouped by cause rather than listed per objective: an instructor
    reading eleven variations of "record the rubric separately" will act
    on none of them, whereas one line naming all the affected objectives
    is a change that can actually be made before next term.
    """
    out: list[str] = []
    codes = {(c.code, c.scope) for c in report.checks if c.level == "fail"}

    agg = sorted({s.split(":", 1)[1] for code, s in codes if code == "EV-AGG"})
    grp = sorted({s.split(":", 1)[1] for code, s in codes if code == "EV-GRP"})
    thin = sorted({c.scope.split(":", 1)[1] for c in report.checks
                   if c.code == "EV-COUNT"})

    if agg:
        sources = sorted({(it.name) for oid in agg
                          for it in bp.items_for_objective(oid) if it.aggregate})
        out.append(
            f"为 {'、'.join(sources)} 按评分标准的各维度分别记分，而不是只记合成总分。"
            f"这一项改动可同时使 {'、'.join(agg)} 摆脱“聚合分固定比例分解”的状态，"
            f"是本轮诊断中投入最小、收益最大的一处。")
    if grp:
        out.append(
            f"为 {'、'.join(grp)} 增加一项按个人评定的证据（报告中由本人独立完成的章节、"
            f"或答辩个人得分），否则同组成员在这些目标上的达成度恒等，无法反映个体差异。")
    only_thin = [o for o in thin if o not in agg and o not in grp]
    if only_thin:
        out.append(
            f"{'、'.join(only_thin)} 目前仅有一条独立证据支撑，建议增设第二个考核项，"
            f"使该目标的达成结论不依赖单一材料。")

    ceiling = [c for c in report.checks
               if c.code == "DS-CEIL" and c.scope.startswith("item:")]
    if ceiling:
        names = [c.scope.split(":", 1)[1] for c in ceiling]
        out.append(
            f"{len(ceiling)} 个考核项处于天花板（{'、'.join(names[:6])}"
            f"{' 等' if len(names) > 6 else ''}），几乎不区分学生。"
            f"或收紧评分标准使最高档确实不易获得，或将这部分分值移到有区分度的考核项上。")

    if report.rank99 < int(np.ceil(report.n_objectives / 2)) or report.effective_rank < 1.5:
        out.append(
            f"在上述改动落地之前，{report.n_objectives} 个课程目标的达成值实际只有 "
            f"{report.rank99} 个自由度，建议在评价表中以课程整体达成度为结论，"
            f"各目标值标注为分解结果而非独立测量，避免据此得出“某目标薄弱”的改进意见。")
    return out
