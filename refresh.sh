#!/bin/bash
# Daily refresh of the Sable AI Ledger data: rebuild it from this Mac's logs and
# commit the snapshot.
# launchd runs it every morning (launchd/local.sable.ai-ledger.plist). Safe to run by hand.
set -euo pipefail
export PATH="$HOME/.local/bin:/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
cd "$(dirname "$0")"

URL=https://claude.ai/artifact/9rkccTsV3vvha7mtggGaTh
PY="$HOME/.pyenv/versions/3.8.2/bin/python3"
[ -x "$PY" ] || PY=python3
LOG="$HOME/Library/Logs/ai-ledger-refresh.log"

notify() { osascript -e "display notification \"$1\" with title \"Sable AI Ledger\"" >/dev/null 2>&1 || true; }
trap 'notify "Refresh failed. See $LOG"; echo "FAILED at line $LINENO" >&2' ERR

echo "== $(date '+%F %T')"
"$PY" -m unittest -q 2>&1 | tail -1
"$PY" ingest.py          # stops without writing if any past day lost tokens
if git diff --quiet -- out; then
  echo "No new usage since the last refresh."
  exit 0
fi
git add out
git commit -q -m "data: refresh $(date +%F)"
echo "Committed $(git rev-parse --short HEAD)"

# Publishing the page ($URL) needs the Artifact tool, which only interactive
# Claude Code sessions have: `claude -p` gets none (tested 2026-10-26). So this job
# keeps the snapshot safe and current; the page is republished from a session.
