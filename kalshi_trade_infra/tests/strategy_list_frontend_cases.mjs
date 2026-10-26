// Strategies list (/strategies) cases, run against each bundle's offline DOM/transport harness.
import assert from 'node:assert/strict';
import {test} from 'node:test';

const response = (data, status = 200) => ({ok: status < 400, status, json: async () => data});

export function strategyListCases({name, frontend, detailStrategy}) {
  const row = (f, s) => f.strategySlip(detailStrategy({id: 46, title: 'List fixture', ...s}), null, {});
  const badge = html => (html.match(/<span class="mk (?:live|dep)">([^<]*)<\/span>/) || [])[1];

  test(`${name}: a deployed row's badge names the books it runs in, not "Deployed"`, () => {
    const f = frontend({fetchImpl: () => response({})});
    assert.equal(badge(row(f, {deployed: true, books: ['paper'], real: {pnl: 1, trades: 1, open: 0, mode: 'paper'}})), 'On paper');
    assert.equal(badge(row(f, {deployed: true, books: ['demo'], real: {pnl: 1, trades: 1, open: 0, mode: 'demo'}})), 'On demo');
    assert.equal(badge(row(f, {deployed: true, books: ['paper', 'demo'], real: {pnl: 1, trades: 1, open: 0, mode: 'paper'}})), 'On paper + demo');
    const live = row(f, {deployed: true, deploy_live: true, books: ['live', 'paper'], real: {pnl: 1, trades: 1, open: 0, mode: 'live', live: true}});
    assert.equal(badge(live), 'Live + paper'); assert.match(live, /<span class="mk live">Live \+ paper<\/span>/);
    // A server that sends no books keeps the old badge rather than guessing a book.
    assert.equal(badge(row(f, {deployed: true, real: {pnl: 1, trades: 1, open: 0}})), 'Deployed');
    assert.equal(badge(row(f, {deployed: false})), undefined);
  });

  test(`${name}: a row says what its removed deployments made, each book on its own line`, () => {
    const f = frontend({fetchImpl: () => response({})});
    const html = row(f, {deployed: false, past: {paper: {pnl: -13.56, trades: 9, deployments: 1}, demo: {pnl: 0, trades: 0, deployments: 1}}});
    assert.match(html, /Removed from paper: <span class="[^"]*">−\$13\.56<\/span> · 9 trades/);
    assert.match(html, /Removed from demo: no closed trades/);
    assert.ok(html.indexOf('Removed from paper') < html.indexOf('Removed from demo'));
    // Beside an active record it stays apart: never added into "since deploying".
    const both = row(f, {deployed: true, books: ['paper'], real: {pnl: 4, trades: 2, open: 0, mode: 'paper'}, past: {paper: {pnl: 2.25, trades: 4, deployments: 1}}});
    assert.match(both, /\+\$4\.00<\/span> on paper since deploying · 2 trades/);
    assert.match(both, /Removed from paper: <span class="[^"]*">\+\$2\.25<\/span> · 4 trades/);
    assert.doesNotMatch(both, /\$6\.25/);
    assert.doesNotMatch(row(f, {}), /Removed from/);
    // A research-only strategy never shows a book record, even if one leaks in.
    assert.doesNotMatch(row(f, {kind: 'code', research_only: true, past: {paper: {pnl: 1, trades: 1}}}), /Removed from/);
  });
}
