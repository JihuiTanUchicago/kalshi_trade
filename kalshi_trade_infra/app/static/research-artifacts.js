/* Open strategy tabs belong to one research workspace. */
function newResearchArtifacts() {
  return { openIds: [], selectedId: null, entries: new Map() };
}

function openResearchArtifact(state, strategy) {
  if (!Number.isSafeInteger(strategy?.id) || strategy.id < 1) throw new Error('Invalid strategy artifact.');
  if (!state.entries.has(strategy.id)) {
    state.openIds.push(strategy.id);
    state.entries.set(strategy.id, { strategy, detail: null, scenario: null });
  }
  state.selectedId = strategy.id;
  return state.entries.get(strategy.id);
}

function selectResearchArtifact(state, id) {
  if (!state.entries.has(id)) throw new Error('This strategy tab is not open.');
  state.selectedId = id;
}

function closeResearchArtifact(state, id) {
  const index = state.openIds.indexOf(id);
  if (index < 0) return;
  state.openIds.splice(index, 1);
  state.entries.delete(id);
  if (state.selectedId === id) state.selectedId = state.openIds[Math.min(index, state.openIds.length - 1)] ?? null;
}
