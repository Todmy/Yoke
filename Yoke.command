#!/usr/bin/env bash
# Double-click me (macOS Finder runs .command files in Terminal).
# First run: installs (asks for a token/key). Every run: opens the live board.
cd "$(dirname "$0")"
echo "── Yoke ──"
if ! crontab -l 2>/dev/null | grep -q "# yoke-auto"; then
  echo "First run — setting up (config + auth + cron)…"
  bash ./setup.sh || { echo "Setup did not finish. Double-click again to retry."; read -r; exit 1; }
fi
echo "Opening the live board… (close this window to stop the server)"
exec ./yoke serve --open
