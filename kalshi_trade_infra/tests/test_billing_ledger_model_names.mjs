// Billing's ledger names a model by what a customer calls it, never by its internal id. The server sends each usage
// line's `item` and `model` ("Claude Opus 4.6", app.web.routes.billing._usage_item), but a line from before it did has
// only the stored memo, "Agent usage · " then the invokable id, and the page showed what followed the prefix as it was:
// the fixtures read "claude-opus-4-6" under "Agent usage". Each bundle's Billing page now says the model's family and
// version, or "AI model" for one it doesn't know, at display time; the stored memo is left as it was.
import assert from './assert_text.mjs';
import {test} from 'node:test';
import {loadBundle, pageText, renderPage} from './view_fuzz_harness.mjs';
import {me, replies} from './view_fuzz_fixtures.mjs';

const at = '2026-10-25T17:00:00Z';
const usage = (memo, extra = {}) => ({kind: 'usage', amount: -0.21, memo, created_at: at, ...extra});
// Each memo a ledger row can hold, without the server's item and model, and the name its line shows.
const CASES = [
  ['Agent usage · claude-opus-4-6', 'Claude Opus 4.6'],
  ['Agent usage · us.anthropic.claude-opus-4-6-v1', 'Claude Opus 4.6'],
  ['Agent usage · us.anthropic.claude-haiku-4-5-20251001-v1:0', 'Claude Haiku 4.5'],
  ['Agent usage · us.anthropic.claude-3-5-sonnet-20240620-v1:0', 'Claude Sonnet'],
  ['Agent usage · sonnet', 'Claude Sonnet'],
  ['Agent usage · us.deepseek.r1-v1:0', 'AI model'],
  ['Agent usage · fixture', 'AI model'],
  ['Research run · us.anthropic.claude-opus-4-6-v1', 'Research run · Claude Opus 4.6'],
];
// What an internal model id looks like: a provider prefix, a "claude-" slug, or a version suffix.
const RAW_ID = /claude-|anthropic\.|deepseek\.|\bus\.|-v\d(?::\d)?\b|20240620|20251001/;

async function ledgerRows(bundle, ledger) {
  const r = replies();
  r['/api/billing'] = {...r['/api/billing'], ledger};
  const {crashes, root} = await renderPage(loadBundle(bundle), '/billing', (url) => r[url.split('?')[0]], {me: me()});
  assert.deepEqual(crashes.map((e) => e.message || String(e)), []);
  return {rows: root.querySelectorAll('.t-ledger tbody tr').map((row) => row.innerHTML), text: pageText(root)};
}

for (const bundle of ['app.js', 'app.meridian.js']) {
  test(`${bundle}: a usage line from a memo alone names the model, never its id`, async () => {
    const {rows, text} = await ledgerRows(bundle, CASES.map(([memo]) => usage(memo)));
    assert.equal(rows.length, CASES.length);
    CASES.forEach(([memo, name], i) => {
      assert.ok(rows[i].includes(`<div class="sub-fig">${name}</div>`), `${memo} → ${rows[i]}`);
      assert.doesNotMatch(rows[i], RAW_ID, memo);
    });
    assert.doesNotMatch(text, RAW_ID);
  });

  test(`${bundle}: a line with the server's item and model shows them as sent`, async () => {
    const {rows} = await ledgerRows(bundle, [usage('Autopilot research · Claude Opus 4.6', {item: 'Autopilot research', model: 'Claude Opus 4.6'}),
      usage('Chat', {item: 'Chat', model: ''})]);
    assert.match(rows[0], /Autopilot research<div class="sub-fig">Claude Opus 4\.6<\/div>/);
    assert.match(rows[1], /Chat<\/td>/);  // nothing under it: no model, and the memo isn't repeated
    assert.doesNotMatch(rows[1], /sub-fig/);
  });
}
