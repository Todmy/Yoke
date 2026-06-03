#!/usr/bin/env python3
"""Skill-gap analysis for a role (US3, FR-011/012/013/014).

Deterministic core (no required model call): match the role's JD against the
user's CV via a curated skill taxonomy + aliases, return matched skills and
missing skills ranked by how central they are to the role, plus an honestly-
framed match indicator (a qualitative band + a number, NOT an ATS-beating score).

When a model is available, `--suggest` adds: how to learn each genuinely-missing
skill, and accept/reject bullet edits ONLY for skills the CV already supports —
never fabricating a skill, tool, metric, or seniority the CV does not contain.

  gap.py <role_key|url|substring>        # deterministic gap vs the base CV
  gap.py <role> --json                   # machine-readable
  gap.py <role> --suggest                # + model-backed learning/tuning (needs a provider)

CLI-first; serve.py reuses compute_gap(). Stdlib only.
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from paths import load_profile, INDEX, JD_CACHE  # noqa: E402

_SKILLS_FILE = Path(__file__).resolve().parent / "data" / "skills.json"


def load_taxonomy():
    data = json.loads(_SKILLS_FILE.read_text())
    return data["skills"]


def _present(text, aliases):
    """True if any alias appears as a word-ish token in the (lowercased) text."""
    t = f" {re.sub(r'[^a-z0-9+/. ]', ' ', text.lower())} "
    for a in aliases:
        a = a.strip().lower()
        if not a:
            continue
        # word-boundary-ish: surround single tokens with spaces; substrings for multiword
        if " " in a or "/" in a or "." in a:
            if a in text.lower():
                return True
        elif f" {a} " in t:
            return True
    return False


def extract_skills(text, taxonomy=None):
    """Canonical skills whose aliases appear in `text`. Deterministic, no model."""
    taxonomy = taxonomy or load_taxonomy()
    return {s["name"]: s for s in taxonomy if _present(text or "", s["aliases"])}


def _centrality(skill, jd_text):
    """How central a skill is to the role: alias hit-count in the JD (cheap proxy)."""
    t = (jd_text or "").lower()
    return max(1, sum(t.count(a.strip().lower()) for a in skill["aliases"] if a.strip()))


def compute_gap(jd_text, cv_text, taxonomy=None):
    """Deterministic matched/missing skills + honest match indicator.

    matched  = skills the role calls for that the CV shows
    missing  = skills the role calls for that the CV does NOT show (ranked, central first)
    band/score = relevance signal for a HUMAN reader, never a claim about ATS.
    """
    taxonomy = taxonomy or load_taxonomy()
    role_skills = extract_skills(jd_text, taxonomy)
    cv_skills = extract_skills(cv_text, taxonomy)
    matched = [n for n in role_skills if n in cv_skills]
    missing = [n for n in role_skills if n not in cv_skills]
    missing.sort(key=lambda n: _centrality(role_skills[n], jd_text), reverse=True)
    required = len(role_skills)
    score = round(100 * len(matched) / required) if required else 0
    band = "Strong" if score >= 70 else "Moderate" if score >= 40 else "Weak"
    return {
        "matched": matched,
        "missing": [{"skill": n, "category": role_skills[n]["category"]} for n in missing],
        "required_count": required,
        "match_score": score,            # number, shown on expand
        "match_band": band,              # the headline (relevance, not ATS — FR-014)
        "indicator_note": "relevance signal for a human reader — not a prediction of beating automated screening",
    }


# ── role lookup (index + JD cache) ───────────────────────────────────────────
def _find_role(needle):
    idx = json.loads(INDEX.read_text()) if INDEX.exists() else {}
    n = needle.lower()
    for k, v in idx.items():
        hay = f"{k} {v.get('company','')} {v.get('title','')} {v.get('role_key','')}".lower()
        if n in hay:
            return k, v
    return None, None


def _jd_text(url):
    import hashlib
    p = JD_CACHE / (hashlib.sha1((url or "").encode()).hexdigest() + ".json")
    if p.exists():
        try:
            return json.loads(p.read_text()).get("description", "")
        except (json.JSONDecodeError, OSError):
            return ""
    return ""


def _cv_text():
    prof = load_profile()
    return (prof.get("resume_text") or "") + "\n" + (prof.get("prompt") or "")


# ── optional model-backed suggestions (FR-012/013/014) ───────────────────────
def suggest(gap, jd_text, cv_text):
    """Learning paths for missing skills + accept/reject tuning bullets for skills
    the CV ALREADY supports. Truthfulness-guarded: the prompt forbids inventing
    anything not in the CV. Returns the raw model text (the human accepts/rejects)."""
    from llm import get_backend
    be = get_backend()
    sys_prompt = (
        "You help a candidate close the gap for ONE role, truthfully. RULES:\n"
        "- NEVER invent a skill, tool, certification, metric, or seniority the CV does not contain.\n"
        "- For MISSING skills: suggest only how to learn them (resource + a first step). Do not claim the candidate has them.\n"
        "- For tuning the CV: propose rephrasings ONLY for skills already present in the CV, to surface genuine relevance. Each as an accept/reject bullet.\n"
        "- Frame any match as relevance for a human reader, never as beating an ATS.")
    prompt = (f"CV:\n{cv_text}\n\nROLE (JD excerpt):\n{jd_text[:2000]}\n\n"
              f"Matched skills: {', '.join(gap['matched']) or '(none)'}\n"
              f"Missing skills (central first): {', '.join(m['skill'] for m in gap['missing']) or '(none)'}\n\n"
              "Output two sections: (1) Learn (per missing skill) (2) Tune CV (accept/reject bullets, "
              "only for skills already in the CV).")
    return be.complete(prompt, system=sys_prompt)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("role", help="role_key / url / company-or-title substring")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--suggest", action="store_true", help="add model-backed learning/tuning (needs a provider)")
    a = ap.parse_args()

    key, entry = _find_role(a.role)
    if not entry:
        print(f"gap: no role matched '{a.role}' in the index", file=sys.stderr)
        sys.exit(2)
    jd = _jd_text(entry.get("url") or key)
    jd_for_match = jd or f"{entry.get('title','')} {entry.get('company','')}"
    cv = _cv_text()
    gap = compute_gap(jd_for_match, cv)

    if a.json and not a.suggest:
        print(json.dumps(gap, ensure_ascii=False, indent=2))
        return

    print(f"{entry.get('company')} — {entry.get('title')}")
    print(f"Match: {gap['match_band']} ({gap['match_score']}% of {gap['required_count']} role skills) "
          f"— {gap['indicator_note']}")
    print(f"Matched: {', '.join(gap['matched']) or '(none)'}")
    print("Missing (most central first):")
    for m in gap["missing"]:
        print(f"  - {m['skill']} [{m['category']}]")
    if not jd:
        print("\n(no JD text cached — matched on title/company only; paste the JD for a fuller gap)",
              file=sys.stderr)
    if a.suggest:
        try:
            print("\n── suggestions (accept/reject; nothing is auto-applied) ──")
            print(suggest(gap, jd_for_match, cv))
        except Exception as e:
            print(f"gap: suggestions need a configured provider ({type(e).__name__}: {e})", file=sys.stderr)
            sys.exit(2)


if __name__ == "__main__":
    main()
