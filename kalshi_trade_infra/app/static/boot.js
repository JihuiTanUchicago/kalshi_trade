/* Theme bootstrap (external so it satisfies CSP script-src 'self' — inline scripts are blocked).
   When the server knows the theme (the tau_ui cookie, or the signed-in account), the page shell
   already links that theme's stylesheet and bundle, so nothing is swapped or downloaded twice: this
   only records the choice. Otherwise (signed out on this device) it goes by the theme saved in
   localStorage: the Tau stylesheet is linked by default, and for Meridian it swaps the href before
   loading Meridian's bundle. The app keeps localStorage in step with the account. It also hands the
   app the account the signed-in shell carries (window.__TAU_ME__), and the page's first reads when
   the shell carries those too (window.__TAU_FIRST__). It keeps the browser's UTC offset in the tau_tz
   cookie, so a later shell can name Billing's first read too. */
(function () {
  // A signed-in shell carries the account (/api/me's reply) in a JSON data block; the app takes it
  // from here once, at its first render, instead of starting with a round trip to read it.
  try {
    var me = document.getElementById('tau-me');
    if (me) { window.__TAU_ME__ = JSON.parse(me.textContent); me.remove(); }
  } catch (e) { /* unreadable: the app reads /api/me itself */ }
  // It may carry the page's first reads too ([{url, body}], app/web/shell_reads.py): api() takes each once.
  try {
    var first = document.getElementById('tau-first');
    if (first) { window.__TAU_FIRST__ = JSON.parse(first.textContent); first.remove(); }
  } catch (e) { /* unreadable: the page asks for it itself */ }
  // Billing asks for /api/billing?tz=<getTimezoneOffset()> (its statement's days are yours). Only the
  // browser knows that offset: kept in a cookie, a later page shell can carry Billing's read (shell_reads.py).
  try {
    document.cookie = 'tau_tz=' + new Date().getTimezoneOffset() + '; Path=/; Max-Age=34560000; SameSite=Lax' + (location.protocol === 'https:' ? '; Secure' : '');
  } catch (e) { /* cookies blocked: Billing asks as before */ }
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

/* Page error reports. An uncaught error or unhandled promise rejection, or (through
   window.__tauReport, from the app bundle) an API call or page bug that the page shows as an error,
   is sent to POST /api/client-errors, so the operator sees broken pages on /admin instead of finding
   them by walking every page. At most MAX per page load, each distinct report once. A report holds
   only what locates the bug: its kind, the message (emails, URL queries, long tokens and long numbers
   taken out, cut to 300 characters), the script's file name and line, the page path without its
   query (ids as :id), the theme and the build. Never form values, request bodies, query strings or
   stacks. A fire-and-forget fetch with keepalive (so a report sent as the page unloads still goes)
   and the X-Recursive header every write carries: sendBeacon can't send that header, and this route
   gets no exception to the CSRF rule. It can't throw, and its own failure is never reported. */
(function () {
  var MAX = 5, MSG = 300, sent = 0, seen = {}, busy = false;
  var FRAME = /([A-Za-z0-9_.-]+\.js)(?:\?[^:\s)]*)?:(\d+):(\d+)/;
  function scrub(s) {
    return String(s).replace(/[\x00-\x1f\x7f]+/g, ' ')
      .replace(/\?[^\s'"<>()]*=[^\s'"<>()]*/g, '')
      .replace(/[\w.+-]+@[\w-]+(?:\.[\w-]+)+/g, '<email>')
      .replace(/[A-Za-z0-9_\-+=]{24,}/g, '<redacted>')
      .replace(/\d{9,}/g, '<n>')
      .replace(/\s+/g, ' ').replace(/^ | $/g, '').slice(0, MSG);
  }
  function base(f) {
    f = String(f || '').split(/[?#]/)[0];
    return f.slice(f.lastIndexOf('/') + 1).slice(0, 80);
  }
  // Only the words of an Error or a string: any other rejected value (an object) could hold anything.
  function words(err) {
    if (typeof err === 'string') return err;
    if (err && typeof err.message === 'string' && err.message) {
      return (typeof err.name === 'string' && err.name && err.name !== 'Error' ? err.name + ': ' : '') + err.message;
    }
    return 'A non-Error value (' + (err === null ? 'null' : typeof err) + ')';
  }
  function report(kind, err, src, line, col) {
    if (busy || sent >= MAX) return;
    busy = true;
    try {
      var stack = err && typeof err.stack === 'string' ? err.stack : '';
      var m = !src && stack ? stack.match(FRAME) : null;
      var path = '';
      try { path = String(location.pathname || '').replace(/\/\d+(?=\/|$)/g, '/:id').slice(0, 120); } catch (e) { /* no location */ }
      var body = {
        kind: kind, message: scrub(words(err)) || '(no message)', src: base(src || (m && m[1])),
        line: +line || (m ? +m[2] : 0), col: +col || (m ? +m[3] : 0), path: path,
        theme: window.__TAU_UI__ === 'meridian' ? 'meridian' : 'tau', ver: String(window.__BUILD__ || '').slice(0, 16)
      };
      var key = [kind, body.message, body.src, body.line, body.col, path].join('|');
      if (seen[key]) return;
      seen[key] = 1;
      sent++;
      if (typeof fetch !== 'function') return;
      var p = fetch('/api/client-errors', {
        method: 'POST', keepalive: true, credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', 'X-Recursive': '1' }, body: JSON.stringify(body)
      });
      if (p && typeof p.catch === 'function') p.catch(function () { /* nowhere to report it */ });
    } catch (e) { /* a report must never break the page */ } finally { busy = false; }
  }
  // An error from another origin's script (Stripe) or a browser extension says nothing usable.
  function ours(file) {
    if (!file) return true;
    try { return String(file).indexOf(location.origin + '/') === 0; } catch (e) { return false; }
  }
  window.__tauReport = function (kind, err) { report(kind === 'api' ? 'api' : 'view', err); };
  if (typeof window.addEventListener !== 'function') return;
  window.addEventListener('error', function (ev) {
    try {
      if (!ev || (!ev.error && (!ev.message || /^Script error\.?$/.test(ev.message))) || !ours(ev.filename)) return;
      report('error', ev.error || ev.message, ev.filename, ev.lineno, ev.colno);
    } catch (e) { /* never */ }
  });
  window.addEventListener('unhandledrejection', function (ev) {
    try { report('rejection', ev ? ev.reason : undefined); } catch (e) { /* never */ }
  });
})();
