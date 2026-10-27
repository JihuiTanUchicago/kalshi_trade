import test from 'node:test';
import assert from './assert_text.mjs';
import { readFileSync } from 'node:fs';
import { runInNewContext } from 'node:vm';

const api = runInNewContext(readFileSync(new URL('../app/static/research-artifacts.js', import.meta.url), 'utf8') + '\n({newResearchArtifacts, openResearchArtifact, selectResearchArtifact, closeResearchArtifact})');

test('opening existing and failed artifacts keeps one tab per source ID', () => {
  const state = api.newResearchArtifacts();
  api.openResearchArtifact(state, { id: 2, status: 'failed' });
  const entry = api.openResearchArtifact(state, { id: 1, status: 'passed' });
  entry.scenario = { stake: 20 };
  assert.equal(api.openResearchArtifact(state, { id: 1 }), entry);
  assert.deepEqual([...state.openIds], [2, 1]);
  assert.equal(state.selectedId, 1);
  assert.equal(entry.scenario.stake, 20);
});

test('switching tabs retains the other artifact and its scenario', () => {
  const state = api.newResearchArtifacts();
  const entry = api.openResearchArtifact(state, { id: 1 });
  entry.scenario = { result: { passed: false }, fee: 3 };
  api.openResearchArtifact(state, { id: 2 });
  api.selectResearchArtifact(state, 1);
  assert.equal(state.selectedId, 1);
  assert.equal(state.entries.get(1).scenario.fee, 3);
  assert.equal(state.entries.size, 2);
});

test('closing the selected middle tab selects its right neighbor', () => {
  const state = api.newResearchArtifacts();
  [1, 2, 3].forEach(id => api.openResearchArtifact(state, { id }));
  api.selectResearchArtifact(state, 2);
  api.closeResearchArtifact(state, 2);
  assert.deepEqual([...state.openIds], [1, 3]);
  assert.equal(state.selectedId, 3);
  assert.equal(state.entries.has(2), false);
});

test('closing an inactive tab keeps selection; closing the last clears it', () => {
  const state = api.newResearchArtifacts();
  [1, 2].forEach(id => api.openResearchArtifact(state, { id }));
  api.closeResearchArtifact(state, 1);
  assert.equal(state.selectedId, 2);
  api.closeResearchArtifact(state, 2);
  assert.equal(state.selectedId, null);
  assert.equal(state.entries.size, 0);
  api.closeResearchArtifact(state, 2);
});

test('research workspaces have independent open artifacts', () => {
  const first = api.newResearchArtifacts(), second = api.newResearchArtifacts();
  api.openResearchArtifact(first, { id: 1 });
  assert.equal(second.entries.size, 0);
  assert.equal(second.selectedId, null);
});

test('invalid source IDs and unopened selections fail without changing state', () => {
  const state = api.newResearchArtifacts();
  for (const id of [null, 0, -1, '1', 1.5, Number.MAX_SAFE_INTEGER + 1]) {
    assert.throws(() => api.openResearchArtifact(state, { id }), /Invalid/);
  }
  assert.throws(() => api.selectResearchArtifact(state, 1), /not open/);
  assert.equal(state.openIds.length, 0);
  assert.equal(state.selectedId, null);
});
