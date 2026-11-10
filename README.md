# Sable AI usage

**Sable AI Ledger** (GitHub Pages): https://pritesh1980.github.io/sable-ai-ledger/
Rebuilt by `.github/workflows/pages.yml` on every push that touches `ledger/` or `out/`.
The repo is public (since 2026-11-04), so everything in it, data included, is readable
by anyone. The old claude.ai artifact (https://claude.ai/artifact/9rkccTsV3vvha7mtggGaTh)
is no longer updated.

Source `ledger/index.html`. GSAP 3.15 and ECharts 6.1 from jsDelivr,
Marcellus and Archivo from Google Fonts, Sable's v2 palette. Loads `data/*.json`
published beside the page. The earlier Dashboard-type page was retired on
2026-10-21; its source is kept in `retired/dashboard/`. For raw rows, read `out/*.json`.

`ingest.py` reads every AI log on this Mac, for every project, and writes one JSON file
per dataset to `out/`. Standard library only, Python 3.8+. Each call is booked to the
project it ran in (`project_of()`): Sable for its checkout, its worktrees, sibling
`tattoo-app-*` clones and Claude Code scratchpads of it; otherwise the folder under
`~/code` (or `~/Documents` and the like). Daily rows carry that `project`. Tasks, PRs
and CI come from Sable's git and GitHub only, so only Sable work is attributed to tasks.

| Source | Path | What it gives |
|---|---|---|
| Claude Code transcripts | `~/.claude/projects/` (every project) | Tokens, cache, thinking, model, branch, folder per reply |
| Codex sessions | `~/.codex/sessions/` and `archived_sessions/`, plain or `.jsonl.zst` (needs the `zstd` tool) | Tokens per call, model, role, branch, folder |
| Antigravity (agy CLI and IDE) | `~/.gemini/antigravity-cli/` and `~/.gemini/antigravity/`, one SQLite file per conversation in `conversations/` | Tokens per generation, model (mostly Gemini) |
| Gemini CLI (before agy) | `~/.gemini/tmp/<project>/chats/` | Tokens per reply, model |
| git + GitHub (`gh`) | the Sable repo | PRs, issues, CI runs, diff sizes, rework |

Do ledger work from this folder: `cd ~/code/ai-usage && claude`, so it is booked to the
ai-usage project. A Claude Code reply is booked by the folder its session ran in, so a
session started in the Sable checkout counts as Sable even when it works on another
repo; the ingest only leaves a commit made into another repo under `~/code` off Sable's
tasks.

## Cloud sessions

Claude Code sessions that run in the cloud (claude.ai/code, marked `anthropic_cloud` in
the sessions list) leave no logs on this Mac. Sessions started from the phone through
Remote Control run on the Mac and are already counted. `cloud/claude-cloud-sessions.json`
holds per-day token counts for cloud sessions, imported by hand: the ingest adds them
to the daily rows as Claude Code, role main, with no task, rebuilds or per-call detail.

Imported on 2026-11-08 from the sessions API (via a Claude session's session tools):
"Sable work history" (Sable, 4-7 Nov) and "Ledger status check" (ai-usage, 31 Oct-8 Nov).
Each session's totals (`get_session`) are exact. The per-day split comes from its reply
events: cache reads and writes by day, with what the events did not reach put on the
session's first day; input and output are spread by cache reads, because streamed
events under-report them. To add a session, append it in the same shape.

Not counted at all: Codex cloud, and chats in the Claude or ChatGPT apps.

## Refresh

Run `./refresh.sh`. It ingests, commits `out/` and pushes; the push redeploys the page.
The Pages workflow adds the document skeleton (`<!doctype html>`, charset, viewport)
in front of `ledger/index.html` and copies `out/{daily,tasks,prices,waveform}.json`
and `out/meta.json` to `data/`, which is where the page fetches them from. `meta.json`
holds the time of the last refresh, which the page shows as "Last updated" beside
"Data through" (the latest call in the data). `out/insights.json` is copied too.

## Tips and trends

Every ingest also writes `out/insights.json`: tips on working better and trends worth
knowing, from `insights()` in `ingest.py`. The page shows them under "Tips and trends",
and the ingest prints them at the end of its summary. Weeks count back from the last day
Claude Code was used. Each rule speaks only when the data backs it:

- **Models**: Opus took 80%+ of Claude spend over 28 days, and shipped small or medium
  tasks cost Sonnet under 60% of what they cost Opus (at least 3 tasks each).
- **Context**: replies read 150k+ tokens on average this week; otherwise a 20%+ drop is
  noted as a trend.
- **Cache rebuilds**: 3+ rebuilds costing $1+ this week.
- **CI**: first-time CI passes over the last 14 days at least 10 points below earlier
  tasks (a tip), or 10 points above (a trend). Needs 4+ tasks on each side.
- **Rework**: 5+ later commits touched files from tasks shipped in the last 28 days.
- **Spend, tools and the biggest task** (trends): this week's Claude spend against last
  week's; a 2x swing in calls for a tool with 100+ calls; and a task started this week
  that cost twice the median shipped task or more.

Tips come first, then trends, at most 8 in all.

## Sable timeline

The page's "Who worked when" section is a git graph with the AIs as branches. Claude Code's lane
sits above main, and Codex and Antigravity each have a lane below it. Every task is a line
that forks off main into the lane of the AI working on it, crosses to another lane when a
different AI takes over (a review, say), and joins main again with a dot where it merged
(`merges` in `out/waveform.json`, from main's first-parent history; a hollow dot when the PR
merged into another branch). Lines that are live at the same time get their own track in a lane.
Capsules on a line are stretches of work, split wherever a session sat idle for over 30
minutes; hollow ones are reviewing. Work not tied to a task sits faintly at the top of its lane.
Clicking a line opens the relay for its task below. Sable calls only, last 30 days. Each
waveform row ends with project and session indices (into `projects` and `sessions`).

## Daily refresh

At 05:00 launchd runs `refresh.sh` on this Mac, or runs it on wake if the Mac was
asleep. It pulls from GitHub first (so a page or script change pushed from elsewhere
can't block its push), then runs the tests and the ingest, commits `out/` (every run,
since `meta.json` stamps each one; the commit says "no new usage" when only that
changed), and pushes to https://github.com/Pritesh1980/sable-ai-ledger. That push runs
the Pages workflow. It shows a macOS notification if anything fails.

If the Mac sleeps all day, the page shows the previous day's data until the next run.
Change the page itself by committing `ledger/index.html` and pushing.

Until 2026-11-04 a cloud routine republished the claude.ai artifact at 08:13 UTC
(https://claude.ai/code/routines/trig_01VUxd2ZaoXVZNKrvfjTSHRX, now disabled; delete
it there). Its prompt and `check_live.py` are in git history before that date.

- Log: `~/Library/Logs/ai-ledger-refresh.log`
- Run now: `launchctl kickstart gui/$(id -u)/local.sable.ai-ledger` (or `./refresh.sh`)
- Install (done 2026-10-26): `cp launchd/local.sable.ai-ledger.plist ~/Library/LaunchAgents/ && launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/local.sable.ai-ledger.plist`
- Reload after changing the plist: `launchctl bootout gui/$(id -u)/local.sable.ai-ledger; cp launchd/local.sable.ai-ledger.plist ~/Library/LaunchAgents/ && launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/local.sable.ai-ledger.plist`
- Stop: `launchctl bootout gui/$(id -u)/local.sable.ai-ledger && rm ~/Library/LaunchAgents/local.sable.ai-ledger.plist`

The ingest refuses to write `out/` when any past day holds fewer tokens than the last
snapshot for the same tool, which means logs went missing. That is what happened on 2026-10-26, when
Codex began compressing old sessions to `.jsonl.zst`. Find the logs, or rerun with
`python3 ingest.py --allow-shrink` to accept the loss.

## Tests

    python3 -m unittest -v

## Version control

This folder is a git repository, pushed to the GitHub repo
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
- Many agy runs record no folder. A conversation's project comes from the folder
  Antigravity recorded, else the folder the agy CLI log or prompt history names, else
  Sable when its request names Sable (or tattoo) and no other project folder, else
  Unknown. Until 2026-11-08 only Sable conversations were kept; the rest were left out.
  The CLI logs get pruned, so the folders they name are kept in
  `out/antigravity_folders.json`.
- Prices are in `PRICES` at the top of `ingest.py`; update them and `PRICES_AS_OF`
  when Anthropic changes list prices.
- The model palette in `ledger/index.html` was checked with the dataviz skill's
  `validate_palette.js` against the ink background; keep its fixed order.
