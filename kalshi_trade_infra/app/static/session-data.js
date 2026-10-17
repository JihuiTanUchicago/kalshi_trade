/* Fetch all pages for views that group strategies across research sessions. */
async function loadStrategyPages(request, filters = {}, current = () => true) {
  const rows = new Map();
  let page = 0, pages = 1;
  do {
    if (!current()) break;
    const query = new URLSearchParams({...filters, page: String(page)});
    const data = await request('/api/strategies?' + query);
    if (!current()) break;
    for (const row of data.strategies) rows.set(row.id, row);
    pages = data.pages ?? 1;
    page++;
  } while (page < pages);
  return {strategies: [...rows.values()]};
}

/* Group the existing research, strategy and deployment responses for the UI. */
function agentSessions(runs, strategies, deployments) {
  const byId = new Map(strategies.map(s => [s.id, s]));
  const sessions = new Map(runs.map(run => ['run:' + run.id, {
    key: 'run:' + run.id, run, run_id: run.id, title: run.prompt || 'Research session',
    market: run.market, created_at: run.created_at, candidates: [],
  }]));
  const active = deployments.filter(d => d.status !== 'stopped');
  const deployed = new Set(active.map(d => d.strategy_id));

  for (const strategy of strategies) {
    let parent = strategy;
    const visited = new Set();
    while (parent.run_id == null && parent.parent_id != null && byId.has(parent.parent_id)) {
      visited.add(parent.id);
      parent = byId.get(parent.parent_id);
      if (visited.has(parent.id)) break;
    }
    // An adjustment stays with its research session when its ancestor is available.
    const runId = parent.run_id;
    const rootId = visited.has(parent.id) ? Math.min(parent.id, ...visited) : parent.parent_id || parent.id;
    const key = runId != null ? 'run:' + runId : 'strategy:' + rootId;
    if (!sessions.has(key)) {
      sessions.set(key, {
        key, run: null, run_id: runId, market: parent.market, created_at: parent.created_at,
        title: runId != null ? 'Research session #' + runId : parent.title,
        candidates: [],
      });
    }
    sessions.get(key).candidates.push(strategy);
  }
  const order = { passed: 0, failed: 1, rejected: 2 };
  for (const session of sessions.values()) {
    session.candidates.sort((a, b) => (order[a.status] ?? 3) - (order[b.status] ?? 3) ||
      (Number.isFinite(b.out_of_sample?.pnl) ? b.out_of_sample.pnl : -Infinity) -
      (Number.isFinite(a.out_of_sample?.pnl) ? a.out_of_sample.pnl : -Infinity) || b.id - a.id);
    const ids = new Set(session.candidates.map(s => s.id));
    session.deployments = active.filter(d => ids.has(d.strategy_id));
    session.passed = Math.max(session.run?.strategies_passed || 0, session.candidates.filter(s => s.status === 'passed').length);
    session.pending = Math.max(0, session.passed - session.candidates.filter(s => s.status === 'passed' && deployed.has(s.id)).length);
    session.tested = Math.max(session.run?.hypotheses_tried || 0, session.candidates.length);
    const passed = session.candidates.filter(s => s.status === 'passed');
    const pnl = (passed.length ? passed : session.candidates).map(s => s.out_of_sample?.pnl).filter(Number.isFinite);
    session.best_pnl = pnl.length ? Math.max(...pnl) : null;
    session.phase = session.deployments.length ? 'deployed'
      : ['running', 'queued'].includes(session.run?.status) ? 'researching'
      : ['failed', 'cancelled'].includes(session.run?.status) ? 'history'
      : session.passed ? 'review' : 'history';
    session.href = session.run_id != null ? '/research/' + session.run_id : '/strategies/' + session.candidates[0].id;
  }
  return [...sessions.values()].sort((a, b) => (Date.parse(b.created_at) || 0) - (Date.parse(a.created_at) || 0));
}
