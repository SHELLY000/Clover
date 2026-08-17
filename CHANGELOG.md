# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

## [1.1.0] — 2026-08-16

Everything in this release comes from the independent audit of 1.0.0. The
attainment values it produces are unchanged; what changed is what it tells you
about them, and one methodological error that the audit's reference check
uncovered.

### Fixed
- **Effective rank was computed as the participation ratio while citing Roy and
  Vetterli, who define it as the exponential of the entropy of the singular-value
  spectrum.** These are different quantities. The cited definition is now the one
  computed and reported; the participation ratio is reported alongside it under
  its own name. On the reference cohort the reported figure moves from 1.64 to
  1.79, and the conclusion drawn from it is unchanged.
- **Integer rounding of grade totals used NumPy's half-to-even default.** Grade
  totals land on .5 constantly — 44 of 92 students in the reference cohort — so
  banker's rounding sent half of them down and shifted the cohort mean by 0.16
  marks. Rounding is now half-up, and the generated form reproduces the
  registrar's overall mark for every student individually.
- `derived_from` was accepted without validation, so a typo silently disabled the
  evidence-collapsing logic in the diagnostics. Dangling references are now
  rejected.

### Added
- `TH-DEGEN` — an eleventh check. When every student in the cohort falls on the
  same side of the expectation level, the threshold method returns one value for
  every objective and must not be quoted as independent corroboration.
- Grade distributions are reported under both rounding conventions, side by side,
  in the terminal summary, the evaluation form and the record.
- `--no-per-student` withholds named per-student rows from the JSON record. No
  reported figure changes; the record becomes safe to circulate.
- `AttainmentResult.incomplete` — students with missing items are now named in the
  record, not only mentioned in the terminal.
- `scripts/set_metadata.py` and `submission.yaml`: one source of truth for the
  submission metadata that appears across five files, with a `--check` mode for CI.
- The registrar-transcript reader accepts `.xlsx` as well as legacy `.xls`, which
  is what makes it testable.
- Fixtures and tests for both institutional readers, including block-width
  discovery across sections and detection of register/transcript disagreement.

### Changed
- `verify` now compares bootstrap interval endpoints and the diagnostic findings
  themselves, not only the point estimates and the grades. An unseeded bootstrap
  would have reproduced the estimate exactly and the interval not at all.
- Test count 18 → 30. `ruff check` is clean; the two remaining broad excepts are
  annotated with the reason they are deliberate.

## [1.0.0] — 2026-08-16

First public release.

### Added
- Declarative, versioned and content-hashed assessment blueprints (YAML).
- Evidence readers for an item-level coursework register, a legacy registrar
  transcript export, and portable CSV/XLSX in long or wide layout; third-party
  readers register under the `clover.readers` entry point.
- Attainment computation by the score-ratio and threshold methods, each with a
  seeded percentile bootstrap interval over students.
- Ten validity checks (`ID-CONF`, `ID-RANK`, `ID-CORR`, `EV-COUNT`, `EV-AGG`,
  `EV-GRP`, `DS-CEIL`, `DS-SEP`, `SN-LOO`, `TH-RISK`) with per-objective
  identifiability grades and generated remediation advice.
- Output artefacts: institutional calculation workbook (XLSX), evaluation form
  (DOCX), single-file static dashboard (HTML), and a signed JSON record.
- `clover verify` — re-reads inputs by recorded hash and reader options,
  recomputes, and reports drift.
- `clover anonymize` — keyed-HMAC pseudonymisation for safe data release.
- Pseudonymised 92-student replication cohort with two contrasting blueprints.

### Notes
- Absent items are handled by available-case normalisation, never by
  zero-filling; a missing assignment is a data-collection problem, not a low
  attainment value.
