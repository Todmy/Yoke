#!/usr/bin/env python3
"""Yoke local control panel — board + settings + profile + run/schedule.

stdlib http.server + the SQLite store. Zero dependencies, cross-platform, bound
to 127.0.0.1 (it writes keys/config and can trigger runs — keep it local-only):
    python3 src/serve.py [--port 8765] [--open]

Pages: / (board, triage) · /settings (provider+key, sources) · /profile (CV+prompt).
Buttons: Run now (background) · Schedule / Unschedule (cron).
"""
import argparse
import html
import json
import os
import re
import shutil
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
import store  # noqa: E402
import tune  # noqa: E402
import gap  # noqa: E402  (deterministic skill-gap panel on the apply page)
from paths import (STATE, YOKE_HOME, CONFIG_DIR, PROFILE_FILE, SOURCES_FILE,  # noqa: E402
                   ensure_home, load_profile, load_sources)

HERE = Path(__file__).resolve().parent
RUN_SH = HERE / "run.sh"
ENV_FILE = Path(os.environ.get("YOKE_ENV", Path.home() / ".config" / "yoke.env"))
RUN_LOG = YOKE_HOME / "run.log"
CRON_TAG = "# yoke-auto"
SCHEDULE_PRESETS = {  # label -> (hours csv, description)
    "1": ("9", "once a day · 09:00"),
    "2": ("9,17", "twice a day · 09:00, 17:00"),
    "3": ("8,13,18", "3× a day · 08:00, 13:00, 18:00"),
    "4": ("6,11,16,21", "4× a day · 06/11/16/21"),
}


def cron_line(hours="9,17", minute="10", days="3"):
    return f"{minute} {hours} * * * /bin/bash {RUN_SH} all --days {days} >> /tmp/yoke-cron.log 2>&1 {CRON_TAG}"

NEED_LABELS = 12
TIER_TITLE = {"A": "Tier A — apply", "B": "Tier B — worth a look", "C": "Tier C"}
TIER_ORDER = {"A": 0, "B": 1, "C": 2}
REASONS = ["off-lane", "geo", "comp", "seniority", "not-interesting", "lang", "other"]
# All providers route through the one OpenAICompat backend (+ presets), except
# claude_code (subscription via the claude CLI). anthropic uses Anthropic's
# OpenAI-compatible /v1/chat/completions route (Claude via API key, vs claude_code's
# subscription). All are functional given a key / local server.
PROVIDERS = ["claude_code", "openrouter", "openai", "anthropic", "groq",
             "together", "deepinfra", "ollama", "lmstudio"]
PROVIDER_LABELS = {
    "claude_code": "Claude subscription — via the claude CLI",
    "openrouter": "OpenRouter — 100+ models · API key",
    "openai": "OpenAI — API key",
    "anthropic": "Anthropic — Claude via API key",
    "groq": "Groq — fast inference · API key",
    "together": "Together AI — API key",
    "deepinfra": "DeepInfra — API key",
    "ollama": "Ollama — fully local, no key",
    "lmstudio": "LM Studio — fully local, no key",
}
SOURCE_NAMES = ["ats", "remoteok", "remotive", "weworkremotely", "hackernews", "dorks", "jobspy"]
SOURCE_DESC = {
    "ats": "Your Target Companies' own job boards (Greenhouse/Lever/Ashby) — first-source, complete, fresh.",
    "remoteok": "RemoteOK — a large remote-only job aggregator.",
    "remotive": "Remotive — curated remote roles across tech.",
    "weworkremotely": "We Work Remotely — the largest remote-work board (RSS).",
    "hackernews": "Hacker News 'Who is hiring?' — the monthly startup hiring thread.",
    "dorks": "Google site-search across ATS domains — finds roles at companies NOT in your list (the hidden layer).",
    "jobspy": "LinkedIn / Indeed via jobspy — needs the optional venv; those sites restrict scraping (off by default).",
}
LANGS = ["en", "uk", "de", "fr", "es", "pl"]
MAX_UPLOAD = 5 * 1024 * 1024  # 5 MB résumé upload cap (FR-007a)


def _parse_multipart(ctype, body):
    """Parse multipart/form-data with the stdlib email parser (cgi was removed in
    3.13). Returns {field: (filename|None, bytes)}."""
    from email import policy
    from email.parser import BytesParser
    header = f"Content-Type: {ctype}\r\nMIME-Version: 1.0\r\n\r\n".encode()
    # policy.default → EmailMessage (has iter_parts/get_param); the legacy Message does not.
    msg = BytesParser(policy=policy.default).parsebytes(header + body)
    out = {}
    for part in (msg.iter_parts() if msg.is_multipart() else []):
        name = part.get_param("name", header="content-disposition")
        if name:
            out[name] = (part.get_filename(), part.get_payload(decode=True) or b"")
    return out


def _esc(x):
    return html.escape(str(x if x is not None else ""))


# ── config / auth / cron helpers ─────────────────────────────────────────────
def read_env():
    """Return {provider, has_key, configured}. `configured` = the user actually
    saved a provider in Settings (not just a default)."""
    prov, has_key, configured = "claude_code", False, False
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.replace("export ", "").strip()
            if line.startswith("YOKE_PROVIDER="):
                prov = line.split("=", 1)[1].strip() or prov
                configured = True
            if line.startswith(("YOKE_API_KEY=", "OPENROUTER_API_KEY=", "CLAUDE_CODE_OAUTH_TOKEN=")) and line.split("=", 1)[1].strip():
                has_key = True
                configured = True
    return {"provider": prov, "has_key": has_key, "configured": configured}


def write_env(provider, key):
    ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
    # always record the chosen provider (even claude_code w/o key) so we can tell
    # "user picked a provider" from "never configured".
    lines = [f"export YOKE_PROVIDER={provider}"]
    if key:
        lines.append(f"export CLAUDE_CODE_OAUTH_TOKEN={key}" if provider == "claude_code"
                     else f"export YOKE_API_KEY={key}")
    ENV_FILE.write_text("\n".join(lines) + "\n")
    try:
        ENV_FILE.chmod(0o600)
    except OSError:
        pass


def write_json(path, obj):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2))


def _crontab():
    return subprocess.run(["crontab", "-l"], capture_output=True, text=True).stdout or ""


def cron_scheduled():
    return CRON_TAG in _crontab()


def cron_current():
    """Return (hours, minute) of the installed Yoke cron line, or None."""
    for ln in _crontab().splitlines():
        if CRON_TAG in ln:
            parts = ln.split()
            if len(parts) >= 2:
                return parts[1], parts[0]
    return None


def cron_set(enable, hours="9,17", minute="10"):
    kept = [ln for ln in _crontab().splitlines() if CRON_TAG not in ln]
    if enable:
        kept.append(cron_line(hours, minute))
    body = ("\n".join(kept) + "\n") if kept else ""
    subprocess.run(["crontab", "-"], input=body, text=True)


def run_ready():
    """Can a run actually score anything? Returns (ok, message).
    Requires an EXPLICIT provider choice saved in Settings — not just a claude
    binary that happens to be on PATH."""
    env = read_env()
    if not env["configured"]:
        return False, "Pick an AI provider in Settings and save it first."
    if env["has_key"] or env["provider"] in ("ollama", "lmstudio"):
        return True, ""
    if env["provider"] == "claude_code":
        return ((True, "") if shutil.which("claude")
                else (False, "You chose Claude, but the `claude` CLI isn't installed / logged in."))
    return True, ""  # configured provider without a key (e.g. a custom base_url)


def run_now():
    ensure_home()
    RUN_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(RUN_LOG, "a") as log:
        subprocess.Popen(["bash", str(RUN_SH), "all", "--days", "7"],
                         stdout=log, stderr=subprocess.STDOUT, start_new_session=True)


CSS = """
* { box-sizing: border-box; }
body { font: 15px/1.5 -apple-system, system-ui, sans-serif; margin: 0; background: #0f1115; color: #e6e6e6; }
a, a:visited { color: #7db4ff; }
a:hover { color: #a9cdff; }
header { padding: 16px 24px; border-bottom: 1px solid #262a33; position: sticky; top: 0; background: #0f1115; z-index: 5; }
h1 { font-size: 18px; margin: 0 0 4px; }
.sub { color: #8b93a3; font-size: 13px; }
.filt { color: #6ea8fe; text-decoration: none; font-weight: 600; } .filt:hover { text-decoration: underline; }
.counts { margin-top: 8px; font-size: 13px; color: #aab3c5; } .counts b { color: #e6e6e6; }
nav { display: flex; gap: 14px; align-items: center; margin-bottom: 8px; flex-wrap: wrap; }
nav a { color: #9aa4b6; text-decoration: none; font-size: 13px; font-weight: 600; }
nav a.on { color: #7db4ff; }
nav .spacer { flex: 1; }
nav button, nav a.schedlink { border: 0; border-radius: 7px; padding: 8px 16px; cursor: pointer; font-weight: 700; font-size: 13px; line-height: 1; transition: filter .12s ease, transform .06s ease; display: inline-flex; align-items: center; gap: 6px; }
nav button:hover, nav a.schedlink:hover { filter: brightness(1.15); }
nav button:active, nav a.schedlink:active { transform: translateY(1px); }
.run { background: #2d4a7a; color: #dce8ff; } .sched { background: #1f5e35; color: #d6ffe0; } .unsched { background: #5e2530; color: #ffd6dd; }
main { padding: 12px 24px 48px; }
h2 { font-size: 14px; text-transform: uppercase; letter-spacing: .06em; color: #9aa4b6; margin: 24px 0 8px; }
table { width: 100%; border-collapse: collapse; }
th, td { text-align: left; padding: 8px 10px; border-bottom: 1px solid #1d2129; vertical-align: top; }
th { font-size: 12px; color: #788196; font-weight: 600; }
tr:hover td { background: #161a21; }
.fit { font-weight: 700; white-space: nowrap; }
.role a { color: #7db4ff; text-decoration: none; } .role a:hover { text-decoration: underline; }
.company { color: #cfd6e4; } .note { color: #8b93a3; font-size: 13px; max-width: 360px; }
.geo, .comp, .added { white-space: nowrap; font-size: 13px; } .comp { color: #b8e6c0; } .added { color: #6b7280; font-size: 12px; }
.banner { background: #1c2530; color: #9cc4ff; padding: 6px 24px; font-size: 13px; }
.tier { display: inline-block; min-width: 16px; text-align: center; padding: 2px 7px; border-radius: 6px; font-size: 11px; font-weight: 800; }
.tier.A { background: #1f5e35; color: #d6ffe0; }
.tier.B { background: #5a4a1c; color: #ffe9b0; }
.tier.C { background: #2a2f3a; color: #9aa4b6; }
.board { margin-top: 4px; }
.ritem { border-bottom: 1px solid #1d2129; }
.ritem details > summary { list-style: none; display: flex; align-items: center; gap: 12px; padding: 11px 6px; cursor: pointer; }
.ritem details > summary::-webkit-details-marker { display: none; }
.ritem details > summary::before { content: "▸"; color: #5a6271; font-size: 11px; transition: transform .15s ease; }
.ritem details[open] > summary::before { transform: rotate(90deg); }
.ritem summary:hover { background: #161a21; }
.s-fit { width: 150px; font-weight: 700; white-space: nowrap; }
.s-geo { width: 86px; font-size: 13px; white-space: nowrap; }
.s-title { flex: 1; min-width: 180px; } .s-title b { color: #cfd6e4; }
.s-comp { width: 84px; font-size: 13px; color: #b8e6c0; white-space: nowrap; text-align: right; }
.ritem summary button { border: 0; border-radius: 5px; padding: 5px 10px; cursor: pointer; font-weight: 700; }
.ritem summary .ok { background: #1f5e35; color: #d6ffe0; } .ritem summary .no { background: #5e2530; color: #ffd6dd; }
.ritem summary a.applybtn { padding: 5px 12px; border-radius: 5px; font-weight: 700; font-size: 13px; text-decoration: none; white-space: nowrap; }
.ritem summary .star { background: transparent; border: 0; color: #c9a227; font-size: 18px; line-height: 1; cursor: pointer; padding: 0 8px; }
.ritem summary .star:hover { color: #ffd34d; }
.ritem summary .star.starred { color: #ffd34d; }
.detail { padding: 2px 6px 14px 30px; display: flex; flex-direction: column; gap: 8px; max-width: 920px; }
.detail .note { color: #b9c2d0; font-size: 13px; margin: 0; }
.detail .row { display: flex; gap: 8px; align-items: center; }
.detail select, .detail input { background: #11151c; color: #cfd6e4; border: 1px solid #2a2f3a; border-radius: 5px; padding: 5px 7px; font-size: 12px; }
.detail input { flex: 1; max-width: 320px; }
.detail .rlabel { color: #9aa4b6; font-size: 12px; font-weight: 600; }
.detail .row button { border: 0; border-radius: 5px; padding: 6px 12px; cursor: pointer; font-weight: 700; }
.detail .row .ok { background: #1f5e35; color: #d6ffe0; } .detail .row .no { background: #5e2530; color: #ffd6dd; }
.improve { background: #2d4a7a; color: #dce8ff; border: 0; border-radius: 4px; padding: 5px 10px; cursor: pointer; font-weight: 700; }
.improve-off { color: #5a6271; cursor: not-allowed; }
.card { background: #161a21; border: 1px solid #262a33; border-radius: 8px; padding: 16px 20px; margin: 16px 0; max-width: 760px; }
.delta { font-size: 22px; font-weight: 800; } .up { color: #9cffb0; } .same { color: #8b93a3; }
code { background: #11151c; padding: 2px 5px; border-radius: 3px; }
form.cfg label { display: block; margin: 12px 0 4px; font-size: 13px; color: #aab3c5; }
form.cfg input[type=text], form.cfg input[type=password], form.cfg input[type=number], form.cfg select, form.cfg textarea {
  width: 100%; max-width: 720px; background: #11151c; color: #e6e6e6; border: 1px solid #2a2f3a; border-radius: 6px; padding: 8px 10px; font: inherit; }
form.cfg textarea { min-height: 120px; font-family: ui-monospace, monospace; font-size: 13px; }
form.cfg .save { margin-top: 16px; background: #2d4a7a; color: #dce8ff; border: 0; border-radius: 6px; padding: 8px 16px; font-weight: 700; cursor: pointer; }
.checks label { display: inline-flex; gap: 5px; align-items: center; margin: 4px 14px 4px 0; color: #cfd6e4; }
.src-list { display: flex; flex-direction: column; gap: 2px; }
.src-row { display: flex; gap: 10px; align-items: flex-start; padding: 9px 10px; border-radius: 8px; color: #cfd6e4; cursor: pointer; }
.src-row:hover { background: #161b24; }
.src-row input { margin-top: 3px; }
.src-row .sub { font-size: 12px; }
form.trk { display: flex; gap: 6px; align-items: center; }
form.trk select, form.trk input { background: #11151c; color: #cfd6e4; border: 1px solid #2a2f3a; border-radius: 5px; padding: 5px 7px; font-size: 12px; }
form.trk input { flex: 1; min-width: 160px; }
.save2 { background: #2d4a7a; color: #dce8ff; border: 0; border-radius: 5px; padding: 5px 12px; font-weight: 700; cursor: pointer; }
/* standalone buttons (work outside form.cfg): consistent, with hover */
.btn { display: inline-flex; align-items: center; gap: 6px; background: #2d4a7a; color: #dce8ff; border: 0; border-radius: 8px; padding: 9px 16px; font: inherit; font-size: 13px; font-weight: 700; cursor: pointer; transition: background .12s ease, transform .04s ease; }
.btn:hover { background: #37589a; } .btn:active { transform: translateY(1px); }
.btn-accent { background: linear-gradient(135deg, #5b3da8, #3a2d6e); color: #ece6ff; }
.btn-accent:hover { background: linear-gradient(135deg, #6b49c4, #463584); }
.btn-ghost { background: #1a1f29; color: #cfd6e4; border: 1px solid #2a2f3a; }
.btn-ghost:hover { background: #222836; }
.resume-actions { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; margin-top: 12px; }
/* [hidden] must win over explicit display rules below (.btn, .af-loading) */
[hidden] { display: none !important; }
/* auto-fill review modal (smooth fade+scale) */
.modal-bg { position: fixed; inset: 0; background: rgba(0,0,0,.55); display: flex; align-items: center; justify-content: center; z-index: 100; opacity: 0; transition: opacity .15s ease; }
.modal-bg.show { opacity: 1; }
.modal-bg[hidden] { display: none; }
.modal { width: min(640px, 92vw); max-height: 88vh; overflow: auto; background: #141922; border: 1px solid #2a2f3a; border-radius: 14px; padding: 22px; box-shadow: 0 24px 60px rgba(0,0,0,.6); transform: translateY(10px) scale(.98); transition: transform .15s ease; }
.modal-bg.show .modal { transform: none; }
.modal h2 { margin: 0 0 4px; }
.modal label { display: block; margin: 14px 0 4px; color: #9aa4b6; font-size: 12px; }
.modal input, .modal textarea { width: 100%; box-sizing: border-box; background: #11151c; color: #e6e6e6; border: 1px solid #2a2f3a; border-radius: 6px; padding: 8px 10px; font: inherit; }
.modal textarea { min-height: 160px; font-family: ui-monospace, monospace; font-size: 13px; }
.modal-actions { display: flex; gap: 10px; justify-content: flex-end; margin-top: 18px; }
.spinner { width: 22px; height: 22px; border: 3px solid #2a2f3a; border-top-color: #6b49c4; border-radius: 50%; animation: spin .7s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.af-loading { display: flex; align-items: center; gap: 12px; color: #cfd6e4; padding: 8px 0; }
.toast { position: fixed; bottom: 20px; right: 20px; z-index: 50; max-width: 440px; padding: 11px 16px; border-radius: 10px; font-size: 13px; box-shadow: 0 10px 30px rgba(0,0,0,.5); animation: toastin .18s ease-out, toastout .5s ease 4.5s forwards; }
.toast.ok { background: #1f5e35; color: #d6ffe0; }
.toast.warn { background: #5a4a1c; color: #ffe9b0; border: 1px solid #8a6d1f; }
.toast.error { background: #5e2530; color: #ffd6dd; border: 1px solid #8a3a48; }
@keyframes toastin { from { opacity: 0; transform: translateY(10px); } }
@keyframes toastout { to { opacity: 0; visibility: hidden; } }
nav a.schedlink { background: #1f5e35; color: #d6ffe0; text-decoration: none; }
.checks.col label { display: flex; }
"""


def _nav(active):
    sched = cron_scheduled()
    # Schedule opens a chooser page (when / how often); Unschedule is a one-click off
    sbtn = ('<form method="post" action="/unschedule" style="display:inline"><button class="unsched">Unschedule</button></form>'
            if sched else
            '<a href="/schedule" class="schedlink">Schedule (cron)</a>')
    def lk(href, name):
        return f'<a href="{href}" class="{"on" if active == href else ""}">{name}</a>'
    return ('<nav>' + lk("/", "Board") + lk("/applied", "Applied") + lk("/settings", "Settings") + lk("/profile", "Profile")
            + '<span class="spacer"></span>'
            + '<form method="post" action="/run" style="display:inline"><button class="run">▶ Run now</button></form>'
            + sbtn + (' <span class="sub">cron: on</span>' if sched else '') + '</nav>')


def _page(title, body, active="", flash="", kind="ok"):
    fl = f'<div class="toast {kind}">{_esc(flash)}</div>' if flash else ""
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>Yoke — {_esc(title)}</title><style>{CSS}</style></head>'
            f'<body><header>{_nav(active)}<h1>Yoke — {_esc(title)}</h1></header>{fl}<main>{body}</main></body></html>')


# ── board ────────────────────────────────────────────────────────────────────
# Each role is an expandable <details> wrapped in one <form>: the summary is the
# at-a-glance triage line (overview), the body holds the note + reject reason +
# comment (details-on-demand). Because reason/comment live in the same form, the
# ✓/✗ buttons in the summary submit them whether or not the row is expanded.
def _item(r, starred=False, next_q=""):
    rk = _esc(r.get("role_key"))
    tier = r.get("tier", "B")
    url = r.get("url") or ""
    link = (f'<a href="{_esc(url)}" target="_blank" rel="noopener">open posting →</a>'
            if url.startswith("http") else _esc(r.get("source", "")))
    opts = "".join(f"<option>{o}</option>" for o in REASONS)
    # ☆/★ bookmark toggle — instant, role STAYS on the board (a "look later" signal,
    # NOT a tuner positive). formaction overrides the row form's /mark; the hidden
    # `next` returns the user to the same (possibly filtered) board view.
    icon, act, title = (("★", "/unstar", "un-star") if starred
                        else ("☆", "/star", "star — interested, filter to it later"))
    star = (f'<button class="star{" starred" if starred else ""}" formaction="{act}" title="{title}"'
            f' onclick="event.stopPropagation()">{icon}</button>')
    return (
        '<form method="post" action="/mark" class="ritem">'
        f'<input type="hidden" name="role_key" value="{rk}">'
        f'<input type="hidden" name="next" value="{_esc(next_q)}">'
        '<details><summary>'
        f'<span class="tier {_esc(tier)}">{_esc(tier)}</span>'
        f'<span class="s-fit">{_esc(r.get("fit"))} {_esc(r.get("label"))}</span>'
        f'<span class="s-geo">{_esc(r.get("geo"))}</span>'
        f'<span class="s-title">{_esc(r.get("title"))} · <b>{_esc(r.get("company"))}</b></span>'
        f'<span class="s-comp">{_esc(r.get("comp"))}</span>'
        f'{star}'
        f'<a class="ok applybtn" href="/apply?role={quote(r.get("role_key") or "")}" title="review &amp; log this application">✓ Apply</a>'
        '</summary>'
        '<div class="detail">'
        f'<p class="note">{_esc(r.get("note"))}</p>'
        '<div class="row"><span class="rlabel">Reject —</span>'
        f'<select name="reason"><option value="">reason…</option>{opts}</select>'
        '<input name="comment" placeholder="comment (optional)">'
        '<button class="no" name="decision" value="rejected">✗ Reject</button></div>'
        f'<div class="sub">{link}</div>'
        '</div></details></form>')


def _is_remote(r):
    return "remote" in (r.get("geo") or "")


def _board_query(remote, interested):
    qs = [k for k, v in (("remote=1", remote), ("interested=1", interested)) if v]
    return "/?" + "&".join(qs) if qs else "/"


def board_page(flash="", kind="ok", remote_only=False, interested_only=False):
    b = store.load()
    c = store.label_counts()
    starred = store.starred_keys()
    roles = sorted(b["roles"], key=lambda r: (TIER_ORDER.get(r.get("tier", "B"), 1), -int(r.get("fit") or 0)))
    counts = {t: sum(1 for r in roles if r.get("tier") == t) for t in ("A", "B", "C")}
    n_remote = sum(1 for r in roles if _is_remote(r))
    n_starred = sum(1 for r in roles if r.get("role_key") in starred)
    shown = roles
    if remote_only:
        shown = [r for r in shown if _is_remote(r)]
    if interested_only:
        shown = [r for r in shown if r.get("role_key") in starred]
    next_q = _board_query(remote_only, interested_only)  # row toggles return to this view
    # two independent board filters (each toggle preserves the other):
    #  · remote-confirmed (hybrid B) — drop the geo=verify noise
    #  · ★ interested-only — the triage → shortlist → work flow, on the SAME board (no tab)
    remote_link = (f'<a href="{_board_query(False, interested_only)}" class="filt">show all geos →</a>' if remote_only
                   else f'<a href="{_board_query(True, interested_only)}" class="filt">remote-confirmed only ({n_remote}) →</a>')
    star_link = (f'<a href="{_board_query(remote_only, False)}" class="filt">show all →</a>' if interested_only
                 else f'<a href="{_board_query(remote_only, True)}" class="filt">★ interested only ({n_starred}) →</a>')
    if shown:
        items = "".join(_item(r, starred=r.get("role_key") in starred, next_q=next_q) for r in shown)
        caption = " · ".join(f"<span class=\"tier {t}\">{t}</span> {counts[t]}" for t in ("A", "B", "C") if counts[t])
        body = (f'<p class="sub" style="margin:8px 0 12px">{caption} · {remote_link} · {star_link} · click a role for the why + reject reason</p>'
                f'<div class="board">{items}</div>')
    elif roles:  # roles exist but a filter hid them all
        why = "starred" if interested_only else "geo-confirmed remote"
        body = (f'<div class="card">No {why} roles in this view. {remote_link} · {star_link}<br>'
                f'<span class="sub">{len(roles)} roles on the board total.</span></div>')
    else:
        body = '<div class="card">Board is empty. Set a provider in <a href="/settings">Settings</a> and your CV in <a href="/profile">Profile</a>, then hit <b>▶ Run now</b>.</div>'
    tunable = store.labeled_decisions(require_raw=True)
    n_pos = sum(1 for l in tunable if l["decision"] == "applied")  # tuner positive = applied only (Δ1)
    n_neg = sum(1 for l in tunable if l["decision"] == "rejected")
    eligible = n_pos >= 1 and n_neg >= 1 and len(tunable) >= NEED_LABELS
    improve = ('<form method="post" action="/improve" style="display:inline"><button class="improve">⚙ Improve (refit weights)</button></form>'
               if eligible else
               f'<span class="improve-off" title="needs ≥{NEED_LABELS} labels, both classes (tunable: {n_pos}+/{n_neg}−)">⚙ Improve (locked)</span>')
    gate = (f'<b>{c["total"]}</b> labels (applied {c["applied"]}, interested {c["interested"]}, '
            f'rejected {c["rejected"]}; tunable {len(tunable)}). {improve}')
    fl = f'<div class="toast {kind}">{_esc(flash)}</div>' if flash else ""
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1"><meta http-equiv="refresh" content="60">'
            f'<title>Yoke — board</title><style>{CSS}</style></head><body>'
            f'<header>{_nav("/")}<h1>Yoke — live board</h1>'
            f'<div class="sub">{len(roles)} roles to review · auto-refresh 60s · ✓ Apply opens a log step · ✗ reject is instant</div>'
            f'<div class="counts">{gate}</div></header>{fl}<main>{body}</main></body></html>')


# ── settings (A) ─────────────────────────────────────────────────────────────
def settings_page(flash=""):
    env = read_env()
    src = load_sources()
    enabled = src.get("sources", {})
    companies = src.get("companies", [])
    comp_text = "\n".join(f"{c.get('name','')},{c.get('ats','')},{c.get('slug','')}" for c in companies)
    prov_opts = "".join(
        f'<option value="{p}"{" selected" if p == env["provider"] else ""}>{_esc(PROVIDER_LABELS.get(p, p))}</option>'
        for p in PROVIDERS)
    # current saved state — so the user sees what's already configured
    if env["provider"] == "claude_code":
        cur = ("Configured: <b>Claude subscription</b> — "
               + ("token on file ✓" if env["has_key"] else "uses your logged-in <code>claude</code> session (a token is needed only for cron)"))
    elif env["provider"] in ("ollama", "lmstudio"):
        cur = f"Configured: <b>{_esc(env['provider'])}</b> — local model, no key needed"
    else:
        cur = (f"Configured: <b>{_esc(env['provider'])}</b> — "
               + ("API key on file ✓" if env["has_key"] else "no key yet — paste one below"))
    keyhint = "leave blank to keep the saved key" if env["has_key"] else "paste your key (or leave blank for local / Claude session)"
    # claude_code-specific guidance on getting the token
    cc_note = ("""<p class="sub"><b>Claude subscription:</b> interactive runs use your logged-in <code>claude</code> CLI — no key needed. """
               """For scheduled (cron) runs, generate a long-lived token: run <code>claude setup-token</code> in your terminal and paste it above.</p>""")
    src_rows = "".join(
        f'<label class="src-row"><input type="checkbox" name="src_{s}" '
        f'{"checked" if enabled.get(s, {}).get("enabled", s != "jobspy") else ""}> '
        f'<span><b>{_esc(s)}</b><br><span class="sub">{_esc(SOURCE_DESC.get(s, ""))}</span></span></label>'
        for s in SOURCE_NAMES)
    body = f"""<form class="cfg" method="post" action="/settings">
<div class="card">
<h2 style="margin-top:0">AI provider</h2>
<p class="sub">{cur}</p>
<label>Provider</label>
<select name="provider">{prov_opts}</select>
<label>API key / token — {keyhint}</label>
<input type="password" name="key" placeholder="sk-… / token (or leave empty)">
{cc_note}
</div>
<div class="card">
<h2 style="margin-top:0">Sources</h2>
<p class="sub">Where Yoke looks for roles. Toggle any off; finer per-source settings are coming.</p>
<div class="src-list">{src_rows}</div>
</div>
<div class="card">
<h2 style="margin-top:0">Target companies <span class="sub">(optional)</span></h2>
<p class="sub">Your watchlist of dream employers — Yoke pulls roles straight from each company's own job board (first-source, complete, fresh), not via aggregators. Leave empty if you're not targeting specific companies; the other sources still run.</p>
<label>One per line: <code>name,ats,slug</code> — <code>ats</code> = greenhouse | lever | ashby; <code>slug</code> = the board id in their careers URL (e.g. <code>Mistral,lever,mistral</code> → <code>jobs.lever.co/mistral</code>)</label>
<textarea name="companies">{_esc(comp_text)}</textarea>
</div>
<button class="btn" type="submit">Save settings</button>
</form>"""
    return _page("settings", body, active="/settings", flash=flash)


# ── profile (B) ──────────────────────────────────────────────────────────────
_AUTOFILL_MODAL = """
<div id="afModal" class="modal-bg" hidden>
  <div class="modal">
    <h2>✨ Auto-fill from your résumé</h2>
    <p class="sub" id="afNote"></p>
    <div id="afLoading" class="af-loading"><div class="spinner"></div><span id="afLoadingMsg">Reading…</span></div>
    <div id="afReview" hidden>
      <label>Name</label><input id="m_name">
      <label>Headline</label><input id="m_headline">
      <label>Scoring prompt</label><textarea id="m_prompt"></textarea>
    </div>
    <div class="modal-actions">
      <button class="btn btn-ghost" id="afCancel" type="button">Cancel</button>
      <button class="btn btn-accent" id="afPrimary" type="button" hidden>Apply</button>
    </div>
  </div>
</div>"""

# Vanilla JS UX layer (no framework, no business logic — extraction/auto-fill/cloud
# gate all stay server-side). Picks a file → extracts → auto-fills → review modal.
_AUTOFILL_JS = """
(function(){
  var $=function(i){return document.getElementById(i);};
  var modal=$('afModal'); if(!modal) return;
  var note=$('afNote'),loading=$('afLoading'),loadMsg=$('afLoadingMsg'),review=$('afReview'),
      primary=$('afPrimary'),cancel=$('afCancel'),ta=$('pf_resume'),
      file=$('cvfile'),afbtn=$('afbtn'),upbtn=$('upbtn');
  if(upbtn) upbtn.style.display='none';  // JS: file pick auto-runs; no separate upload click
  if(file) file.style.display='none';    // hide the native picker; ✨ Auto-fill opens it via file.click()
  function open(){modal.hidden=false;void modal.offsetWidth;modal.classList.add('show');}  // reflow, not rAF (works in bg tabs)
  function close(){modal.classList.remove('show');setTimeout(function(){modal.hidden=true;},160);}
  function loadingMode(m){note.textContent='';loadMsg.textContent=m;loading.hidden=false;review.hidden=true;primary.hidden=true;open();}
  function errorMode(m){loading.hidden=true;review.hidden=true;primary.hidden=true;note.textContent=m;open();}
  function confirmMode(prov,text){loading.hidden=true;review.hidden=true;primary.hidden=false;
    note.textContent='Your résumé text will be sent to '+prov+' (a non-local provider).';
    primary.textContent='Send & auto-fill';primary.onclick=function(){autofill(text,true);};}
  function reviewMode(p){loading.hidden=true;review.hidden=false;primary.hidden=false;
    note.textContent='Review the proposal — edit anything, then Apply.';
    $('m_name').value=p.name||'';$('m_headline').value=p.headline||'';$('m_prompt').value=p.scoring_prompt||'';
    primary.textContent='Apply to profile';primary.onclick=apply;}
  function apply(){$('pf_name').value=$('m_name').value;$('pf_headline').value=$('m_headline').value;
    $('pf_prompt').value=$('m_prompt').value;close();}
  cancel.onclick=close;
  modal.addEventListener('click',function(e){if(e.target===modal)close();});
  document.addEventListener('keydown',function(e){if(e.key==='Escape'&&!modal.hidden)close();});
  function autofill(text,confirm){
    loadingMode('Drafting your profile…');
    var body=new URLSearchParams();body.set('format','json');body.set('resume_text',text);
    if(confirm)body.set('confirm_cloud','1');
    fetch('/profile/autofill',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:body})
      .then(function(r){return r.json();}).then(function(j){
        if(j.need_confirm){confirmMode(j.need_confirm,text);return;}
        if(!j.ok){errorMode(j.error||'Auto-fill failed.');return;}
        ta.value=text;reviewMode(j);
      }).catch(function(e){errorMode('Network error: '+e);});
  }
  function extractThenFill(f){
    loadingMode('Reading your résumé…');
    var fd=new FormData();fd.append('file',f);
    fetch('/profile/extract',{method:'POST',body:fd})
      .then(function(r){return r.json();}).then(function(j){
        if(!j.ok){errorMode(j.error||'Could not read the file.');return;}
        autofill(j.text,false);
      }).catch(function(e){errorMode('Network error: '+e);});
  }
  file.addEventListener('change',function(){if(file.files&&file.files[0])extractThenFill(file.files[0]);});
  // one path: clicking Auto-fill always opens the picker → extract → auto-fill.
  // (clear value so re-picking the same/new file always fires change)
  afbtn.addEventListener('click',function(e){e.preventDefault();file.value='';file.click();});
})();"""


def profile_page(flash="", draft=None, pending_cloud=False, kind="ok"):
    p = load_profile()
    draft = draft or {}
    val = lambda k, dflt="": _esc(draft.get(k, p.get(k, dflt)))  # draft overrides saved
    lang_opts = "".join(
        f'<option value="{l}"{" selected" if l == p.get("output_language", "en") else ""}>{l}</option>' for l in LANGS)
    # ⬆ upload (multipart, its own form) → extracts text into the résumé field.
    # The single ✨ Auto-fill button sits HERE at the top but, via the HTML form=
    # attribute, submits the main profile form below — so it always acts on the
    # LIVE résumé textarea (whether pasted or just uploaded). No duplicate button.
    upload = """<div class="card">
<h2 style="margin-top:0">Start from your résumé</h2>
<p class="sub">Pick your CV (or paste it below) — Yoke reads it and proposes your headline + scoring prompt for you to review. Nothing is saved until you click Save.</p>
<div class="resume-actions">
<form id="upform" method="post" action="/profile/upload" enctype="multipart/form-data" style="display:contents">
<input type="file" id="cvfile" name="file" accept=".txt,.md,.pdf,.docx" required>
<button class="btn btn-ghost" id="upbtn" type="submit">⬆ Upload &amp; extract</button>
</form>
<button class="btn btn-accent" id="afbtn" form="pf" formaction="/profile/autofill" formmethod="post" type="submit">✨ Auto-fill from CV</button>
</div>
<p class="sub" style="margin-top:10px">PDF / .docx need <code>pip install pypdf python-docx</code> (opt-in). .txt works out of the box. A non-local AI provider means your CV text is sent to that provider.</p>
</div>"""
    # cloud-confirm banner (FR-013): re-submits the résumé text with confirm_cloud=1
    confirm = ""
    if pending_cloud:
        prov = read_env()["provider"]
        confirm = f"""<div class="card" style="border:1px solid #5a4a1c">
<p style="margin:0 0 8px">⚠ Auto-fill will send your résumé text to <b>{_esc(prov)}</b> (a non-local provider).</p>
<form method="post" action="/profile/autofill">
<input type="hidden" name="resume_text" value="{val('resume_text')}">
<input type="hidden" name="confirm_cloud" value="1">
<button class="btn btn-accent" type="submit">Send &amp; auto-fill</button> <a href="/profile" style="margin-left:12px">cancel</a>
</form></div>"""
    body = f"""{upload}{confirm}
<form class="cfg" id="pf" method="post" action="/profile">
<div class="card">
<h2 style="margin-top:0">Who you are</h2>
<label>Name</label><input type="text" id="pf_name" name="name" value="{val('name')}">
<label>Headline</label><input type="text" id="pf_headline" name="headline" value="{val('headline')}">
<label>Output language</label><select name="output_language">{lang_opts}</select>
<label>Comp floor (net USD/mo, 0 = none)</label><input type="number" name="comp_floor" value="{_esc(p.get('comp_floor_net_mo_usd',0))}">
</div>
<div class="card">
<h2 style="margin-top:0">Scoring profile (prompt)</h2>
<p class="sub">Fed to the model verbatim. Describe your lane, differentiators, seniority, languages, geo, comp. Be specific.</p>
<textarea id="pf_prompt" name="prompt">{val('prompt')}</textarea>
<label>Resume text (paste — optional; appended to the prompt so scoring sees your CV)</label>
<textarea id="pf_resume" name="resume_text" placeholder="paste your CV text here…">{val('resume_text')}</textarea>
</div>
<button class="btn" type="submit">Save profile</button>
</form>
{_AUTOFILL_MODAL}
<script>{_AUTOFILL_JS}</script>"""
    return _page("profile", body, active="/profile", flash=flash, kind=kind)


def schedule_page(flash=""):
    cur = cron_current()
    cur_txt = (f"Currently scheduled: every day at minute <code>{_esc(cur[1])}</code> of hours <code>{_esc(cur[0])}</code>."
               if cur else "Not scheduled yet.")
    presets = "".join(
        f'<label><input type="radio" name="preset" value="{k}"{" checked" if k == "2" else ""}> {v[1]}</label>'
        for k, v in SCHEDULE_PRESETS.items())
    unsched = ('<form method="post" action="/unschedule" style="margin-top:12px">'
               '<button class="unsched" style="border:0;border-radius:6px;padding:8px 16px;cursor:pointer">Unschedule</button></form>'
               if cur else "")
    body = f"""<form class="cfg" method="post" action="/schedule">
<div class="card">
<h2 style="margin-top:0">How often should Yoke run?</h2>
<p class="sub">{cur_txt} Each run does collect + score, in the background.</p>
<div class="checks col">{presets}
<label><input type="radio" name="preset" value="custom"> custom — set hours below</label></div>
<label>Custom hours (24h, comma-separated, e.g. <code>7,12,19</code>)</label>
<input type="text" name="hours" placeholder="9,17">
<label>Minute past the hour (0–59)</label>
<input type="number" name="minute" value="10" min="0" max="59">
<button class="save" type="submit">Schedule</button>
</div>
</form>{unsched}
<div class="card"><p class="sub" style="margin:0">Cron runs headless, so it needs auth that works without you logged in: set a token/key in <a href="/settings">Settings</a> (a local Ollama model works too). macOS: if cron does nothing, grant Full Disk Access to <code>/usr/sbin/cron</code> in System Settings › Privacy.</p></div>"""
    return _page("schedule", body, active="/schedule", flash=flash)


def _app_row(a):
    cur = a.get("status") or "applied"
    opts = "".join(f'<option{" selected" if cur == st else ""}>{st}</option>' for st in store.APP_STATUSES)
    url = a.get("url") or ""
    title = (f'<a href="{_esc(url)}" target="_blank" rel="noopener">{_esc(a.get("title"))}</a>'
             if str(url).startswith("http") else _esc(a.get("title")))
    cv = f'<div class="sub">CV: {_esc(a.get("resume"))}</div>' if a.get("resume") else ""
    return ('<tr>'
            f'<td class="added">{_esc(a.get("ts"))}</td>'
            f'<td class="role">{title}{cv}</td>'
            f'<td class="company">{_esc(a.get("company"))}</td>'
            '<td><form method="post" action="/track" class="trk">'
            f'<input type="hidden" name="id" value="{_esc(a.get("id"))}">'
            f'<select name="status">{opts}</select>'
            f'<input name="status_note" value="{_esc(a.get("status_note") or "")}" placeholder="note / rejection reason">'
            '<button class="save2">Save</button></form></td></tr>')


def apply_page(role_key, flash=""):
    r = store.get_role(role_key)
    if not r or r.get("title") is None:
        return _page("apply", '<div class="card">Role not found (it may already be decided). '
                     '<a href="/">← back to the board</a>.</div>', active="/")
    url = r.get("url") or ""
    link = (f' · <a href="{_esc(url)}" target="_blank" rel="noopener">open posting →</a>'
            if str(url).startswith("http") else "")
    # deterministic skill-gap panel (no model) — T037 / FR-011
    prof = load_profile()
    base_cv = prof.get("resume_text") or ""
    jd_text = gap._jd_text(url) or f"{r.get('title','')} {r.get('company','')}"
    g = gap.compute_gap(jd_text, gap._cv_text())
    matched = ", ".join(g["matched"]) or "—"
    missing = ", ".join(m["skill"] for m in g["missing"]) or "—"
    gap_panel = f"""<div class="card">
<h2 style="margin-top:0">Gap vs your CV</h2>
<p class="sub">Match: <b>{_esc(g['match_band'])}</b> ({g['match_score']}% of {g['required_count']} role skills) — a relevance signal for you, not a prediction of beating screening.</p>
<p>Matched: {_esc(matched)}</p>
<p>Missing (most central first): {_esc(missing)}</p>
<p class="sub">Tailor the CV below to surface the skills you genuinely have. For a letter draft run <code>yoke cover {_esc(role_key)}</code> — nothing is auto-written or sent.</p>
</div>"""
    body = f"""<div class="card">
<h2 style="margin-top:0">{_esc(r.get("title"))} · {_esc(r.get("company"))}</h2>
<p class="sub">{_esc(r.get("fit"))} {_esc(r.get("label"))} · {_esc(r.get("geo"))} · {_esc(r.get("comp"))}{link}</p>
<p class="note">{_esc(r.get("note"))}</p>
</div>
{gap_panel}
<form class="cfg" method="post" action="/apply-confirm">
<input type="hidden" name="role" value="{_esc(role_key)}">
<div class="card">
<h2 style="margin-top:0">Log this application</h2>
<p class="sub">Nothing is recorded until you confirm. Open the posting, apply there, then log what you sent.</p>
<label>Resume / CV sent — edit to tailor for this role; this exact text is snapshotted (immutable)</label>
<textarea name="resume" rows="10" placeholder="paste or tailor the CV you send…">{_esc(base_cv)}</textarea>
<label>Notes (cover-letter angle, referral, contact, anything to remember)</label>
<textarea name="notes" placeholder="optional"></textarea>
<button class="save" type="submit">✓ Confirm — I applied</button>
<a href="/" style="margin-left:14px">cancel</a>
</div>
</form>"""
    return _page("apply", body, active="/", flash=flash)


def applied_page(flash=""):
    apps = store.applications()
    if not apps:
        body = '<div class="card">Nothing applied yet. Hit <b>✓ Apply</b> on the <a href="/">Board</a> to start tracking applications here.</div>'
    else:
        s = store.application_stats()
        by = " · ".join(f"{k} {v}" for k, v in s["by"].items())
        analytics = (f'<p class="sub" style="margin:8px 0 14px"><b>{s["total"]}</b> applied · '
                     f'response {s["response_rate"]} · interview {s["interview_rate"]} · '
                     f'{s["offers"]} offer(s)<br>{by}</p>')
        rows = "".join(_app_row(a) for a in apps)
        body = (analytics + "<table><tr><th>Applied</th><th>Role</th><th>Company</th>"
                f"<th>Status · note</th></tr>{rows}</table>")
    return _page("applied", body, active="/applied", flash=flash)


def improve_result(res):
    if not res.get("ok"):
        return _page("improve", f'<div class="card"><p>Not enough data: {_esc(res.get("reason"))} '
                     f'(pursued {res.get("n_pos")}, rejected {res.get("n_neg")}).</p>'
                     '<p><a href="/">← back</a></p></div>', active="/")
    before, after = res["objective_before"], res["objective_after"]
    rows = "".join(f"<tr><td><code>{_esc(k)}</code></td><td>{_esc(res['weights_before'][k])}</td>"
                   f"<td><b>{_esc(v)}</b></td></tr>" for k, v in res["changed"].items()) \
        or '<tr><td colspan="3">default weights already optimal — no change</td></tr>'
    apply_form = ("" if not res["changed"] else
                  '<form method="post" action="/improve-apply" style="display:inline">'
                  f'<input type="hidden" name="weights" value="{_esc(json.dumps(res["weights_after"]))}">'
                  '<button class="improve">Apply new weights</button></form>')
    body = (f'<div class="card"><h2 style="margin-top:0">Refit weights to your decisions</h2>'
            f'<p>Labels: {res["n_pos"]} pursued / {res["n_neg"]} rejected</p>'
            f'<p>Balanced accuracy: <span class="delta {"up" if after > before else "same"}">{before} → {after}</span></p>'
            f'<table><tr><th>Weight</th><th>was</th><th>now</th></tr>{rows}</table>'
            f'<p style="margin-top:14px">{apply_form} &nbsp; <a href="/">← back, no change</a></p></div>')
    return _page("improve", body, active="/")


class Handler(BaseHTTPRequestHandler):
    def _html(self, s, code=200):
        body = s.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _redirect(self, to="/"):
        self.send_response(303)
        self.send_header("Location", to)
        self.end_headers()

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/", ""):
            q = parse_qs(urlparse(self.path).query)
            return self._html(board_page(remote_only=(q.get("remote") or [""])[0] == "1",
                                         interested_only=(q.get("interested") or [""])[0] == "1"))
        if path == "/settings":
            return self._html(settings_page())
        if path == "/profile":
            return self._html(profile_page())
        if path == "/schedule":
            return self._html(schedule_page())
        if path == "/applied":
            return self._html(applied_page())
        if path == "/apply":
            role = (parse_qs(urlparse(self.path).query).get("role") or [""])[0]
            return self._html(apply_page(role))
        self.send_error(404)

    def do_POST(self):
        path = self.path.split("?")[0]
        n = int(self.headers.get("Content-Length") or 0)
        ctype = self.headers.get("Content-Type", "")
        try:
            if ctype.startswith("multipart/form-data"):
                if n > MAX_UPLOAD:
                    return self._html(profile_page(
                        flash=f"File too large (limit {MAX_UPLOAD // (1024 * 1024)} MB).", kind="warn"))
                return self._post_multipart(path, ctype, self.rfile.read(n))
            d = parse_qs(self.rfile.read(n).decode("utf-8")) if n else {}
            g = lambda k, default="": (d.get(k) or [default])[0]
            return self._post(path, d, g)
        except Exception as e:  # any handler failure -> a red toast, not a 500
            return self._html(board_page(flash=f"⚠ {type(e).__name__}: {e}", kind="error"))

    def _post_multipart(self, path, ctype, raw):
        # /profile/extract → JSON {text} for the JS modal flow; /profile/upload →
        # no-JS fallback that re-renders the form with the extracted text.
        if path not in ("/profile/upload", "/profile/extract"):
            return self.send_error(404)
        js = path == "/profile/extract"
        import os as _os
        import tempfile
        import resume_import
        parts = _parse_multipart(ctype, raw)
        fname, data = parts.get("file", (None, None))
        if not data:
            m = "No file received — pick a file or paste the text."
            return self._json({"ok": False, "error": m}) if js else \
                self._html(profile_page(flash=m, kind="warn"))
        with tempfile.NamedTemporaryFile(suffix=Path(fname or "cv.txt").suffix, delete=False) as tf:
            tf.write(data)
            tmp = tf.name
        try:
            text = resume_import.extract_text(tmp)
        except resume_import.ExtractionUnavailable as e:
            return self._json({"ok": False, "error": e.hint}) if js else \
                self._html(profile_page(flash=f"⚠ {e.hint}", kind="warn"))
        except resume_import.NoTextFound:
            m = "Couldn't read text from that file — paste it instead."
            return self._json({"ok": False, "error": m}) if js else \
                self._html(profile_page(flash=m, kind="warn"))
        finally:
            _os.unlink(tmp)
        if js:
            return self._json({"ok": True, "text": text})
        return self._html(profile_page(
            draft={"resume_text": text}, flash="Résumé extracted — review, then ✨ Auto-fill or Save."))

    def _post(self, path, d, g):
        if path == "/mark":
            rk, dec = g("role_key"), g("decision")
            if rk and dec in ("applied", "rejected"):  # interested is star(), not mark()
                store.mark(rk, dec, g("reason"), g("comment"), source="ui")
                if dec == "applied":
                    _add_applied(rk)
            return self._redirect("/")
        if path in ("/star", "/unstar"):  # bookmark toggle — role stays on the board
            (store.star if path == "/star" else store.unstar)(g("role_key"))
            nxt = g("next", "/")
            if not (nxt.startswith("/") and not nxt.startswith("//")):
                nxt = "/"
            # un-starring the last role while in the interested-only view would strand
            # the user on an empty filter — drop the interested flag (keep remote if set).
            if path == "/unstar" and "interested=1" in nxt and not store.starred_keys():
                nxt = "/?remote=1" if "remote=1" in nxt else "/"
            return self._redirect(nxt)
        if path == "/profile/autofill":
            text = g("resume_text")
            js = g("format") == "json"   # JS (modal) path wants JSON; else no-JS re-render
            ok, msg = run_ready()
            if not ok:
                return self._json({"ok": False, "error": msg}) if js else \
                    self._html(profile_page(flash=msg, kind="warn", draft={"resume_text": text}))
            if not text.strip():
                m = "Paste or upload a résumé first."
                return self._json({"ok": False, "error": m}) if js else \
                    self._html(profile_page(flash=m, kind="warn"))
            provider = read_env()["provider"]
            local = provider in ("ollama", "lmstudio")
            if not local and g("confirm_cloud") != "1":   # FR-013 cloud warning gate
                return self._json({"ok": False, "need_confirm": provider}) if js else \
                    self._html(profile_page(pending_cloud=True, draft={"resume_text": text}))
            import resume_import
            try:
                out = resume_import.autofill(text)
            except Exception as e:  # malformed output / provider failure (FR-012)
                m = f"Couldn't auto-fill ({type(e).__name__}) — edit manually."
                return self._json({"ok": False, "error": m}) if js else \
                    self._html(profile_page(flash=m, kind="warn", draft={"resume_text": text}))
            if js:
                return self._json({"ok": True, "name": out["name"], "headline": out["headline"],
                                   "scoring_prompt": out["scoring_prompt"]})
            return self._html(profile_page(  # no-JS fallback: replace fields inline (FR-004)
                draft={"name": out["name"], "headline": out["headline"],
                       "prompt": out["scoring_prompt"], "resume_text": text},
                flash="Auto-filled — review and edit, then Save."))
        if path == "/settings":
            write_env(g("provider", "claude_code"), g("key"))
            srcs = {s: {"enabled": (f"src_{s}" in d)} for s in SOURCE_NAMES}
            companies = []
            for line in g("companies").splitlines():
                parts = [x.strip() for x in line.split(",")]
                if len(parts) == 3 and all(parts):
                    companies.append({"name": parts[0], "ats": parts[1], "slug": parts[2]})
            cur = load_sources()
            cur["sources"] = srcs
            if companies:
                cur["companies"] = companies
            write_json(SOURCES_FILE, cur)
            return self._html(settings_page(flash="Settings saved."))
        if path == "/profile":
            p = load_profile()
            p.update({"name": g("name"), "headline": g("headline"),
                      "output_language": g("output_language", "en"),
                      "comp_floor_net_mo_usd": float(g("comp_floor", "0") or 0),
                      "prompt": g("prompt"), "resume_text": g("resume_text")})
            p.pop("_comment", None)
            write_json(PROFILE_FILE, p)
            return self._html(profile_page(flash="Profile saved."))
        if path == "/run":
            ok, msg = run_ready()
            if not ok:
                return self._html(board_page(flash="⚠ " + msg, kind="warn"))
            run_now()
            note = ("" if PROFILE_FILE.exists()
                    else " (heads up: you're on the example profile — set yours in Profile)")
            return self._html(board_page(flash="Run started in the background — refresh in a minute." + note))
        if path == "/schedule":
            preset = g("preset", "2")
            hours = (g("hours") if preset == "custom" else SCHEDULE_PRESETS.get(preset, SCHEDULE_PRESETS["2"])[0])
            hours = ",".join(h for h in re.findall(r"\d{1,2}", hours or "") if int(h) <= 23) or "9,17"
            minute = str(min(59, max(0, int((re.sub(r"\D", "", g("minute", "10")) or "10")))))
            cron_set(True, hours, minute)
            return self._html(board_page(flash=f"Scheduled: daily at minute {minute} of hours {hours}."))
        if path == "/unschedule":
            cron_set(False)
            return self._html(board_page(flash="Unscheduled — no more cron runs."))
        if path == "/apply-confirm":
            rk = g("role")
            if rk:
                store.mark(rk, "applied", comment=g("notes"), source="ui", resume=g("resume"))
                _add_applied(rk)
            return self._html(applied_page(flash="Logged — now tracked under Applied."))
        if path == "/track":
            sid = g("id")
            status = g("status", "applied")
            if sid and status in store.APP_STATUSES:
                store.set_status(sid, status, g("status_note"))
            return self._html(applied_page(flash="Status updated."))
        if path == "/improve":
            return self._html(improve_result(tune.tune(store.labeled_decisions(require_raw=True))))
        if path == "/improve-apply":
            try:
                w = json.loads(g("weights", "{}"))
                if w:
                    store.set_weights(w)
            except json.JSONDecodeError:
                pass
            return self._redirect("/")
        self.send_error(404)

    def log_message(self, *_):
        pass


def _add_applied(role_key):
    if not role_key:
        return
    st = json.loads(STATE.read_text()) if STATE.exists() else {"last_review": None, "reviewed": [], "applied": []}
    if role_key not in st.get("applied", []):
        st.setdefault("applied", []).append(role_key)
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(st, ensure_ascii=False, indent=2))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--open", action="store_true", help="open the browser")
    a = ap.parse_args()
    url = f"http://localhost:{a.port}/"
    print(f"Yoke control panel → {url}  (Ctrl-C to stop)", file=sys.stderr)
    if a.open:
        import webbrowser
        webbrowser.open(url)
    try:
        HTTPServer(("127.0.0.1", a.port), Handler).serve_forever()
    except KeyboardInterrupt:
        print("\nstopped", file=sys.stderr)


if __name__ == "__main__":
    main()
