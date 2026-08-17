# CLOVER

**C**ourse **L**earning-**O**utcome **V**alidation, **E**valuation and **R**eporting

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)

Outcome-based accreditation asks every course, every term, to report how far
each declared learning objective was attained. In practice that report is
assembled by hand in a spreadsheet, and the number it produces has three
problems that nobody checks:

* **It cannot be re-derived.** The formulas live in one workbook on one
  laptop. If a reviewer asks how 0.876 was obtained, the answer is a person's
  memory of what they typed.
* **It has no stated precision.** A cohort is a sample. Attainment printed to
  three decimals from 30 students carries the same apparent authority as the
  same figure from 300.
* **It is often not a measurement at all.** The common pattern is to take two
  aggregate marks — coursework and final — and split them across six
  objectives by fixed shares. Six numbers come out, but they are six
  rescalings of two, so they can never disagree, never fail separately, and
  cannot support the sentence "objective 3 is weak, we will strengthen it".

CLOVER makes the computation declarative and reproducible, attaches a
bootstrap interval to every figure, and — the part that matters — **checks
whether the figures are identifiable before it prints them**.

```
$ clover run --config run.yaml -o out/

objective   points  attainment              95% CI  threshold  grade
CO1          11.00      0.8745      [0.868, 0.881]      1.000      C
CO2           8.00      0.8935      [0.888, 0.899]      1.000      C
...
course attainment 0.8761  (meets standard 0.65)
effective rank 1.79 of 6 objectives   separation index 0.152

  [FAIL] ID-RANK   the 6 objective scores span an effective rank of 1.79
                   (participation ratio 1.64) and need only 2 dimension(s) to
                   explain 99% of their variance
  [FAIL] EV-AGG    every item backing CO1 is an undecomposed aggregate
  [FAIL] EV-GRP    all evidence for CO5 is group-assigned, so within-group
                   variance is zero
```

## Install

```bash
pip install clover-obe            # or: pip install clover-obe[dev]
```

Pure Python, no compilation. Runs on Linux, macOS and Windows with Python
3.10 or later. A container image is available for air-gapped sites:

```bash
docker run --rm -v "$PWD:/work" ghcr.io/SHELLY000/Clover:1.1.0 run --config /work/run.yaml -o /work/out
```

## Try it in one minute

```bash
git clone https://github.com/SHELLY000/Clover.git && cd Clover
pip install -e ".[dev]"
clover run --config examples/run-example.yaml -o out/
```

The shipped cohort is a real course — 92 undergraduates, three sections, six
objectives, 14 recorded assessment items — pseudonymised with a keyed HMAC.
The same directory carries a second blueprint over the *same* students, so
you can see what changes when points are attached to the items that were
actually recorded rather than to two aggregate marks:

```bash
clover run --config examples/run-example-itemlevel.yaml -o out-itemlevel/
```

| | as-declared | item-level |
|---|---|---|
| course attainment | 0.8761 | 0.8750 |
| effective rank / objectives | 1.79 / 6 | 4.10 / 6 |
| participation ratio | 1.64 | 3.40 |
| dimensions for 99 % of variance | 2 | 4 |
| objective separation index | 0.152 | 0.437 |
| mean \|r\| between objectives | 0.848 | 0.563 |
| identifiability grades | C C C C C C | B A B B C B |

The headline figure barely moves. What it *means* changes completely.

## How it works

Four artefacts, kept strictly apart so that each can be replaced without
touching the others:

**The blueprint** (YAML, versioned, hashed) declares the chain
`assessment item --points--> course objective --> graduation indicator`,
plus the evaluation policy. No file formats, no student names. One blueprint
is reusable across cohorts; one cohort can be re-scored under a revised
blueprint.

**Readers** turn institutional files into *source keys*. Three ship with the
tool — an item-level coursework register, a registrar transcript export, and
a portable CSV/XLSX reader. Sites register their own under the
`clover.readers` entry point without forking:

```python
# mysite/readers.py  →  entry point "sis" in group "clover.readers"
def read(path, **opts):
    return rows, keys   # rows: [{"sid", "name", "class_name", "scores": {...}}]
```

**Computation** produces attainment by the score-ratio method (评分法) and the
threshold method (合格率法), each with a percentile bootstrap interval over
students. An item a student did not sit is treated as absent, not as zero:
each student's objective ratio is normalised over the items actually
observed, then rescaled onto the full target.

Grade distributions are reported under both rounding conventions. A blueprint
total is a sum of un-rounded points; a registrar rounds each student's mark
before tabulating. The gap is small but lands on band boundaries, so both are
computed and shown rather than one being quietly preferred. Integer rounding
is half-up, not the half-to-even that NumPy applies by default — grade totals
sit on .5 constantly, and banker's rounding sends half of them the wrong way.

**Diagnostics** decide whether the figures mean what they appear to mean. Eleven checks:

| code | question |
|---|---|
| `ID-CONF` | Do two objectives draw on identical evidence in identical proportions, so that *no* data could separate them? |
| `ID-RANK` | How many independent dimensions does the objective-score matrix actually span? |
| `ID-CORR` | Which objective pairs are empirically collinear? |
| `EV-COUNT` | Is each objective backed by enough independent evidence streams? |
| `EV-AGG` | Is an objective's evidence entirely an undecomposed aggregate? |
| `EV-GRP` | Is it entirely group-assigned, so individual attainment is not individually measured? |
| `DS-CEIL` | Which items sit at the ceiling and separate nobody? |
| `DS-SEP` | Does the profile vary across objectives, or only across students? |
| `SN-LOO` | How far does an objective move if its largest item is dropped? |
| `TH-RISK` | What is the bootstrap probability of falling below the qualifying standard? |
| `TH-DEGEN` | Does the expectation level separate anybody, or does the threshold method return one value for every objective? |

Each objective is graded **A** (identified and robust), **B** (weakly
identified) or **C** (not identified from the declared evidence). A `C` is
not a statement about teaching quality — it says the number should not be
read as a measurement of that objective.

## Outputs

`clover run` writes four files:

* `..._达成度计算表.xlsx` — the institutional calculation workbook, one sheet
  per class plus a combined sheet, in the layout reviewers expect, with two
  rows the manual template does not have: the bootstrap interval and the
  identifiability grade. A fifth sheet carries the full diagnostic detail.
* `..._达成度评价表.docx` — the signed-and-archived evaluation form, generated
  rather than transcribed.
* `..._dashboard.html` — a single self-contained file: no server, no external
  assets, no network access at render time.
* `..._record.json` — the citable record: attainment, diagnostics, the
  blueprint, and the SHA-256 of every input file. Per-student rows are
  included by default; `--no-per-student` withholds them, which changes no
  reported figure and makes the record safe to circulate.

## Auditing a submitted result

```bash
$ clover verify --record out/BM0400067_2025-2026-2_record.json
[ok] source-hash            {'expected': '37996d295e56...', 'actual': '37996d295e56...'}
[ok] blueprint-hash         {'expected': '661e804d1cab...', 'actual': '661e804d1cab...'}
[ok] recompute-objectives   {'max_abs_drift': 0.0}
[ok] recompute-course       {'abs_drift': 0.0}
[ok] recompute-grades       {...}

VERIFIED
```

`verify` re-reads the named inputs with the recorded reader options,
recomputes, and compares — the point estimates, the bootstrap interval
endpoints, the identifiability grades and the diagnostic findings themselves.
Change one cell in one gradebook and it says so.

## Commands

```
clover run       --config run.yaml -o out/     ingest, compute, diagnose, report
clover ingest    --config run.yaml -o cohort.json
clover compute   --cohort c.json --blueprint b.yaml -o attainment.json
clover diagnose  --cohort c.json --blueprint b.yaml [--strict]
clover report    --record record.json -o out/  re-render without recomputing
clover verify    --record record.json
clover anonymize --cohort c.json -o example.csv
clover blueprint b.yaml                        validate and summarise
clover readers                                 list available readers
```

`--strict` makes `run` and `diagnose` exit non-zero when any diagnostic
fails, which is what you want in a CI job that guards a programme's
assessment design between terms.

## Python API

```python
from clover import load_blueprint, build_cohort, run

bp = load_blueprint("blueprints/course.yaml")
cohort = build_cohort(bp.course.code, bp.course.term, [
    {"path": "gradebook.xlsx", "reader": "wbu_gradebook", "skip_sheets": ["其他班"]},
    {"path": "transcript.xls", "reader": "wbu_transcript"},
])
result, report, recommendations = run(bp, cohort)

print(result.course_attainment)   # 0.8761
print(report.grades)              # {'CO1': 'C', ...}
print(report.effective_rank)      # 1.64
```

## Privacy

Attainment work is done on files full of named students' marks. `clover
anonymize` replaces identifiers with a keyed HMAC truncated to a fixed
width: the same student maps to the same pseudonym across files in one
release, so joins survive, but the mapping is not reversible without the key
and a different key produces an unlinkable release. Scores are left
untouched. Run it before anything leaves your machine — example datasets,
bug reports, replication packages.

## Scope and limits

* CLOVER computes and checks attainment. It does not judge whether a
  blueprint's mapping from items to objectives is pedagogically sound; that
  is a course team's decision, and the tool only asks whether the mapping is
  *identifiable* from the evidence declared.
* The diagnostics are necessary, not sufficient. A blueprint that passes
  every check can still measure the wrong thing well.
* The threshold method's expectation level and the qualifying standard are
  policy, not statistics. CLOVER reports both methods and leaves the choice
  where it belongs — but `TH-DEGEN` will tell you when the expectation level
  you chose separates nobody, in which case the threshold figure is not a
  second opinion.
* Effective rank is Roy and Vetterli's definition, the exponential of the
  entropy of the singular-value spectrum. The participation ratio of the same
  spectrum is reported next to it under its own name; the two agree at the
  extremes and weight intermediate spectra differently.

## Citing

If CLOVER contributes to published work, please cite the SoftwareX article
listed in `CITATION.cff`.

## Release checklist

`submission.yaml` holds the organisation, version, DOI and contact addresses
that appear across five files in three syntaxes. Fill it once and run:

```bash
python scripts/set_metadata.py --config submission.yaml           # rewrite
python scripts/set_metadata.py --config submission.yaml --check   # verify
```

`--check` exits non-zero while any placeholder is unfilled, so it can guard a
release in CI.

## Contributing

Rule packs, readers and translations are the most useful contributions.
Run `pytest` before opening a pull request; the diagnostic tests are
deliberately written so that a check which stops firing breaks the build.

## License

MIT — see [LICENSE](LICENSE).
