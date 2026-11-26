// Home-screen app support, loaded only by the GitHub Pages build (build-site.sh), not the claude.ai artifact.
(() => {
  if ('serviceWorker' in navigator) {
    addEventListener('load', () => navigator.serviceWorker.register('sw.js').catch(() => {}));
  }
  // A home-screen app has no reload button, and iOS keeps it alive in the background, so reopening it
  // can show yesterday's numbers. Reload when it comes back after half an hour or more away.
  const standalone = navigator.standalone || matchMedia('(display-mode: standalone)').matches;
  if (!standalone) return;
  let hiddenAt = 0;
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) hiddenAt = Date.now();
    else if (hiddenAt && Date.now() - hiddenAt > 30 * 60 * 1000) location.reload();
  });
})();
