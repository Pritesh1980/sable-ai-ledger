#!/bin/sh
# Builds the GitHub Pages site in ./site. Run by .github/workflows/pages.yml; run it locally to preview.
# ledger/index.html is a fragment: claude.ai adds the document skeleton when it publishes the artifact.
# This adds one too, plus what makes the page installable on a phone's home screen (pwa/), so the
# fragment stays as it is.
set -eu
cd "$(dirname "$0")"
rm -rf site
mkdir -p site/data
{
  cat <<'HEAD'
<!doctype html>
<html lang="en">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<link rel="manifest" href="manifest.webmanifest">
<link rel="icon" href="icon.svg" type="image/svg+xml">
<link rel="apple-touch-icon" href="apple-touch-icon.png">
<meta name="theme-color" content="#131110">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="AI Ledger">
<script src="app.js" defer></script>
HEAD
  cat ledger/index.html
} > site/index.html
cp out/daily.json out/tasks.json out/prices.json out/waveform.json out/meta.json out/insights.json site/data/
cp pwa/manifest.webmanifest pwa/app.js pwa/sw.js pwa/icon.svg pwa/apple-touch-icon.png pwa/icon-192.png pwa/icon-512.png site/
touch site/.nojekyll
