/* Theme bootstrap (external so it satisfies CSP script-src 'self' — inline scripts are blocked).
   Reads the user's saved theme from localStorage and loads the Tau (default) or Meridian bundle.
   The default app.css is already linked in <head> (no flash for the common case); for Meridian
   we swap the stylesheet href before loading its JS. The app syncs localStorage to the account. */
(function () {
  var b = document.getElementById('tau-boot');
  if (!b) return;
  var mer = false;
  try { mer = localStorage.getItem('tau_ui') === 'meridian'; } catch (e) { /* private mode */ }
  // Only Tau has the Terms and Privacy pages; Meridian used to bounce them to the dashboard.
  try { if (/^\/(?:terms|privacy)$/.test(location.pathname)) mer = false; } catch (e) { /* no location */ }
  window.__TAU_UI__ = mer ? 'meridian' : 'tau';
  if (mer) {
    var link = document.getElementById('tau-css');
    if (link) link.href = b.dataset.merCss;
    window.__BUILD__ = b.dataset.merVer;
  } else {
    window.__BUILD__ = b.dataset.tauVer;
  }
  var s = document.createElement('script');
  s.src = mer ? b.dataset.merJs : b.dataset.tauJs;
  s.defer = true;
  document.body.appendChild(s);
})();
