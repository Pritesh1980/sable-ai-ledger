# Sable AI usage

**Sable AI Ledger**: https://claude.ai/artifact/9rkccTsV3vvha7mtggGaTh
Source `ledger/index.html`. GSAP 3.15 and ECharts 6.1 from jsDelivr,
Marcellus and Archivo from Google Fonts, Sable's v2 palette. Loads `data/*.json`
published beside the page. The earlier Dashboard-type page was retired on
2026-10-21; its source is kept in `retired/dashboard/`. For raw rows, read `out/*.json`.

`ingest.py` reads the AI logs on this Mac and writes one JSON file per dataset to
`out/`. Standard library only, Python 3.8+.

| Source | Path | What it gives |
|---|---|---|
| Claude Code transcripts | `~/.claude/projects/-Users-pritesh-code-tattoo-app/` | Tokens, cache, thinking, model, branch per reply |
| Codex sessions | `~/.codex/sessions/` and `archived_sessions/`, plain or `.jsonl.zst` (filtered to this repo; needs the `zstd` tool) | Tokens per call, model, role, branch |
| Antigravity (agy CLI and IDE) | `~/.gemini/antigravity-cli/` and `~/.gemini/antigravity/`, one SQLite file per conversation in `conversations/` | Tokens per generation, model (mostly Gemini) |
| Gemini CLI (before agy) | `~/.gemini/tmp/<project>/chats/` | Tokens per reply, model |
| git + GitHub (`gh`) | the repo | PRs, issues, CI runs, diff sizes, rework |

Do ledger work from this folder: `cd ~/code/ai-usage && claude`. A session started in
the Sable checkout logs its transcript under Sable's project folder, so its cost is
booked to Sable. The ingest leaves a commit made into another repo under `~/code`
unattributed rather than booking it to a Sable task, but every other reply in that
session still counts as Sable usage.

## Refresh

Ask Claude Code: "refresh the Sable AI ledger". It runs `python3 ingest.py`, copies
`ledger/index.html` and `out/{daily,tasks,prices,waveform}.json` into its scratchpad
(published files must live there or in the working directory) and republishes to the
ledger URL with the JSON files under `data/`.

## Daily refresh

Two halves, because the logs live on this Mac but headless `claude -p` has no
Artifact tool (tested 2026-10-26), so it can't publish:

1. **07:43, this Mac.** launchd runs `refresh.sh`, or runs it on wake if the Mac was
   asleep. It runs the tests and the ingest, commits `out/` if anything changed, and
   pushes to the private repo https://github.com/Pritesh1980/sable-ai-ledger. It
   shows a macOS notification if anything fails.
2. **08:13 UTC, the cloud.** The routine "Sable AI Ledger: daily republish"
   (https://claude.ai/code/routines/trig_01VUxd2ZaoXVZNKrvfjTSHRX) clones that repo and
   republishes the page from `ledger/index.html` and `out/*.json`. It runs on Sonnet 5.5
   with only the Artifact, Read, Bash and Glob tools, and no Gmail, Drive or Calendar
   connectors. Its runs are listed on the routine's page.

If the Mac sleeps through both times, the page shows the previous day's data until
the next morning. Change the page itself by committing `ledger/index.html` and
pushing: the next routine run publishes it.

- Log: `~/Library/Logs/ai-ledger-refresh.log`
- Run now: `launchctl kickstart gui/$(id -u)/local.sable.ai-ledger` (or `./refresh.sh`)
- Install (done 2026-10-26): `cp launchd/local.sable.ai-ledger.plist ~/Library/LaunchAgents/ && launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/local.sable.ai-ledger.plist`
- Stop: `launchctl bootout gui/$(id -u)/local.sable.ai-ledger && rm ~/Library/LaunchAgents/local.sable.ai-ledger.plist`

The ingest refuses to write `out/` when any past day holds fewer tokens than the last
snapshot for the same tool, which means logs went missing. That is what happened on 2026-10-26, when
Codex began compressing old sessions to `.jsonl.zst`. Find the logs, or rerun with
`python3 ingest.py --allow-shrink` to accept the loss.

## Tests

    python3 -m unittest -v

## Version control

This folder is a git repository, pushed to the private GitHub repo
`Pritesh1980/sable-ai-ledger` (since 2026-10-26). The daily job commits and pushes
data. Commit and push page or script changes yourself. `out/` is committed on purpose: Claude Code deletes its transcripts
after `cleanupPeriodDays`, so each commit of `out/*.json` keeps a snapshot of numbers
the logs may no longer hold.

## Notes

- Claude Code deletes transcripts after `cleanupPeriodDays` (now 365 in
  `~/.claude/settings.json`; it was the 30-day default until 2026-10-21, so older
  history is gone).
- The IJFW session log (`tattoo-app/.ijfw/metrics/sessions.jsonl`) is deliberately
  not used. It records running totals for long, parallel sessions; summed it showed
  $172k for August, and even untangled into per-session amounts it came out 1.5 to
  2.3 times the transcripts for the same 30 days.
- Codex and Gemini have no list prices here, so they are compared on tokens, not dollars.
- Antigravity stores each conversation as SQLite rows of protobuf with no published
  schema. `ingest.py` reads a copy of each file (so a running agy is never locked) and
  decodes the few fields it needs: the field numbers are noted in
  `antigravity_generation()`, read off real conversations in October 2026. If an agy
  update moves them, the Antigravity rows vanish and the shrink guard stops the refresh.
- Many agy runs record no folder. A conversation counts for Sable when Antigravity
  recorded Sable's folder (a worktree or a Claude Code scratchpad of this repo counts),
  else when the agy CLI log or prompt history names its folder, else when its request
  names Sable (or tattoo) and no other project folder. Everything else is left out:
  on 2026-10-26 that was 60 of 123 conversations, some of them reviews for other projects.
  The CLI logs get pruned, so the folders they name are kept in
  `out/antigravity_folders.json`.
- Prices are in `PRICES` at the top of `ingest.py`; update them and `PRICES_AS_OF`
  when Anthropic changes list prices.
- The model palette in `ledger/index.html` was checked with the dataviz skill's
  `validate_palette.js` against the ink background; keep its fixed order.
