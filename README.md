# Yoke

Yoke is a job-search harness you run on your own machine. It pulls roles from across the web, scores each one against your CV with an LLM, and keeps a live board of what's actually worth your time. The more you use it, the better its scoring fits your taste — because it learns from the decisions you make, not from a stranger's idea of a good job.

It isn't a job board, and it isn't a chat wrapper. It's a harness: a rig you run over the market, with an evaluation loop wrapped around the model so you can trust — and improve — what it tells you.

## Why it exists

Most "AI job search" tools are a prompt and a hope. You paste your CV, a model says nice things, and you have no idea why a role scored well or whether the next run will agree with the last. Yoke takes the opposite stance:

- **Local-first.** Your CV and your decisions stay on your machine. Run it against a cloud model or a local one (Ollama, LM Studio) — your call.
- **Deterministic where it can be.** Roughly a quarter of roles are decided by plain rules (lane, geo, hard blockers) and never touch a model. The model only fills a narrow set of features; a transparent formula turns those into the score. You can read the formula.
- **Self-improving from your labels.** You mark roles applied or rejected from the CLI (`yoke apply` / `yoke drop`). Those become the ground truth. `yoke tune` refits the scoring weights to *your* decisions — so it converges on what you'd pick, not on what the model guesses. It proposes the refit as a diff you apply; it never rewrites your profile behind your back.
- **Honest about uncertainty.** `yoke eval` scores the model against a frozen golden set and flags geo false-positives and other unsafe calls — safety first — before you waste an application on them.

## How it works

```
collect   pull roles (company ATS, RSS boards, HN, search dorks, optional LinkedIn)
   ↓
prepare   deterministic feature cards — geo / lane / comp decided by rules, no LLM
   ↓
analyze   the model fills a few features; a weighted formula computes fit + tier
   ↓
board     a live, self-pruning shortlist (SHORTLIST.md); triage from the CLI (apply / drop)
   ↓
eval      score the model vs a frozen golden set — safety gates dominate, per-dimension diagnostics
tune      propose refit weights from your real applied/rejected labels (a diff you apply)
```

The model surface is deliberately small: it extracts features and writes a one-line note, nothing more. Everything around it — windowing, dedup, scoring math, the board, the labels — is ordinary code you can audit.

## Under the hood

Yoke is a job-search harness — but the scoring loop inside it carries the kind of evaluation discipline you'd want around any model decision in production:

- **Evaluation harness with a golden set.** `eval.py` scores the current model against a frozen, human-reviewed golden set — with **zero model calls at scoring time** (you capture the model's take once via `yoke eval --record`, then score it offline). Safety gates dominate the verdict — a wrong "remote" call or a hallucinated requirement counts far more than a fit-score being a few points off — and a per-dimension breakdown tells you *which* part of the process is weak (comp estimation, red-flag detection, geo), not just that something is.
- **A regression gate, not vibes.** Before trusting a cheaper or faster model you run the golden set and read the numbers. The model gets downgraded on evidence, not hope.
- **Deterministic core, thin AI surface.** About a quarter of roles are decided by rules and never call a model. The model fills a fixed feature schema; a weighted formula you can read turns those features into the score — so the score is stable and auditable, not a black box.
- **The tuner proposes, you decide.** Your real apply/reject labels refit the formula weights to maximise balanced accuracy at the "worth pursuing" threshold — a deterministic grid-search, zero model calls. It writes the refit as a proposal (`_tuned_weights.json` + a printed diff); it never mutates your `profile.yml`.
- **Plain, inspectable state.** Flat JSON files (`_index.json`, `_board.json`) plus a rendered `SHORTLIST.md`, idempotent board operations. No hidden magic.

The reasoning behind these choices lives as ADRs in [`docs/adr/`](docs/adr/); the domain glossary is in [`CONTEXT.md`](CONTEXT.md).

## Providers

Pick a backend with `YOKE_PROVIDER` (or let it default to your Claude subscription):

| Provider | `YOKE_PROVIDER` | Key |
|---|---|---|
| Claude subscription (default) | — | long-lived token (`claude setup-token`) |
| OpenRouter (100+ models) | `openrouter` | `OPENROUTER_API_KEY` |
| OpenAI / Anthropic / Groq / Together / DeepInfra | `openai` / `anthropic` / `groq` / … | provider key |
| Ollama / LM Studio (fully local) | `ollama` / `lmstudio` | none |
| Anything OpenAI-compatible | set `YOKE_BASE_URL` | `YOKE_API_KEY` |

## Quickstart

```bash
git clone https://github.com/Todmy/Yoke && cd Yoke
mkdir -p ~/.yoke && cp profile.example.yml ~/.yoke/profile.yml   # then edit it with your CV/prefs
pip install pyyaml                                               # or write ~/.yoke/profile.json instead
./yoke run
```

`yoke run` walks you through a sources menu, then asks before it spends a model call. Your shortlist lands at `~/.yoke/SHORTLIST.md`. Useful flags: `--yes` (skip the prompts, use your remembered selection), `--dry-run` (stop after collect), `--mock` (no real model call, deterministic fake).

Other commands: `yoke help` lists them all; `yoke sources` reports each source's status (available · cost · geo · roles last run), and `yoke sources <name>` prints that source's setup page — how to enable it, with the exact commands. `yoke eval` scores the model against a golden set (run `yoke eval --record` once first to capture the model's take), printing a safety-first, per-dimension scorecard; `yoke tune` proposes refit weights from your apply/drop history. Add `--json` to `sources`, `eval`, or `tune` for machine-readable output (handy when another tool or agent drives Yoke).

### Building a golden set (for `yoke eval`)

`yoke eval` reads `~/.yoke/_golden.json` — a small, hand-reviewed set of roles with trusted labels. Each entry carries the role's `key`, its `jd` text, and a `truth` block: `{geo, tier, comp_vs_floor, red_flags, features}`. Bootstrap candidate labels with a stronger model, correct the safety-critical ones (geo / tier / red-flags) by hand, and freeze the file — it stays on your machine and is never committed. See [`tests/fixtures/golden.json`](tests/fixtures/golden.json) for the exact shape.

## Status

Early. The engine was extracted from a working private setup and is being decoupled into a clean, profile-driven tool. Expect rough edges and breaking changes. Issues and ideas welcome.

## License

MIT — see [LICENSE](LICENSE).
