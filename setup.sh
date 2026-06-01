#!/usr/bin/env bash
# One-shot installer for Yoke.
#   ./setup.sh              interactive install (auth + profile + optional venv + cron)
#   ./setup.sh --dry-run    show what it WOULD do, change nothing
#   ./setup.sh --uninstall  remove the cron entry
#   ./setup.sh --no-venv    skip the jobspy venv (LinkedIn/Indeed sources)
#
# Paths derive from this script's location (works from any clone). The crontab
# edit is idempotent (tagged line, existing entries preserved) and no secret is
# ever passed on the command line. macOS + Linux (cron). Windows: use Task Scheduler.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
S="$REPO/src"
YOKE_HOME="${YOKE_HOME:-$HOME/.yoke}"
ENV_FILE="${YOKE_ENV:-$HOME/.config/yoke.env}"
VENV="$REPO/.venv"
TAG="# yoke-auto"
CRON_LINE="10 9,17 * * * /bin/bash $S/run.sh all --days 3 >> /tmp/yoke-cron.log 2>&1 $TAG"

DRY=0; UNINSTALL=0; WANT_VENV=1
for a in "$@"; do case "$a" in
  --dry-run) DRY=1 ;; --uninstall) UNINSTALL=1 ;; --no-venv) WANT_VENV=0 ;;
  -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
  *) echo "unknown arg: $a" >&2; exit 1 ;;
esac; done

say() { printf '\033[36m›\033[0m %s\n' "$*"; }
warn() { printf '\033[33m!\033[0m %s\n' "$*"; }
run() { if [ "$DRY" = 1 ]; then echo "  [dry-run] $*"; else eval "$*"; fi; }

if [ "$UNINSTALL" = 1 ]; then
  say "Removing Yoke cron entry…"
  if crontab -l 2>/dev/null | grep -q "$TAG"; then
    run "crontab -l 2>/dev/null | grep -v '$TAG' | crontab -"
    say "Removed. (Token file $ENV_FILE and $YOKE_HOME left in place.)"
  else
    say "No Yoke cron entry found."
  fi
  exit 0
fi

echo "── Yoke setup ──  repo: $REPO   data: $YOKE_HOME"

# ── 1. prerequisites ─────────────────────────────────────────
command -v python3 >/dev/null || { warn "python3 not found — install it first."; exit 1; }
say "python3: $(python3 --version 2>&1)"
command -v claude >/dev/null && say "claude CLI: found" \
  || warn "claude CLI not found — fine if you use a provider key (OpenRouter/OpenAI/Ollama/…)."

# ── 2. config: profile + sources (copied from examples on first run) ─
run "mkdir -p '$YOKE_HOME/config'"
if [ -f "$YOKE_HOME/config/profile.json" ]; then
  say "profile.json present."
else
  run "cp '$REPO/config/profile.example.json' '$YOKE_HOME/config/profile.json'"
  warn "Edit $YOKE_HOME/config/profile.json with your CV + constraints before the first real run."
fi
[ -f "$YOKE_HOME/config/sources.json" ] || run "cp '$REPO/config/sources.example.json' '$YOKE_HOME/config/sources.json'"

# ── 3. auth (headless): subscription token OR a provider key ─
if [ -f "$ENV_FILE" ] && grep -qE '(CLAUDE_CODE_OAUTH_TOKEN|OPENROUTER_API_KEY|YOKE_API_KEY)=.+' "$ENV_FILE"; then
  say "Auth already set in $ENV_FILE — keeping it."
elif [ "$DRY" = 1 ]; then
  echo "  [dry-run] would prompt for a token/key -> $ENV_FILE"
else
  echo
  say "Headless auth (cron can't reach the OS keychain)."
  echo "  A) Claude subscription: run  claude setup-token  in another terminal, paste the token."
  echo "  B) Provider key:        paste an sk-or-… (OpenRouter) or other provider key."
  echo "  (Skip if you'll use a local model like Ollama — set YOKE_PROVIDER=ollama instead.)"
  printf "Paste token/key (hidden, Enter to skip): "
  read -rs SECRET; echo
  if [ -n "$SECRET" ]; then
    mkdir -p "$(dirname "$ENV_FILE")"
    case "$SECRET" in
      sk-or-*) echo "export OPENROUTER_API_KEY=$SECRET" > "$ENV_FILE"; say "Saved OpenRouter key." ;;
      *)       echo "export CLAUDE_CODE_OAUTH_TOKEN=$SECRET" > "$ENV_FILE"; say "Saved Claude subscription token." ;;
    esac
    chmod 600 "$ENV_FILE"
  else
    warn "No token entered — set auth in $ENV_FILE later, or use a local model (YOKE_PROVIDER=ollama)."
  fi
fi

# ── 4. jobspy venv (optional — adds LinkedIn/Indeed/Google sources) ──
if [ "$WANT_VENV" = 1 ]; then
  if [ -x "$VENV/bin/python" ]; then
    say "jobspy venv: present."
  else
    say "Creating jobspy venv (optional LinkedIn/Indeed sources)…"
    run "python3 -m venv '$VENV'"
    run "'$VENV/bin/pip' -q install --upgrade pip python-jobspy pandas"
  fi
else
  warn "Skipping jobspy venv (--no-venv): ATS / HN / RSS / dorks still work."
fi

# ── 5. cron (idempotent via tag; preserves existing entries) ─
say "Installing cron entry (twice daily 09:10 / 17:10):"
echo "    $CRON_LINE"
if crontab -l 2>/dev/null | grep -q "$TAG"; then
  run "( crontab -l 2>/dev/null | grep -v '$TAG'; echo '$CRON_LINE' ) | crontab -"
  say "Updated Yoke cron entry."
else
  run "( crontab -l 2>/dev/null; echo '$CRON_LINE' ) | crontab -"
  say "Added Yoke cron entry."
fi

echo
say "Done.${DRY:+ (dry-run — nothing changed)}"
echo "  • Edit profile:  \$EDITOR $YOKE_HOME/config/profile.json"
echo "  • Live board:    $REPO/yoke serve --open    (or: python3 $S/serve.py --open)"
echo "  • Run now:       $REPO/yoke run all --days 7"
echo "  • Uninstall:     $REPO/yoke uninstall"
echo "  • macOS: if cron does nothing, grant Full Disk Access to /usr/sbin/cron in System Settings › Privacy."
