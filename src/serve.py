#!/usr/bin/env python3
"""Local web viewer for the jobsearch board (slice 2 — read-only).

stdlib http.server + the SQLite store. Zero dependencies, cross-platform:
    python3 scripts/serve.py [--port 8765] [--open]
Open the printed URL. The page auto-refreshes (60s) so it tracks cron updates.
Marking (applied/reject + comment) and the Improve button arrive in later slices.
"""
import argparse
import html
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs

sys.path.insert(0, str(Path(__file__).resolve().parent))
import store  # noqa: E402
import tune  # noqa: E402
from paths import STATE  # noqa: E402

NEED_LABELS = 12  # min raw-feature labels (both classes) before Improve unlocks

TIER_TITLE = {"A": "Tier A — apply", "B": "Tier B — worth a look", "C": "Tier C"}
TIER_ORDER = {"A": 0, "B": 1, "C": 2}
REASONS = ["off-lane", "geo", "comp", "seniority", "not-interesting", "lang", "other"]


def _add_applied(role_key):
    """Mirror an applied decision into review-state.json so /jobsearch never re-surfaces it."""
    if not role_key:
        return
    st = json.loads(STATE.read_text()) if STATE.exists() else {"last_review": None, "reviewed": [], "applied": []}
    if role_key not in st.get("applied", []):
        st.setdefault("applied", []).append(role_key)
        STATE.write_text(json.dumps(st, ensure_ascii=False, indent=2))

CSS = """
* { box-sizing: border-box; }
body { font: 15px/1.5 -apple-system, system-ui, sans-serif; margin: 0; background: #0f1115; color: #e6e6e6; }
header { padding: 18px 24px; border-bottom: 1px solid #262a33; position: sticky; top: 0; background: #0f1115; }
h1 { font-size: 18px; margin: 0 0 4px; }
.sub { color: #8b93a3; font-size: 13px; }
.counts { margin-top: 8px; font-size: 13px; color: #aab3c5; }
.counts b { color: #e6e6e6; }
main { padding: 12px 24px 48px; }
h2 { font-size: 14px; text-transform: uppercase; letter-spacing: .06em; color: #9aa4b6; margin: 24px 0 8px; }
table { width: 100%; border-collapse: collapse; }
th, td { text-align: left; padding: 8px 10px; border-bottom: 1px solid #1d2129; vertical-align: top; }
th { font-size: 12px; color: #788196; font-weight: 600; }
tr:hover td { background: #161a21; }
.fit { font-weight: 700; white-space: nowrap; }
.role a { color: #7db4ff; text-decoration: none; }
.role a:hover { text-decoration: underline; }
.company { color: #cfd6e4; }
.note { color: #8b93a3; font-size: 13px; max-width: 360px; }
.geo { white-space: nowrap; font-size: 13px; }
.comp { white-space: nowrap; color: #b8e6c0; font-size: 13px; }
.added { color: #6b7280; font-size: 12px; white-space: nowrap; }
.banner { background: #1c2530; color: #9cc4ff; padding: 6px 24px; font-size: 13px; }
.act { display: flex; gap: 4px; align-items: center; flex-wrap: wrap; }
.act button { border: 0; border-radius: 4px; padding: 4px 8px; cursor: pointer; font-weight: 700; }
.act .ok { background: #1f5e35; color: #d6ffe0; }
.act .no { background: #5e2530; color: #ffd6dd; }
.act select, .act .cmt { background: #11151c; color: #cfd6e4; border: 1px solid #2a2f3a; border-radius: 4px; padding: 3px 5px; font-size: 12px; }
.act .cmt { width: 110px; }
.improve { background: #2d4a7a; color: #dce8ff; border: 0; border-radius: 4px; padding: 5px 10px; cursor: pointer; font-weight: 700; }
.improve-off { color: #5a6271; cursor: not-allowed; }
.card { background: #161a21; border: 1px solid #262a33; border-radius: 8px; padding: 16px 20px; margin: 16px 0; max-width: 720px; }
.delta { font-size: 22px; font-weight: 800; }
.up { color: #9cffb0; } .same { color: #8b93a3; }
code { background: #11151c; padding: 2px 5px; border-radius: 3px; }
"""


def _esc(x):
    return html.escape(str(x if x is not None else ""))


def _actions(r):
    rk = _esc(r.get("role_key"))
    opts = "".join(f"<option>{o}</option>" for o in REASONS)
    return (
        '<form method="post" action="/mark" class="act">'
        f'<input type="hidden" name="role_key" value="{rk}">'
        '<button name="decision" value="applied" class="ok" title="подався">✓</button>'
        f'<select name="reason"><option value="">причина…</option>{opts}</select>'
        '<button name="decision" value="rejected" class="no" title="відхилити">✗</button>'
        '<input name="comment" placeholder="коментар" class="cmt">'
        '</form>'
    )


def _row(r):
    url = r.get("url") or ""
    title = _esc(r.get("title"))
    role_cell = f'<a href="{_esc(url)}" target="_blank" rel="noopener">{title}</a>' if url.startswith("http") else title
    return (
        "<tr>"
        f'<td class="fit">{_esc(r.get("fit"))} {_esc(r.get("label"))}</td>'
        f'<td class="geo">{_esc(r.get("geo"))}</td>'
        f'<td class="role">{role_cell}</td>'
        f'<td class="company">{_esc(r.get("company"))}</td>'
        f'<td class="comp">{_esc(r.get("comp"))}</td>'
        f'<td class="note">{_esc(r.get("note"))}</td>'
        f'<td class="act-cell">{_actions(r)}</td>'
        "</tr>"
    )


def render_page():
    b = store.load()
    c = store.label_counts()
    roles = sorted(b["roles"], key=lambda r: (TIER_ORDER.get(r.get("tier", "B"), 1), -int(r.get("fit") or 0)))
    sections = []
    for tier in ("A", "B", "C"):
        chunk = [r for r in roles if r.get("tier") == tier]
        if not chunk:
            continue
        rows = "".join(_row(r) for r in chunk)
        sections.append(
            f"<h2>{TIER_TITLE[tier]} ({len(chunk)})</h2>"
            "<table><tr><th>Fit</th><th>Geo</th><th>Роль</th><th>Компанія</th>"
            f"<th>Comp</th><th>Нюанс</th><th>Дія</th></tr>{rows}</table>")
    body = "".join(sections) or "<p>Дошка порожня — запусти збір/аналіз.</p>"
    applied = c["applied"]
    rej = c["rejected"]
    tunable = store.labeled_decisions(require_raw=True)
    n_pos = sum(1 for l in tunable if l["decision"] in ("applied", "interested"))
    n_neg = sum(1 for l in tunable if l["decision"] == "rejected")
    eligible = n_pos >= 1 and n_neg >= 1 and len(tunable) >= NEED_LABELS
    if eligible:
        improve_btn = ('<form method="post" action="/improve" style="display:inline">'
                       '<button class="improve">⚙ Improve (підігнати ваги)</button></form>')
    else:
        improve_btn = (f'<span class="improve-off" title="треба ≥{NEED_LABELS} міток із сирими '
                       f'фічами та обома класами (зараз tunable: {n_pos}+/{n_neg}−)">⚙ Improve (заблоковано)</span>')
    gate = (f'<b>{c["total"]}</b> міток (applied {applied}, interested {c["interested"]}, rejected {rej}; '
            f'tunable {len(tunable)}). {improve_btn}')
    return f"""<!doctype html><html lang="uk"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="60">
<title>Jobsearch board</title><style>{CSS}</style></head><body>
<header><h1>Jobsearch — жива дошка</h1>
<div class="sub">{len(roles)} ролей на розгляд · авто-оновлення 60с · ✓ подався / ✗ відхилити (+причина, коментар)</div>
<div class="counts">{gate}</div></header>
<div class="banner">Кліки пишуть мітки в БД → роль зникає з дошки → годує флайвіл. Improve (тюнер) — слайс 4.</div>
<main>{body}</main></body></html>"""


def _page(title, body):
    return (f'<!doctype html><html lang="uk"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>{_esc(title)}</title><style>{CSS}</style></head>'
            f'<body><header><h1>{_esc(title)}</h1></header><main>{body}</main></body></html>')


def improve_result(res):
    if not res.get("ok"):
        return _page("Improve", f'<div class="card"><p>Недостатньо даних: {_esc(res.get("reason"))} '
                     f'(pursued {res.get("n_pos")}, rejected {res.get("n_neg")}).</p>'
                     '<p><a href="/">← назад</a></p></div>')
    before, after = res["objective_before"], res["objective_after"]
    delta_cls = "up" if after > before else "same"
    changed = res["changed"]
    rows = "".join(
        f"<tr><td><code>{_esc(k)}</code></td><td>{_esc(res['weights_before'][k])}</td>"
        f"<td><b>{_esc(v)}</b></td></tr>" for k, v in changed.items()
    ) or '<tr><td colspan="3">дефолтні ваги вже оптимальні — змін немає</td></tr>'
    apply_form = ""
    if changed:
        apply_form = ('<form method="post" action="/improve-apply" style="display:inline">'
                      f'<input type="hidden" name="weights" value="{_esc(json.dumps(res["weights_after"]))}">'
                      '<button class="improve">Застосувати нові ваги</button></form>')
    body = (f'<div class="card"><h2 style="margin-top:0">Підгін ваг під твої рішення</h2>'
            f'<p>Мітки: {res["n_pos"]} pursued / {res["n_neg"]} rejected</p>'
            f'<p>Balanced accuracy: <span class="delta {delta_cls}">{before} → {after}</span></p>'
            f'<table><tr><th>Вага</th><th>було</th><th>стало</th></tr>{rows}</table>'
            f'<p style="margin-top:14px">{apply_form} &nbsp; <a href="/">← назад без змін</a></p></div>')
    return _page("Improve", body)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.split("?")[0] not in ("/", ""):
            self.send_error(404)
            return
        body = render_page().encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _redirect(self, to="/"):
        self.send_response(303)
        self.send_header("Location", to)
        self.end_headers()

    def _html(self, s):
        body = s.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        path = self.path.split("?")[0]
        n = int(self.headers.get("Content-Length") or 0)
        data = parse_qs(self.rfile.read(n).decode("utf-8")) if n else {}
        if path == "/mark":
            rk = (data.get("role_key") or [""])[0]
            dec = (data.get("decision") or [""])[0]
            if rk and dec in ("applied", "rejected", "interested"):
                store.mark(rk, dec, (data.get("reason") or [""])[0],
                           (data.get("comment") or [""])[0], source="ui")
                if dec == "applied":
                    _add_applied(rk)
            return self._redirect("/")
        if path == "/improve":
            res = tune.tune(store.labeled_decisions(require_raw=True))
            return self._html(improve_result(res))
        if path == "/improve-apply":
            try:
                w = json.loads((data.get("weights") or ["{}"])[0])
                if w:
                    store.set_weights(w)
            except json.JSONDecodeError:
                pass
            return self._redirect("/")
        self.send_error(404)

    def log_message(self, *_):
        pass  # quiet


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--open", action="store_true", help="open the browser")
    a = ap.parse_args()
    url = f"http://localhost:{a.port}/"
    print(f"jobsearch viewer → {url}  (Ctrl-C to stop)", file=sys.stderr)
    if a.open:
        import webbrowser
        webbrowser.open(url)
    try:
        HTTPServer(("127.0.0.1", a.port), Handler).serve_forever()
    except KeyboardInterrupt:
        print("\nstopped", file=sys.stderr)


if __name__ == "__main__":
    main()
