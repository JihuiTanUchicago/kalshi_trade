// The same fact in the same words in both themes (Tau: app.js and app-*.js; Meridian: app.meridian*.js).
// New-account walk 2026-10-30: the research loop's steps were Explore/Backtest/Check/Improve in Tau and
// Explore/Backtest/Validate/Refine in Meridian; the autopilot panel said "Live trading isn’t open yet." (its
// summary, the server's) under "Live trading isn’t available on this server yet." (its live gate line); and a
// session with no picked market was "Agent’s choice" beside "Session", nothing saying it was the market.
// Untouched: the server's live gate and deploy refusals, and whether live trading is allowed at all.
import assert from './assert_text.mjs';
import {readFileSync} from 'node:fs';
import {test} from 'node:test';

const read = (f) => readFileSync(new URL('../app/' + f, import.meta.url), 'utf8');
const BUNDLES = {tau: ['static/app.js', 'static/page-research.js'], meridian: ['static/app.meridian.js', 'static/page-research.js']};

const stages = (file) => {
  const m = read(file).match(/const RSI_STAGES = (\[[^;]+\]);/);
  assert.ok(m, file);
  return new Function(`return ${m[1]};`)();
};

test('both themes name the research loop’s steps in the same plain words', () => {
  // One list for both themes, in their one Research file (page-research.js).
  const src = read('static/page-research.js');
  assert.equal(src.match(/const RSI_STAGES = /g).length, 1);
  assert.deepEqual(stages('static/page-research.js').map(([, label]) => label), ['Explore', 'Backtest', 'Check', 'Improve']);
  // Each theme's loop names them so in its own markup: Tau's station line and Meridian's list.
  assert.equal((src.match(/aria-label="[^"]*explore, backtest, check, improve/g) || []).length, 2);
  assert.doesNotMatch(src, /'Validate'|'Refine'|validate, refine/);
});

test('the autopilot panel’s live gate says “Live trading isn’t open yet.”, as its summary and Deploy do', () => {
  const line = (file) => {
    const m = read(file).match(/if \(!d\.live_enabled\) return '([^']*)';/);
    assert.ok(m, file);
    return m[1];
  };
  for (const [bundle] of Object.values(BUNDLES)) {
    assert.equal(line(bundle), 'Live trading isn’t open yet. ', bundle);
    assert.doesNotMatch(read(bundle), /available on this server yet/, bundle);
  }
  // Said once in either theme: the gate line steps aside when the summary above it already says it
  // (test_production_ui_reconciliation.mjs walks both).
  // One file both themes load (page-autopilot.js).
  assert.match(read('static/page-autopilot.js'), /some\(\(line\) => \/live trading isn’t open yet\/i\.test\(line\)\);\n {8}gates\.innerHTML = saidAbove \? '' : /);
  // The panel's summary (the server's) and the deploy refusal say it in these words; neither changes here.
  assert.match(read('web/routes/chat.py'), /" Live trading isn’t open yet\."/);
  assert.match(read('web/routes/deployments.py'), /ApiError\(409, "Live trading isn't open yet\."\)/);
});

test('a session with no picked market is named as a market in both themes, display only', () => {
  // One label, in the shared core (core.js), that each theme's marketShort draws.
  const m = read('static/core.js').match(/const NO_MARKET = '([^']*)';\n/);
  assert.ok(m);
  assert.equal(m[1], 'Any market (agent’s choice)');
  for (const [bundle] of Object.values(BUNDLES)) {
    const src = read(bundle);
    assert.match(src, /\n {4}[^\n]*\bNO_MARKET\b[^}]*\} = window\.TauCore;/, bundle);
    assert.match(src, /\n {2}const marketShort = \(k\) => \(!k \? NO_MARKET : /, bundle);
    assert.doesNotMatch(src, /\? 'Agent’s choice' :|const NO_MARKET = /, bundle);
  }
  // What the research model is sent is not this label: the "open" angle keeps its own words.
  assert.match(read('research/agent.py'), /"open": \{"label": "Agent's choice"/);
});
