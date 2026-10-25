/* Theme bootstrap (external so it satisfies CSP script-src 'self' — inline scripts are blocked).
   When the server knows the theme (the tau_ui cookie, or the signed-in account), the page shell
   already links that theme's stylesheet and bundle, so nothing is swapped or downloaded twice: this
   only records the choice. Otherwise (signed out on this device) it goes by the theme saved in
   localStorage: the Tau stylesheet is linked by default, and for Meridian it swaps the href before
   loading Meridian's bundle. The app keeps localStorage in step with the account. */
(function () {
  var b = document.getElementById('tau-boot');
  if (!b) return;
  // Only Tau has the Terms and Privacy pages; Meridian used to bounce them to the dashboard.
  var legal = false;
  try { legal = /^\/(?:terms|privacy)$/.test(location.pathname); } catch (e) { /* no location */ }
  var known = b.dataset.ui === 'meridian' || b.dataset.ui === 'tau' ? b.dataset.ui : '';
  var mer = false;
  if (known) mer = known === 'meridian';
  else {
    try { mer = localStorage.getItem('tau_ui') === 'meridian'; } catch (e) { /* private mode */ }
    if (legal) mer = false;
  }
  window.__TAU_UI__ = mer ? 'meridian' : 'tau';
  window.__BUILD__ = mer ? b.dataset.merVer : b.dataset.tauVer;
  if (known) {
    // A forced Tau legal page is not a choice, so it never overwrites a saved Meridian.
    if (!legal) { try { localStorage.setItem('tau_ui', known); } catch (e) { /* private mode */ } }
    return;  // its bundle is already in the page, right after this script
  }
  if (mer) {
    var link = document.getElementById('tau-css');
    if (link) link.href = b.dataset.merCss;
  }
  var s = document.createElement('script');
  s.src = mer ? b.dataset.merJs : b.dataset.tauJs;
  s.defer = true;
  document.body.appendChild(s);
})();
