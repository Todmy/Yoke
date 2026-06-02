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
from urllib.parse import parse_qs

sys.path.insert(0, str(Path(__file__).resolve().parent))
import store  # noqa: E402
import tune  # noqa: E402
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
PROVIDERS = ["claude_code", "openrouter", "openai", "anthropic", "groq",
             "together", "deepinfra", "ollama", "lmstudio"]
SOURCE_NAMES = ["ats", "remoteok", "remotive", "weworkremotely", "hackernews", "dorks", "jobspy"]
LANGS = ["en", "uk", "de", "fr", "es", "pl"]


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
.counts { margin-top: 8px; font-size: 13px; color: #aab3c5; } .counts b { color: #e6e6e6; }
nav { display: flex; gap: 14px; align-items: center; margin-bottom: 8px; flex-wrap: wrap; }
nav a { color: #9aa4b6; text-decoration: none; font-size: 13px; font-weight: 600; }
nav a.on { color: #7db4ff; }
nav .spacer { flex: 1; }
nav button { border: 0; border-radius: 4px; padding: 4px 10px; cursor: pointer; font-weight: 700; font-size: 12px; }
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
.act { display: flex; gap: 4px; align-items: center; flex-wrap: wrap; }
.act button { border: 0; border-radius: 4px; padding: 4px 8px; cursor: pointer; font-weight: 700; }
.act .ok { background: #1f5e35; color: #d6ffe0; } .act .no { background: #5e2530; color: #ffd6dd; }
.act select, .act .cmt { background: #11151c; color: #cfd6e4; border: 1px solid #2a2f3a; border-radius: 4px; padding: 3px 5px; font-size: 12px; } .act .cmt { width: 110px; }
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
.toast { position: fixed; top: 16px; right: 16px; z-index: 50; max-width: 440px; padding: 10px 14px; border-radius: 8px; font-size: 13px; box-shadow: 0 8px 24px rgba(0,0,0,.45); animation: toastin .18s ease-out, toastout .5s ease 4.5s forwards; }
.toast.ok { background: #1f5e35; color: #d6ffe0; }
.toast.warn { background: #5a4a1c; color: #ffe9b0; border: 1px solid #8a6d1f; }
.toast.error { background: #5e2530; color: #ffd6dd; border: 1px solid #8a3a48; }
@keyframes toastin { from { opacity: 0; transform: translateY(-8px); } }
@keyframes toastout { to { opacity: 0; visibility: hidden; } }
nav a.schedlink { background: #1f5e35; color: #d6ffe0; padding: 4px 10px; border-radius: 4px; }
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
    return ('<nav>' + lk("/", "Board") + lk("/settings", "Settings") + lk("/profile", "Profile")
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
def _actions(r):
    rk = _esc(r.get("role_key"))
    opts = "".join(f"<option>{o}</option>" for o in REASONS)
    return ('<form method="post" action="/mark" class="act">'
            f'<input type="hidden" name="role_key" value="{rk}">'
            '<button name="decision" value="applied" class="ok" title="applied">✓</button>'
            f'<select name="reason"><option value="">reason…</option>{opts}</select>'
            '<button name="decision" value="rejected" class="no" title="reject">✗</button>'
            '<input name="comment" placeholder="comment" class="cmt"></form>')


def _row(r):
    url = r.get("url") or ""
    title = _esc(r.get("title"))
    role_cell = f'<a href="{_esc(url)}" target="_blank" rel="noopener">{title}</a>' if url.startswith("http") else title
    return ("<tr>"
            f'<td class="fit">{_esc(r.get("fit"))} {_esc(r.get("label"))}</td>'
            f'<td class="geo">{_esc(r.get("geo"))}</td><td class="role">{role_cell}</td>'
            f'<td class="company">{_esc(r.get("company"))}</td><td class="comp">{_esc(r.get("comp"))}</td>'
            f'<td class="note">{_esc(r.get("note"))}</td><td class="act-cell">{_actions(r)}</td></tr>')


def board_page(flash="", kind="ok"):
    b = store.load()
    c = store.label_counts()
    roles = sorted(b["roles"], key=lambda r: (TIER_ORDER.get(r.get("tier", "B"), 1), -int(r.get("fit") or 0)))
    sections = []
    for tier in ("A", "B", "C"):
        chunk = [r for r in roles if r.get("tier") == tier]
        if not chunk:
            continue
        rows = "".join(_row(r) for r in chunk)
        sections.append(f"<h2>{TIER_TITLE[tier]} ({len(chunk)})</h2>"
                        "<table><tr><th>Fit</th><th>Geo</th><th>Role</th><th>Company</th>"
                        f"<th>Comp</th><th>Note</th><th>Action</th></tr>{rows}</table>")
    body = "".join(sections) or '<div class="card">Board is empty. Set a provider in <a href="/settings">Settings</a> and your CV in <a href="/profile">Profile</a>, then hit <b>▶ Run now</b>.</div>'
    tunable = store.labeled_decisions(require_raw=True)
    n_pos = sum(1 for l in tunable if l["decision"] in ("applied", "interested"))
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
            f'<div class="sub">{len(roles)} roles to review · auto-refresh 60s · ✓ applied / ✗ reject</div>'
            f'<div class="counts">{gate}</div></header>{fl}<main>{body}</main></body></html>')


# ── settings (A) ─────────────────────────────────────────────────────────────
def settings_page(flash=""):
    env = read_env()
    src = load_sources()
    enabled = src.get("sources", {})
    companies = src.get("companies", [])
    comp_text = "\n".join(f"{c.get('name','')},{c.get('ats','')},{c.get('slug','')}" for c in companies)
    prov_opts = "".join(
        f'<option value="{p}"{" selected" if p == env["provider"] else ""}>{p}</option>' for p in PROVIDERS)
    checks = "".join(
        f'<label><input type="checkbox" name="src_{s}" {"checked" if enabled.get(s, {}).get("enabled", s != "jobspy") else ""}> {s}</label>'
        for s in SOURCE_NAMES)
    keyhint = "key on file ✓ (leave blank to keep)" if env["has_key"] else "paste key (blank = none / local model / Claude session)"
    body = f"""<form class="cfg" method="post" action="/settings">
<div class="card">
<h2 style="margin-top:0">AI provider</h2>
<label>Provider</label>
<select name="provider">{prov_opts}</select>
<label>API key — {keyhint}</label>
<input type="password" name="key" placeholder="sk-… (or empty)">
<p class="sub">claude_code = your Claude subscription (no key needed in an interactive run; a token is needed for cron — see Schedule). ollama / lmstudio = local, no key.</p>
</div>
<div class="card">
<h2 style="margin-top:0">Sources</h2>
<div class="checks">{checks}</div>
<p class="sub">jobspy (LinkedIn/Indeed) off by default — those sites restrict scraping.</p>
<label>Target companies (one per line: <code>name,ats,slug</code>; ats = greenhouse|lever|ashby)</label>
<textarea name="companies">{_esc(comp_text)}</textarea>
</div>
<button class="save" type="submit">Save settings</button>
</form>"""
    return _page("settings", body, active="/settings", flash=flash)


# ── profile (B) ──────────────────────────────────────────────────────────────
def profile_page(flash=""):
    p = load_profile()
    lang_opts = "".join(
        f'<option value="{l}"{" selected" if l == p.get("output_language", "en") else ""}>{l}</option>' for l in LANGS)
    body = f"""<form class="cfg" method="post" action="/profile">
<div class="card">
<h2 style="margin-top:0">Who you are</h2>
<label>Name</label><input type="text" name="name" value="{_esc(p.get('name',''))}">
<label>Headline</label><input type="text" name="headline" value="{_esc(p.get('headline',''))}">
<label>Output language</label><select name="output_language">{lang_opts}</select>
<label>Comp floor (net USD/mo, 0 = none)</label><input type="number" name="comp_floor" value="{_esc(p.get('comp_floor_net_mo_usd',0))}">
</div>
<div class="card">
<h2 style="margin-top:0">Scoring profile (prompt)</h2>
<p class="sub">Fed to the model verbatim. Describe your lane, differentiators, seniority, languages, geo, comp. Be specific.</p>
<textarea name="prompt">{_esc(p.get('prompt',''))}</textarea>
<label>Resume text (paste — optional; appended to the prompt so scoring sees your CV)</label>
<textarea name="resume_text" placeholder="paste your CV text here…">{_esc(p.get('resume_text',''))}</textarea>
</div>
<button class="save" type="submit">Save profile</button>
</form>"""
    return _page("profile", body, active="/profile", flash=flash)


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

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/", ""):
            return self._html(board_page())
        if path == "/settings":
            return self._html(settings_page())
        if path == "/profile":
            return self._html(profile_page())
        if path == "/schedule":
            return self._html(schedule_page())
        self.send_error(404)

    def do_POST(self):
        path = self.path.split("?")[0]
        n = int(self.headers.get("Content-Length") or 0)
        d = parse_qs(self.rfile.read(n).decode("utf-8")) if n else {}
        g = lambda k, default="": (d.get(k) or [default])[0]
        try:
            return self._post(path, d, g)
        except Exception as e:  # any handler failure -> a red toast, not a 500
            return self._html(board_page(flash=f"⚠ {type(e).__name__}: {e}", kind="error"))

    def _post(self, path, d, g):
        if path == "/mark":
            rk, dec = g("role_key"), g("decision")
            if rk and dec in ("applied", "rejected", "interested"):
                store.mark(rk, dec, g("reason"), g("comment"), source="ui")
                if dec == "applied":
                    _add_applied(rk)
            return self._redirect("/")
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
