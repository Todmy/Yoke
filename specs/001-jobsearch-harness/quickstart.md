# Quickstart: Yoke v1

Goal (SC-001): from an empty setup to a scored board **in one session, no hand-editing of config files**. Everything below is CLI; the web panel mirrors it.

## Prerequisites
- Python 3 (no third-party install needed for the core).
- Optional: a `.venv` with `jobspy` if you want the LinkedIn source.
- One of: a Claude subscription (`claude -p`, set `CLAUDE_CODE_OAUTH_TOKEN`), or an API key (`YOKE_PROVIDER=openai|groq|together|openrouter` + key), or a local model (`YOKE_PROVIDER=ollama|lmstudio`). For a dry run, none.

## 1. Profile (ICP default — R9)
```
python3 src/serve.py --open        # → /profile : paste your CV, confirm the UA-IT-remote preset
# or copy config/profile.example.json → $YOKE_HOME/config/profile.json and paste resume_text
```
The shipped preset (lane, remote/UA locations, comp floor, output language) means you do **not** hand-edit JSON to get a first board.

## 2. Prove the deterministic path with no model (SC-002)
```
python3 src/collect.py --dry-run            # see roles being pulled + deduped
python3 src/prepare.py < roles.json | python3 src/analyze.py --mock --no-board
# → tier counts (A/B/C); ~¼ decided by rules with zero model calls; no provider needed
```

## 3. Real scored board (provider configured)
```
src/run.sh all                               # collect → prepare → analyze → board
python3 src/board.py render                  # Tier A/B with fit band+number, geo, one-line reason
```

## 4. Triage → tracker (FR-007/009/010)
```
python3 src/board.py apply <role_key>        # review → record CV/notes → confirm; snapshots the CV sent
python3 src/board.py drop  <role_key> --reason "comp too low"
python3 src/board.py status                  # funnel: response / interview / offer rates
```
Re-run `collect`: an applied/rejected role never returns, even reposted under a new URL.

## 5. Gap, tailor, cover (US3)
```
python3 src/gap.py <role_key>                # matched/missing skills + honest match band + accept/reject edits
python3 src/cover.py <role_key>              # cover-letter draft (output language), grounded only in CV+JD
```
Accepted tailoring edits produce the per-application CV copy that `apply` snapshots. (Named variant library + live editor = v2.)

## 6. Trust & improve (US4)
```
python3 src/eval.py                          # scorecard vs frozen golden labels; safety gates dominate
python3 src/tune.py                          # before/after agreement on your applied-vs-rejected labels
python3 src/tune.py --apply                  # persist refit weights (declines below 5 applied / 5 rejected / 20 total)
```

## Acceptance smoke (maps to SCs)
- [ ] SC-001: steps 1→3 reach a board in one session, no config hand-editing.
- [ ] SC-002: step 2 runs with no provider; ~¼ roles rules-decided.
- [ ] SC-005: applied role absent after re-collect (step 4).
- [ ] SC-003: `eval` always emits a scorecard; a seeded geo-FP forces fail.
- [ ] SC-004: `tune` shows before/after on seeded labels; declines below the gate.
- [ ] SC-006: `gap` asserts no skill absent from the CV.
- [ ] SC-008: every step above is a CLI command; the web panel exposes nothing more.
