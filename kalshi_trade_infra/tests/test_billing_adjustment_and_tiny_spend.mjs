// Billing walk 2026-10-31, as a paying customer in every credit state, both themes. Two display faults:
// - Tau support taking credits back (a negative admin grant, an adjustment) read "Credits from Tau support −$2.50". The
//   line says "Credits adjusted by Tau support", as the server's memo and the receipt's memo do; a grant still reads
//   "Credits from Tau support".
// - A week of spend under a cent (one short chat) read "Spent, last 7 days $0.00", "$0.00 in the last 24 hours" and
//   "at $0.00 a week" beside "Last 7 days: other agent calls under $0.01" and a −$0.004 line under "Today · under
//   $0.01 used". The figures say "under $0.01" too. A week over a cent reads as before.
import assert from './assert_text.mjs';
import {test} from 'node:test';
import {loadBundle, pageText, renderPage} from './view_fuzz_harness.mjs';
import {me, replies} from './view_fuzz_fixtures.mjs';

const ago = (h) => new Date(Date.now() - h * 3600e3).toISOString();
const day = (h) => { const d = new Date(Date.now() - h * 3600e3); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };

async function billing(bundle, over) {
  const r = replies();
  r['/api/billing'] = {...r['/api/billing'], ...over};
  r['/api/billing/figures'] = r['/api/billing'];
  const {crashes, root} = await renderPage(loadBundle(bundle), '/billing', (url) => r[url.split('?')[0]], {me: me()});
  assert.deepEqual(crashes.map((e) => e.message || String(e)), []);
  const plain = (s) => s.replace(/\u2060/g, '').replace(/\s+/g, ' ');
  // A row is drawn as markup: its words are its HTML less the tags.
  return {root, text: plain(pageText(root)), rows: root.querySelectorAll('.t-ledger tbody tr').map((row) => plain(row.innerHTML.replace(/<[^>]+>/g, ' ')))};
}

const tinyWeek = {
  balance: 49.996, spent: 7.5, spent_7d: 0, spent_24h: 0, runway_days: 9000, reload_days: 8000, pace_days: 7,
  spent_7d_by: {research: 0, autopilot_research: 0, autopilot_review: 0, chat: 0, other: 0}, spent_7d_under_cent: ['other'],
  math: null, ledger_cut: false,
  ledger: [
    {kind: 'usage', amount: -0.004, memo: 'Agent usage · Claude Haiku 4.5', item: 'Agent usage', model: 'Claude Haiku 4.5', calls: 1, created_at: ago(2), first_at: ago(2), day: day(2)},
    {kind: 'admin_grant', amount: -2.5, memo: 'Credits adjusted by Tau support', created_at: ago(50), first_at: ago(50), day: day(50)},
    {kind: 'admin_grant', amount: 10, memo: 'Credits added by Tau support', created_at: ago(120), first_at: ago(120), day: day(120)},
  ],
};

for (const bundle of ['app.js', 'app.meridian.js']) {
  test(`${bundle}: an adjustment by Tau support says it adjusted credits; a grant says they came from Tau support`, async () => {
    const {rows} = await billing(bundle, tinyWeek);
    const adj = rows.find((t) => /Tau support/.test(t) && t.includes('−$2.50')), grant = rows.find((t) => /Tau support/.test(t) && t.includes('+$10.00'));
    assert.match(adj, /Credits adjusted by Tau support/);
    assert.doesNotMatch(adj, /Credits from Tau support/);
    assert.match(grant, /Credits from Tau support/);
    assert.ok(rows.some((t) => /Agent usage.*−\$0\.004/.test(t)), rows.join(' | '));  // the sub-cent line as it was
  });

  test(`${bundle}: a week of spend under a cent reads "under $0.01", never $0.00 beside "under $0.01"`, async () => {
    const {root, text} = await billing(bundle, tinyWeek);
    const figs = pageText(root.querySelector('#bfigs')).replace(/\u2060/g, '');
    assert.match(figs, /Spent, last 7 days\s*Under \$0\.01/);
    assert.match(figs, /under \$0\.01 in the last 24 hours/);
    assert.match(figs, /\$7\.50 all time/);
    assert.match(figs, /at under \$0\.01 a week/);
    assert.doesNotMatch(figs, /\$0\.00/);
    assert.match(text, /other agent calls under \$0\.01/);
  });

  test(`${bundle}: a week over a cent, and a day with no spend in it, read as the server's figures`, async () => {
    const {root} = await billing(bundle, {...tinyWeek, spent_7d: 2.1, spent_24h: 0, spent_7d_by: {research: 2.1}, spent_7d_under_cent: [],
      ledger: tinyWeek.ledger.slice(1)});
    const figs = pageText(root.querySelector('#bfigs')).replace(/\u2060/g, '');
    assert.match(figs, /Spent, last 7 days\s*\$2\.10/);
    assert.match(figs, /\$0\.00 in the last 24 hours/);
    assert.match(figs, /at \$2\.10 a week/);
  });
}
