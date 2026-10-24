# Sable AI usage

**Sable AI Ledger**: https://claude.ai/artifact/9rkccTsV3vvha7mtggGaTh
Source `ledger/index.html`. GSAP 3.15 (SplitText) and ECharts 6.1 from jsDelivr,
Marcellus and Archivo from Google Fonts, Sable's v2 palette. Loads `data/*.json`
published beside the page. The earlier Dashboard-type page was retired on
2026-10-21; its source is kept in `retired/dashboard/`. For raw rows, read `out/*.json`.

`ingest.py` reads the AI logs on this Mac and writes one JSON file per dataset to
`out/`. Standard library only, Python 3.8+.

| Source | Path | What it gives |
|---|---|---|
| Claude Code transcripts | `~/.claude/projects/-Users-pritesh-code-tattoo-app/` | Tokens, cache, thinking, model, branch per reply |
| Codex sessions | `~/.codex/sessions/` (filtered to this repo) | Tokens per call, model, role, branch |
| git + GitHub (`gh`) | the repo | PRs, issues, CI runs, diff sizes, rework |

## Refresh

Ask Claude Code: "refresh the Sable AI ledger". It runs `python3 ingest.py`, copies
`ledger/index.html` and `out/{daily,tasks,prices,waveform}.json` into its scratchpad
(published files must live there or in the working directory) and republishes to the
ledger URL with the JSON files under `data/`.

## Tests

    python3 -m unittest -v

## Version control

This folder is a local git repository (no remote). Commit after each refresh or
page change. `out/` is committed on purpose: Claude Code deletes its transcripts
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
- Codex has no list prices here, so it is compared on tokens, not dollars.
- agy (Antigravity) logs are not read yet.
- Prices are in `PRICES` at the top of `ingest.py`; update them and `PRICES_AS_OF`
  when Anthropic changes list prices.
- The model palette in `ledger/index.html` was checked with the dataviz skill's
  `validate_palette.js` against the ink background; keep its fixed order.
