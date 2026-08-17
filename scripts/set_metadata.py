"""Replace every submission placeholder from a single source of truth.

SoftwareX requires the metadata tables to match the repository exactly. Those
values appear in the manuscript, pyproject.toml, README.md, CITATION.cff and
the Dockerfile, in five different syntaxes — which is how a version number
ends up correct in three places and stale in two.

    python scripts/set_metadata.py --config submission.yaml [--check]

``--check`` reports what would change without writing, and exits non-zero if
any placeholder is still unfilled. Wire it into CI and the release cannot go
out half-edited.
"""
from __future__ import annotations

import argparse
import os
import re
import sys

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGETS = ["pyproject.toml", "README.md", "CITATION.cff", "Dockerfile",
           "CHANGELOG.md"]
UNFILLED = re.compile(r"\bORG\b|XXXXXXX?|\[Author (One|Two|Three)\]|"
                      r"\[Department, Institution, City, Country\]")


def substitutions(cfg: dict) -> dict[str, str]:
    org, repo = cfg["org"], cfg["repo"]
    return {
        "https://github.com/ORG/clover-obe": f"https://github.com/{org}/{repo}",
        "https://ORG.github.io/clover-obe": f"https://{org}.github.io/{repo}",
        "ghcr.io/ORG/clover-obe": f"ghcr.io/{org}/{repo}",
        "https://github.com/<org>/clover-obe": f"https://github.com/{org}/{repo}",
        "https://<org>.github.io/clover-obe": f"https://{org}.github.io/{repo}",
        "ghcr.io/<org>/clover-obe": f"ghcr.io/{org}/{repo}",
        "10.5281/zenodo.XXXXXXX": cfg["doi"],
        "clover-support@institution.edu": cfg["support_email"],
        "corresponding@institution.edu": cfg["corresponding_email"],
        "[v1.0.0]": f"[v{cfg['version']}]",
    }
    

def apply(paths: list[str], subs: dict[str, str], check: bool) -> int:
    changed = 0
    for rel in paths:
        path = os.path.join(ROOT, rel)
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as fh:
            text = original = fh.read()
        for old, new in subs.items():
            text = text.replace(old, new)
        if text != original:
            changed += 1
            print(("would update " if check else "updated ") + rel)
            if not check:
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(text)
    return changed


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", default=os.path.join(ROOT, "submission.yaml"))
    ap.add_argument("--extra", nargs="*", default=[],
                    help="further files to rewrite, e.g. the manuscript")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    with open(args.config, encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)
    apply(TARGETS + args.extra, substitutions(cfg), args.check)

    remaining = []
    for rel in TARGETS + args.extra:
        path = os.path.join(ROOT, rel)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                content = fh.read()
            for m in UNFILLED.finditer(content):
                remaining.append(f"{rel}: {m.group(0)}")
    if not cfg.get("ethics_reference"):
        remaining.append("submission.yaml: ethics_reference is empty (audit A-2)")

    if remaining:
        print("\nstill unfilled:")
        for r in sorted(set(remaining)):
            print("  - " + r)
        return 1
    print("\nall submission placeholders are filled")
    return 0


if __name__ == "__main__":
    sys.exit(main())
