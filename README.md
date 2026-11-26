# Sable AI usage

**Sable AI Ledger** (GitHub Pages): https://pritesh1980.github.io/sable-ai-ledger/
Rebuilt by `.github/workflows/pages.yml` (which runs `build-site.sh`) on every push that
touches `ledger/`, `out/`, `pwa/` or `build-site.sh`.
The repo is public (since 2026-11-04), so everything in it, data included, is readable
by anyone. The old claude.ai artifact (https://claude.ai/artifact/9rkccTsV3vvha7mtggGaTh)
is no longer updated.

Source `ledger/index.html`. GSAP 3.15 and ECharts 6.1 from jsDelivr,
Marcellus and Archivo from Google Fonts, Sable's v2 palette. Loads `data/*.json`
published beside the page. The earlier Dashboard-type page was retired on
2026-10-21; its source is kept in `retired/dashboard/`. For raw rows, read `out/*.json`.

## On the iPhone

Open the Pages link in Safari, tap Share, then **Add to Home Screen**. It opens full screen
as "AI Ledger" with the waveform icon. The files that make this work live in `pwa/`, and only
the Pages build adds them (the page source stays a fragment):

- `manifest.webmanifest` and the icons. `icon.svg` is the source; re-render the PNGs with
  `rsvg-convert -w 512 -h 512 pwa/icon.svg -o pwa/icon-512.png` (and 192, and 180 for
  `apple-touch-icon.png`).
- `sw.js`, a service worker that keeps the last page and data, so the app still opens with no
  signal. It always tries the network first, so with signal you get the latest refresh.
- `app.js` registers it, and reloads the app when it comes back after 30+ minutes in the
  background (a home-screen app has no reload button, and iOS keeps it alive for days).

To preview the built site locally, run `./build-site.sh` and serve `site/` (it is gitignored).

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
| Antigravity (agy CLI and IDE) | `~/.gemini/antigravity-cli/` and `~/.gemini/antigravity/`, one SQLite file per conversation in `conversations/`, plus each conversation's `brain/<id>/.system_generated/logs/transcript.jsonl` | Tokens per generation, model, effort level and two-model mode (from the SQLite); the branches and PRs its commands named (from the transcript) |
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
holds the time of the last refresh, which the page shows as "Updated" beside
"Latest activity" (the latest call in the data). `out/insights.json` is copied too.

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

## Cost per shipped task

Straight after the waveform, "Cost per shipped task" shows the average Claude cost of the
shipped tasks each model led (`primary_model` in `out/tasks.json`), with a tick for the median.
Buttons switch between all tasks, small and medium (S, M) and large (L, XL), since bigger jobs
tend to go to some models more than others. Models that led fewer than 3 tasks are named in the
note instead of drawn. Each bar stacks the task's Claude cost (list prices) and the estimated cost of the
Codex and Antigravity work on it (`codex_cost_usd`, `gemini_cost_usd` in `out/tasks.json`), so GPT- and
Gemini-led tasks appear too.

## Estimated GPT and Gemini costs

OpenAI and Google models have no prices from a source this ledger trusts, so `EST_PRICES` in `ingest.py`
holds estimates gathered from the web on 2026-11-24 (per million tokens: input, output, cached input).
Codex and Antigravity rows in `out/daily.json` gain `est_cost_usd`; `out/prices.json` lists the rates
with `estimated: true`. Only "Cost per shipped task" shows them; every other cost on the page is Claude.

- GPT-6.2 Sol and GPT-6.1 Sol ($2 / $10 / $0.10) and GPT-6.2 Astra ($8 / $40 / $0.40): OpenAI's GPT-6.2
  launch post. GPT-6 Astra ($10 / $50 / $1) is 25% above 6.2 Astra, as that post says.
- GPT-6 Sol ($2 / $10 / $0.20): price trackers, citing OpenAI's pricing page in October 2026.
- GPT-5.6 Sol ($5 / $30 / $0.50), Terra ($2 / $12 / $0.20 after the July cut), Luna ($0.20 / $1.20 / $0.02),
  GPT-5.5 ($5 / $30 / $0.50): OpenAI's GPT-5.6 post and trackers. Sol ran a promotional $4 / $20 for a
  while from late August; the list rate is used.
- Gemini 4 Argon ($2 / $10 / $0.10): Google's Gemini API pricing page, until 30 November 2026, when Google
  doubles it. Hydrogen ($1.50 / $7.50 / $0.075) and Neon ($3 / $15 / $0.15): trackers only.
- Gemini 3.1 Pro ($2 / $12 / $0.20) and every Flash model at Gemini 3.6 Flash's list rate ($1.50 / $7.50 /
  $0.15): Google Cloud's Vertex AI price list.
- Codex calls that don't name a model (`unknown`, and the `codex-auto-review` approval checker, which
  OpenAI doesn't charge ChatGPT sign-ins for) are priced as that day's busiest named Codex model.

One rate per model, though some changed over time, and these are API prices: Codex and Antigravity run
on subscriptions here, as Claude Code does. Update the table when prices change.

## Where Gemini is used

After "The models", a section on Gemini models only (Antigravity can also run Claude, which
stays out of it): what share of all tokens they took, tokens per week by job (planning and
carrying out in Antigravity's two-model mode, building alone, reviewing), which Gemini model,
which kind of Sable task, and the Sable tasks it worked on most, named by their plain feature
title. Antigravity logs its planner as "Orchestrator (Argon)", which the ledger counts as
`gemini-4-argon`. Daily rows for Antigravity carry `mode` (plan, execute, single) and `effort`
(Low, Medium, High, or null).

An Antigravity call joins a task in one of two ways. Its transcript's commands (`git checkout
-b`, `git worktree add -b`, `gh pr create --head`, `git push origin`, `gh pr <verb> N`) say
which branch or PR it was on, and each call takes the latest one before it. An `agy --print`
review run with none of those takes the task of the Claude Code reply that launched it, up to
10 minutes earlier. Tasks gain `gemini_tokens` and `gemini_review_tokens` (Gemini models
only), and a Gemini model can be a task's lead model.

## Sable timeline

The page's "Who worked when" section is a git graph with the AIs as branches. Claude Code's lane
sits above main, and Codex and Antigravity each have a lane below it. Every task is a line
that forks off main into the lane of the AI working on it, crosses to another lane when a
different AI takes over (a review, say), and joins main again with a dot where it merged
(`merges` in `out/waveform.json`, from main's first-parent history; a hollow dot when the PR
merged into another branch). Lines that are live at the same time get their own track in a lane.
Capsules on a line are stretches of work, split wherever a session sat idle for over 30
minutes; hollow ones are reviewing. Work not tied to a task sits faintly at the top of its lane.
Clicking a line opens the relay for its task below; the relay names a task by when it started
and which AIs worked on it, never by its PR. Sable calls only, last 30 days. The graph opens on
the latest whole days, counting back until they hold about ten tasks (six on a phone), so a busy
spell shows a day or two and a quiet one a week or more; buttons switch to the last 7 days, the
last 30 days, or the day the AIs overlapped most. Each period is drawn on its own, so its lanes
only take as many tracks as that period needs. Each
waveform row ends with project and session indices (into `projects` and `sessions`).

## Daily refresh

At 05:00 launchd runs `refresh.sh` on this Mac, or runs it on wake if the Mac was
asleep. It pulls from GitHub first (so a page or script change pushed from elsewhere
can't block its push), then runs the tests and the ingest, commits `out/` (every run,
since `meta.json` stamps each one; the commit says "no new usage" when only that
changed), and pushes to https://github.com/Pritesh1980/sable-ai-ledger. That push runs
the Pages workflow. It waits up to 5 minutes for the network (a run that starts on wake can beat it), and
if the ingest's shrink guard stops it, tries once more 3 minutes later, since a conversation
being written can read short. It shows a macOS notification if anything fails.

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
  when Anthropic changes list prices. A Claude model missing from it costs nothing in the
  ledger (Fable 5.2 and Haiku 5.5 did until 2026-11-20), so add new models when they appear.
- The model palette in `ledger/index.html` was checked with the dataviz skill's
  `validate_palette.js` against the ink background; keep its fixed order.
