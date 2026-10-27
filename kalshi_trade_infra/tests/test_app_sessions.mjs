import assert from './assert_text.mjs';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import vm from 'node:vm';

const context = vm.createContext({URLSearchParams});
vm.runInContext(readFileSync(new URL('../app/static/session-data.js', import.meta.url), 'utf8'), context);
const sessions = context.agentSessions;
const run = (id, status = 'succeeded') => ({
  id, status, prompt: 'Idea ' + id, market: 'btc15m', created_at: '2026-10-14T01:00:00Z',
});
const strategy = (id, run_id, status = 'passed', pnl = 12) => ({
  id, run_id, parent_id: null, status, title: 'Candidate ' + id, market: 'btc15m',
  created_at: '2026-10-14T00:00:00Z', out_of_sample: { pnl },
});

test('research grouping fetches the new API pages and deduplicates overlapping rows', async () => {
  const requests = [];
  const result = await context.loadStrategyPages(async path => {
    requests.push(path);
    const page = Number(new URL(path, 'http://localhost').searchParams.get('page'));
    return {pages: 3, strategies: page === 0 ? [strategy(10, 1)] : page === 1 ? [strategy(10, 1), strategy(11, 1, 'failed')] : [strategy(12, 1, 'rejected')]};
  }, {status: '', q: 'BTC & ETH'});
  assert.equal(requests.length, 3);
  assert.equal(new URL(requests[2], 'http://localhost').searchParams.get('q'), 'BTC & ETH');
  assert.deepEqual(Array.from(result.strategies, s => s.id), [10, 11, 12]);
});

test('page reads stop after leaving the view and do not hide API errors', async () => {
  let current = true, calls = 0;
  const result = await context.loadStrategyPages(async () => { calls++; current = false; return {pages: 4, strategies: [strategy(10, 1)]}; }, {}, () => current);
  assert.equal(calls, 1);
  assert.equal(result.strategies.length, 0);
  await assert.rejects(context.loadStrategyPages(async () => { throw new Error('Unauthorized'); }), /Unauthorized/);
});

test('one session contains its passed and failed candidates', () => {
  const [s] = sessions([run(1)], [strategy(10, 1), strategy(11, 1, 'failed', -4)], []);
  assert.equal(s.title, 'Idea 1');
  assert.equal(s.candidates.length, 2);
  assert.equal(s.passed, 1);
  assert.equal(s.phase, 'review');
  assert.equal(s.best_pnl, 12);
  assert.equal(s.href, '/research/1');
});

test('queued and running research do not claim finalized results', () => {
  for (const status of ['queued', 'running']) {
    const [s] = sessions([run(1, status)], [], []);
    assert.equal(s.phase, 'researching');
    assert.equal(s.best_pnl, null);
  }
});

test('review opens the strongest passed unseen result before failed or untested candidates', () => {
  const [s] = sessions([run(1)], [
    strategy(10, 1, 'passed', 30), strategy(11, 1, 'passed', 12),
    strategy(12, 1, 'passed', null), strategy(13, 1, 'failed', 50),
  ], []);
  assert.deepEqual(Array.from(s.candidates, c => c.id), [10, 11, 12, 13]);
  assert.equal(s.best_pnl, 30);
});

test('failed, cancelled and zero-passing sessions remain in history', () => {
  for (const status of ['failed', 'cancelled', 'succeeded']) {
    const [s] = sessions([run(1, status)], [strategy(10, 1, 'rejected', null)], []);
    assert.equal(s.phase, 'history');
    assert.equal(s.pending, 0);
    assert.equal(s.candidates.length, 1);
    assert.equal(s.best_pnl, null);
  }
});

test('partial deployment counts candidates rather than deployment instances', () => {
  const [s] = sessions([run(1)], [strategy(10, 1), strategy(11, 1)], [
    { strategy_id: 10, status: 'running', mode: 'paper' },
    { strategy_id: 10, status: 'paused', mode: 'paper' },
    { strategy_id: 11, status: 'stopped', mode: 'paper' },
  ]);
  assert.equal(s.phase, 'deployed');
  assert.equal(s.deployments.length, 2);
  assert.equal(s.pending, 1);
});

test('an active deployment stays visible even when its session failed', () => {
  const [s] = sessions([run(1, 'failed')], [strategy(10, 1)], [{ strategy_id: 10, status: 'paused' }]);
  assert.equal(s.phase, 'deployed');
});

test('adjustments are grouped with the originating research session', () => {
  const child = { ...strategy(11, null), parent_id: 10 };
  const grandchild = { ...strategy(12, null), parent_id: 11 };
  const [s] = sessions([run(1)], [grandchild, child, strategy(10, 1)], []);
  assert.equal(s.key, 'run:1');
  assert.equal(s.candidates.length, 3);
});

test('older sessions missing from the run list retain their strategies', () => {
  const [s] = sessions([], [strategy(10, 50)], []);
  assert.equal(s.href, '/research/50');
  assert.equal(s.candidates.length, 1);
});

test('the run summary prevents truncated candidate windows from claiming no strategy passed', () => {
  const [s] = sessions([{ ...run(1), hypotheses_tried: 4, strategies_passed: 2 }], [], []);
  assert.equal(s.phase, 'review');
  assert.equal(s.passed, 2);
  assert.equal(s.tested, 4);
  assert.equal(s.best_pnl, null);
});

test('standalone adjustments retain a strategy deep link', () => {
  const [s] = sessions([], [{ ...strategy(10, null), parent_id: 1 }], []);
  assert.equal(s.href, '/strategies/10');
  assert.equal(s.phase, 'review');
});

test('broken parent cycles do not hang or lose candidates', () => {
  const a = { ...strategy(10, null), parent_id: 11 };
  const b = { ...strategy(11, null), parent_id: 10 };
  const result = sessions([], [a, b], []);
  assert.equal(result.length, 1);
  assert.equal(result[0].candidates.length, 2);
});

test('empty accounts and non-finite metrics have no fabricated P&L', () => {
  assert.equal(sessions([], [], []).length, 0);
  const [s] = sessions([run(1)], [strategy(10, 1, 'passed', NaN)], []);
  assert.equal(s.best_pnl, null);
});
