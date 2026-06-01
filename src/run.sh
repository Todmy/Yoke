#!/usr/bin/env bash
# Yoke pipeline entrypoint — what cron/launchd calls.
#   run.sh [all|collect|analyze|eval] [flags passed to analyze]
#     all       collect -> analyze            (default)
#     collect   gather roles into the index (deterministic)
#     analyze   prepare | analyze -> score onto the board
#     eval      run the eval harness
# Auth for headless runs: put CLAUDE_CODE_OAUTH_TOKEN or a provider key in
# ~/.config/yoke.env (chmod 600); this sources it. Self-locks. Logs to /tmp/yoke-run.log.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"          # the yoke/ dir
LOG="${YOKE_LOG:-/tmp/yoke-run.log}"
LOCKDIR="/tmp/yoke-run.lock.d"
VENV="$HERE/../.venv/bin/python"
SCANPY=$([ -x "$VENV" ] && echo "$VENV" || echo "python3")    # venv only needed for jobspy
PY="python3"

ENV_FILE="${YOKE_ENV:-$HOME/.config/yoke.env}"
[ -f "$ENV_FILE" ] && set -a && . "$ENV_FILE" && set +a

MODE="${1:-all}"; shift 2>/dev/null || true

log() { echo "[$(date '+%F %T')] $*" | tee -a "$LOG" >&2; }

if [ -d "$LOCKDIR" ] && [ -n "$(find "$LOCKDIR" -prune -mmin +60 2>/dev/null)" ]; then
  log "stale lock (>60m) — reclaiming"; rmdir "$LOCKDIR" 2>/dev/null || true
fi
if ! mkdir "$LOCKDIR" 2>/dev/null; then
  log "another run is active — skipping"; exit 0
fi
trap 'rmdir "$LOCKDIR" 2>/dev/null || true' EXIT

run_collect() {
  log "collect ($SCANPY)"
  "$SCANPY" "$HERE/collect.py" 2>>"$LOG" || log "collect: non-zero (continuing)"
}

run_analyze() {
  local prep=() ana=()
  while [ $# -gt 0 ]; do
    case "$1" in
      --days) prep+=("$1" "${2:-}"); shift 2 ;;
      --all|--coverage) prep+=("$1"); shift ;;
      *) ana+=("$1"); shift ;;
    esac
  done
  log "analyze: prepare ${prep[*]:-} | analyze ${ana[*]:-}"
  "$PY" "$HERE/prepare.py" ${prep[@]+"${prep[@]}"} 2>>"$LOG" \
    | "$PY" "$HERE/analyze.py" ${ana[@]+"${ana[@]}"} 2>>"$LOG"
}

run_eval() { log "eval"; "$PY" "$HERE/eval.py" run 2>>"$LOG" || log "eval: gate FAIL or error (see report)"; }

case "$MODE" in
  collect) run_collect ;;
  analyze) run_analyze "$@" ;;
  eval)    run_eval ;;
  all)     run_collect; run_analyze "$@" ;;
  *) echo "usage: run.sh [all|collect|analyze|eval] [flags->analyze]" >&2; exit 1 ;;
esac
log "done ($MODE)"
