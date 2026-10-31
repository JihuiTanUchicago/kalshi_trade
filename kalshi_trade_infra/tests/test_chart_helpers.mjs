// The shared core's chart helpers (core.js), run on their own: the points a chart can draw (finitePts), a long
// series cut for drawing (thinCurve), a chart's figures in words (curveWords), a price trace's box (traceScale), and
// the zone in force at a time (tzName(at)). Both themes draw every equity curve, sparkline, drawdown, price history
// and price trace through them (chart_trust_frontend_cases.mjs walks the pages).
import assert from 'node:assert/strict';
import {test} from 'node:test';
import vm from 'node:vm';
import {coreSource} from './bundle_source.mjs';

const core = () => {
  const context = vm.createContext({window: {}});
  vm.runInContext(coreSource(), context);
  return context.window.TauCore;
};

test('finitePts leaves out a point with a null, NaN, Infinity or non-number time or value, and keeps the rest in order', () => {
  const {finitePts} = core();
  const kept = finitePts([[1, 0], [2, null], [null, 3], [3, NaN], [4, Infinity], ['x', 1], [5, '2.5'], null, [6]]);
  assert.deepEqual(JSON.parse(JSON.stringify(kept)), [[1, 0], [5, '2.5']]);
  assert.deepEqual(JSON.parse(JSON.stringify(finitePts(null))), []);
  assert.deepEqual(JSON.parse(JSON.stringify(finitePts('nope'))), []);
});

test('thinCurve keeps a short series as given, and cuts a long one keeping its ends and every run’s low and high in order', () => {
  const {thinCurve} = core();
  const short = [[1, 1], [2, 2]];
  assert.equal(thinCurve(short, 10), short);
  const long = Array.from({length: 10000}, (_, i) => [i, i === 1234 ? -500 : i === 8765 ? 700 : Math.sin(i / 30)]);
  long[9999] = [9999, 3.21];
  const cut = thinCurve(long, 1400);
  assert.ok(cut.length <= 1400 && cut.length > 700, String(cut.length));
  assert.deepEqual(cut[0], long[0]); assert.deepEqual(cut[cut.length - 1], [9999, 3.21]);
  assert.ok(cut.some((p) => p[1] === -500) && cut.some((p) => p[1] === 700), 'the deepest dip and the highest peak stay');
  for (let i = 1; i < cut.length; i++) assert.ok(cut[i][0] > cut[i - 1][0], 'in time order, no point twice');
  // Every point kept is a real point of the series.
  assert.ok(cut.every((p) => long[p[0]] === p));
});

test('curveWords says the span, the start and end, and the low and high with when each came; a flat series says so', () => {
  const {curveWords, usd} = core();
  const day = (t) => ['Oct 1', 'Oct 2', 'Oct 3', 'Oct 4'][t];
  assert.equal(curveWords([[0, 0], [1, -3.1], [2, 15], [3, 12.4]], (v) => usd(v, true), day),
    'from Oct 1 to Oct 4: starts at $0.00, ends at +$12.40; low −$3.10 (Oct 2), high +$15.00 (Oct 3)');
  assert.equal(curveWords([[0, 2], [0, 2]], (v) => usd(v, true), day), 'on Oct 1: starts at +$2.00, ends at +$2.00; flat at +$2.00');
  assert.equal(curveWords([[0, 1], [1, null], [2, 3]], String, day), 'from Oct 1 to Oct 3: starts at 1, ends at 3; low 1 (Oct 1), high 3 (Oct 3)');
  assert.equal(curveWords([], String, day), '');
  assert.doesNotMatch(curveWords([[0, -1], [1, 1]], (v) => usd(v, true), day), /⁠/, 'no word joiners in a name');
});

test('traceScale gives a price trace a box at least 10¢ tall, centred on it and inside 0–100¢; a wide trace keeps its own', () => {
  const {traceScale} = core();
  const near = (a, b) => Math.abs(a - b) < 1e-9;
  let s = traceScale([0.47, 0.48]); assert.ok(near(s.lo, 0.425) && near(s.hi, 0.525), JSON.stringify(s));
  s = traceScale([0.5, 0.5]); assert.ok(near(s.hi - s.lo, 0.1));
  s = traceScale([0.01, 0.02]); assert.ok(near(s.lo, 0) && near(s.hi, 0.1), 'kept above 0¢');
  s = traceScale([0.99, 0.985]); assert.ok(near(s.hi, 1) && near(s.lo, 0.9), 'kept under 100¢');
  s = traceScale([0.2, 0.6]); assert.ok(near(s.lo, 0.2) && near(s.hi, 0.6));
});

test('tzName(at) names the zone in force at that time, across the November clock change; with no time, now', () => {
  const was = process.env.TZ;
  process.env.TZ = 'America/New_York';
  try {
    const {tzName} = core();
    assert.equal(tzName(Date.UTC(2026, 9, 31, 20)), 'EDT');
    assert.equal(tzName(Date.UTC(2026, 10, 2, 11)), 'EST');
    assert.ok(['EDT', 'EST'].includes(tzName()));
  } finally {
    if (was === undefined) delete process.env.TZ; else process.env.TZ = was;
  }
});
