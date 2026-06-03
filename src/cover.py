#!/usr/bin/env python3
"""Standalone per-vacancy cover-letter draft (US3, FR-026).

Draft only — grounded ONLY in the CV and the role's JD, in the profile's output
language. The human accepts/rejects/edits; Yoke never sends it and never
fabricates a skill, experience, or claim absent from the CV.

  cover.py <role_key|url|substring>          # draft to stdout
  cover.py <role> --out letter.txt           # also write to a file

Stdlib only; reuses the configured LLM backend and the gap role lookup.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from paths import load_profile  # noqa: E402
import gap as gapmod  # noqa: E402  (role lookup + JD/CV helpers)

_SYSTEM = (
    "You draft a concise, specific cover letter for ONE role. HARD RULES:\n"
    "- Use ONLY facts present in the CV. NEVER invent a skill, employer, tool, metric, "
    "certification, or seniority the CV does not contain.\n"
    "- Map the candidate's REAL experience to the role's needs; if the CV lacks something the "
    "role wants, do not claim it — omit it.\n"
    "- 200-280 words, no salutational fluff, no invented numbers. Output in {lang}.\n"
    "- This is a draft for the human to edit and send themselves.")


def build_prompt(cv_text, jd_text, company, title):
    return (f"Role: {title} at {company}\n\nJob description (excerpt):\n{jd_text[:2500]}\n\n"
            f"Candidate CV:\n{cv_text}\n\nDraft the cover letter now.")


def draft(cv_text, jd_text, company, title, lang="en"):
    from llm import get_backend
    be = get_backend()
    return be.complete(build_prompt(cv_text, jd_text, company, title),
                       system=_SYSTEM.replace("{lang}", lang or "en"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("role", help="role_key / url / company-or-title substring")
    ap.add_argument("--out", help="also write the draft to this file")
    a = ap.parse_args()

    key, entry = gapmod._find_role(a.role)
    if not entry:
        print(f"cover: no role matched '{a.role}' in the index", file=sys.stderr)
        sys.exit(2)
    cv = gapmod._cv_text()
    jd = gapmod._jd_text(entry.get("url") or key) or f"{entry.get('title','')} at {entry.get('company','')}"
    lang = (load_profile().get("output_language") or "en")
    try:
        text = draft(cv, jd, entry.get("company"), entry.get("title"), lang)
    except Exception as e:
        print(f"cover: needs a configured provider ({type(e).__name__}: {e})", file=sys.stderr)
        sys.exit(2)
    print(text)
    if a.out:
        Path(a.out).write_text(text)
        print(f"\n(draft written to {a.out} — review and edit before sending)", file=sys.stderr)


if __name__ == "__main__":
    main()
