#!/bin/bash
# Daily refresh of the Sable AI Ledger data: rebuild it from this Mac's logs and
# commit the snapshot.
# launchd runs it every morning (launchd/local.sable.ai-ledger.plist). Safe to run by hand.
set -euo pipefail
export PATH="$HOME/.local/bin:/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
cd "$(dirname "$0")"

PY="$HOME/.pyenv/versions/3.8.2/bin/python3"
[ -x "$PY" ] || PY=python3
LOG="$HOME/Library/Logs/ai-ledger-refresh.log"

notify() { osascript -e "display notification \"$1\" with title \"Sable AI Ledger\"" >/dev/null 2>&1 || true; }
trap 'notify "Refresh failed. See $LOG"; echo "FAILED at line $LINENO" >&2' ERR

echo "== $(date '+%F %T')"
# Catch up with GitHub first. Page and script changes are pushed from elsewhere
# (cloud sessions), and a main that's behind origin can't push the day's data.
# --rebase replays any data commit a failed run left unpushed on top.
git pull -q --rebase --autostash origin main
"$PY" -m unittest -q 2>&1 | tail -1
"$PY" ingest.py          # stops without writing if any past day lost tokens
if git diff --quiet -- out; then
  echo "No new usage since the last refresh."
else
  git add out
  git commit -q -m "data: refresh $(date +%F)"
  echo "Committed $(git rev-parse --short HEAD)"
fi

# Push anything unpushed. The push redeploys the GitHub Pages site
# (.github/workflows/pages.yml).
if [ -n "$(git log origin/main..HEAD --oneline)" ]; then
  # GitHub sometimes answers a push with a 500 that clears on retry
  # (seen 2026-11-04), so try up to 4 times before failing the run.
  for attempt in 1 2 3 4; do
    if git push -q origin main; then
      echo "Pushed to origin/main"
      break
    fi
    [ "$attempt" -lt 4 ] || false   # out of tries: fails the run, ERR trap notifies
    echo "Push failed (attempt $attempt), retrying in 20s"
    sleep 20
  done
fi
