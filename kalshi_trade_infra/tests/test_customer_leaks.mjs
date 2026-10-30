// What a customer reads in either theme carries none of the internal detail tests/test_devlog.py keeps off the Dev
// Logs: setting names, code and file names, cloud vendors and accounts, credential stores, model and experiment ids,
// raw series keys, raw upstream errors, and what Tau pays for a model or adds on top. The guard reads every string
// literal in the static scripts as a reader would see it (markup out), and the pages render a market the catalog no
// longer lists, and a research-loop tag the page doesn't know, in words.
import assert from './assert_text.mjs';
import {readdirSync, readFileSync} from 'node:fs';
import {test} from 'node:test';
import {literals, prose} from './js_literals.mjs';
import {loadBundle, pageText, renderPage} from './view_fuzz_harness.mjs';
import {me, replies} from './view_fuzz_fixtures.mjs';

const DIR = new URL('../app/static/', import.meta.url);
// The bundles' separator (SEP in app.js and app.meridian.js; test_separator_line_start.mjs): a no-break space, "·", a space.
const SEP = '\u00a0\u00b7 ';
// The same kinds as the Dev Logs guard (INTERNAL in tests/test_devlog.py), for a page's own words. "margin" alone
// stays: it is a Bitcoin perps account's margin, which the perps pages and the safety emails rightly name.
const INTERNAL = {
  'a setting or env-var name': /\b[A-Z]{2,}_[A-Z_]{2,}/,
  'a cloud vendor or service': /\bAWS\b|Bedrock|\bRDS\b|\bEC2\b|\bS3\b|\bIAM\b|\bSSM\b|\bSES\b|\bOIDC\b|CloudFront|CloudWatch|\bboto(?:3|core)\b|\b(?:us|eu|ap)-(?:east|west|north|south|central)-\d/,
  'a cloud account': /\b(?:AWS|Amazon|Bedrock|cloud|hosting|GCP|Azure|Anthropic|provider)(?:['’]s)?\W+(?:\w+\W+)?accounts?\b|\bour (?:\w+ )?account\b/,
  'a credential store or secret': /Secrets? Manager|Parameter Store|Actions Secrets|\bvault\b|\.env\b|tau-deploy|\/etc\/shadow/,
  'a file, module, table or code span': /\b\w+\.(?:py|mjs|sql|sh|ya?ml)\b|\b[a-z0-9]+_[a-z0-9_]+\b|`|\b(?:app|tests?|results)\/|\/api\//,
  'a function, class or raw upstream error': /\b[a-z]+[A-Z]\w*|\w\(\)|\b\w*(?:Error|Exception)\b|AccessDenied|Throttling|\berrno\b|Traceback|Lost connection/,
  'a model, experiment or row id': /\bclaude-|\banthropic\.|\bus\.[a-z]+\.|-v\d+:\d|\[1m\]|\b(?:run|experiment|exp|user|deployment|strategy) #?\d+\b/,
  'a raw series key': /\bKX[A-Z0-9]{2,}/,
  'internal infrastructure': /\bMySQL\b|information_schema|\b(?:the|on|collector) box\b|\bprod\b|\bDDL\b/,
  'what Tau pays for a model or adds on top': /list price|mark-?up|\d+ ?% margin|usage margin|raw model cost|\bour cost|what (?:Tau|we) pays?|\$[\d.]+ ?\/ ?M\b|per million tokens/i,
};
// Scripts no customer reads, or words a customer is owed. Each names why.
const ALLOWED_FILES = {
  'page-admin.js': 'the operator’s Admin page, and the System map, which shows the codebase on purpose (file and table names), in both themes',
  'app-legal.js': 'the privacy policy must name who processes a customer’s data (Anthropic via Amazon Bedrock, Amazon Web Services)',
};
const ALLOWED_TEXT = [
  ['boot.js', /^A non-Error value \($/],  // the error report boot.js sends to the operator’s log; never on screen
];

const scripts = readdirSync(DIR).filter((f) => f.endsWith('.js') && !(f in ALLOWED_FILES)).sort();
// A literal a reader sees as words: two of them with a space between, once its markup is out.
const sentences = (file) => literals(readFileSync(new URL(file, DIR), 'utf8'))
  .map(({line, text}) => ({line, text: prose(text).replace(/\s+/g, ' ').trim()}))
  .filter(({text}) => /[A-Za-z]{2,} [A-Za-z]{2,}/.test(text))
  .filter(({text}) => !ALLOWED_TEXT.some(([f, rx]) => f === file && rx.test(text)));

test('the guard reads both themes’ pages, sentence by sentence', () => {
  for (const f of ['app.js', 'app.meridian.js', 'page-research.js', 'app.meridian-strategies.js', 'page-autopilot.js', 'session-chat.js']) assert.ok(scripts.includes(f), f);
  const research = sentences('page-research.js').map((s) => s.text);
  assert.ok(research.some((t) => t.includes('Watch the agent reason in real time')), 'a sentence inside markup');
  assert.ok(sentences('app.js').length > 500);
  // A sentence split by a ${...} part still reads whole, and markup inside a template is out.
  assert.deepEqual(literals('const a = `<p class="hint" style="margin-top:8px">Read ${when(x)} ago.</p>`;').map((l) => prose(l.text).trim()), ['Read … ago.']);
  // A regex literal is code, not words; a string after one is still found.
  assert.deepEqual(literals("const r = /it's/g, s = 'said';").map((l) => l.text), ['said']);
});

// Each kind still catches the kind of line the Dev Logs walk found.
test('each kind catches what it is for', () => {
  const caught = {
    'a setting or env-var name': 'set TAU_KALSHI_PERPS_ENABLED to open it',
    'a cloud vendor or service': 'the model on Bedrock is busy',
    'a cloud account': 'until our Bedrock account opens it',
    'a credential store or secret': 'the key sits in Secrets Manager',
    'a file, module, table or code span': 'see app_users.autopilot_plan',
    'a function, class or raw upstream error': 'ThrottlingException from the provider',
    'a model, experiment or row id': 'experiment 213 ran on us.anthropic.claude-opus-4-6-v1',
    'a raw series key': 'KXNBAGAME has no data',
    'internal infrastructure': 'the MySQL server went away',
    'what Tau pays for a model or adds on top': 'charged at list price × 2',
  };
  for (const [kind, line] of Object.entries(caught)) assert.match(line, INTERNAL[kind], kind);
  for (const words of ['Kalshi sets margin and leverage limits.', 'a position near liquidation, or heavy margin use', 'your Kalshi account']) {
    assert.deepEqual(Object.keys(INTERNAL).filter((k) => INTERNAL[k].test(words)), [], words);
  }
});

test('no page’s own words carry internal detail', () => {
  const hits = [];
  for (const f of scripts) for (const {line, text} of sentences(f)) {
    for (const [kind, rx] of Object.entries(INTERNAL)) { const m = rx.exec(text); if (m) hits.push(`${f}:${line} ${kind}: “${m[0]}” in ${text.slice(0, 120)}`); }
  }
  assert.deepEqual(hits, []);
});

// A market the catalog no longer lists (a retired key) read as its raw key wherever a page named a market by
// marketShort or marketLabel: the session list, the session's header, the strategy list and the strategy page.
// The research loop's board showed an unknown drop tag, data request kind or state as its raw code.
const RETIRED = 'btc_hourly_old';
for (const bundle of ['app.js', 'app.meridian.js']) {
  test(`${bundle}: a market the catalog no longer lists reads as an unlisted market, never its key`, async () => {
    const r = replies();
    r['/api/runs'] = {...r['/api/runs'], runs: r['/api/runs'].runs.map((x) => ({...x, market: RETIRED}))};
    r['/api/runs/5'] = {...r['/api/runs/5'], run: {...r['/api/runs/5'].run, market: RETIRED}};
    r['/api/strategies'] = {...r['/api/strategies'], strategies: r['/api/strategies'].strategies.map((s) => ({...s, market: RETIRED}))};
    r['/api/strategies/42'] = {...r['/api/strategies/42'], market: RETIRED};
    for (const path of ['/research', '/research/5', '/strategies', '/strategies/42']) {
      const {crashes, root} = await renderPage(loadBundle(bundle), path, (url) => r[url.split('?')[0]], {me: me()});
      assert.deepEqual(crashes.map((e) => e.message || String(e)), [], path);
      const text = pageText(root);
      assert.doesNotMatch(text, new RegExp(RETIRED), path);
      if (path !== '/strategies/42') assert.match(text, /Unlisted market/, path);
    }
  });

  test(`${bundle}: the research loop names an unknown drop reason or data request in words`, async () => {
    const r = replies(), b = r['/api/research/scoreboard'];
    r['/api/research/scoreboard'] = {...b, fix_list: [{...b.fix_list[0], tag: 'new_internal_tag'}],
      data_requests: [{...b.data_requests[0], kind: 'depth_l2', status: 'queued_v2'}]};
    const {crashes, root} = await renderPage(loadBundle(bundle), '/research', (url) => r[url.split('?')[0]], {me: me()});
    assert.deepEqual(crashes.map((e) => e.message || String(e)), []);
    const html = root.querySelectorAll('.loop-list').map((ul) => ul.innerHTML).join(' ');
    assert.doesNotMatch(html, /new_internal_tag|depth_l2|queued_v2/);
    assert.match(html, /<b>other<\/b> × 3/);
    assert.ok(html.includes(`<b>more data${SEP}book depth</b>${SEP}requested`), html);
  });
}
