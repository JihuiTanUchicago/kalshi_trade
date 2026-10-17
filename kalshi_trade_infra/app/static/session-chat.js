/* Session-only connection contract. The account-wide /api/chat is not a fallback. */
function sessionChatApi(request, key) {
  const match = /^(run|strategy):([1-9]\d*)$/.exec(key);
  if (!match || !Number.isSafeInteger(Number(match[2]))) throw new Error('Invalid conversation session.');
  const base = `/api/sessions/${match[1]}/${match[2]}`;
  const id = value => {
    if (!Number.isSafeInteger(value) || value < 1) throw new Error('Invalid conversation record.');
    return value;
  };
  return {
    read(after = 0) {
      if (!Number.isSafeInteger(after) || after < 0) throw new Error('Invalid message cursor.');
      return request(`${base}/chat?after=${after}`);
    },
    send(content, strategyId, messageId) {
      if (typeof content !== 'string' || !content.trim() || content.trim().length > 2000) throw new Error('Keep messages between 1 and 2,000 characters.');
      if (typeof messageId !== 'string' || !messageId) throw new Error('Missing message identity.');
      return request(`${base}/chat`, { content: content.trim(), strategy_id: strategyId == null ? null : id(strategyId), client_message_id: messageId });
    },
    action(proposalId, action) {
      if (!['backtest', 'queue', 'approve', 'reject'].includes(action)) throw new Error('Unsupported conversation action.');
      return request(`${base}/proposals/${id(proposalId)}/${action}`, {});
    },
  };
}

function newSessionChatState() {
  return { messages: new Map(), proposals: new Map(), after: 0, draft: '', draftVersion: 0, pendingMessage: null, sending: false, reviewId: null, error: '', scrollTop: 0, following: true, actions: new Set() };
}

function sessionTargetChanged(messages, index) {
  return index === 0 || (messages[index].strategy_id ?? null) !== (messages[index - 1].strategy_id ?? null);
}

function mergeSessionChat(state, data, key) {
  if (!data || data.session_key !== key || !Array.isArray(data.messages) || !Array.isArray(data.proposals)) throw new Error('The conversation response does not match this session.');
  for (const m of data.messages) {
    if (!m || !Number.isSafeInteger(m.id) || m.id < 1 || typeof m.content !== 'string' || !['user', 'agent', 'system'].includes(m.role) ||
        [m.strategy_id, m.proposal_id].some(value => value != null && (!Number.isSafeInteger(value) || value < 1))) throw new Error('The conversation contains an invalid message.');
  }
  for (const p of data.proposals) {
    if (!p || !Number.isSafeInteger(p.id) || p.id < 1 || !['pending', 'applied', 'rejected'].includes(p.status) ||
        !['revise', 'adjust', 'trial'].includes(p.kind) ||
        (p.base_strategy_id != null && (!Number.isSafeInteger(p.base_strategy_id) || p.base_strategy_id < 1)) ||
        (p.kind !== 'trial' && p.base_strategy_id == null) ||
        (p.diff != null && (!Array.isArray(p.diff) || p.diff.some(d => !d || typeof d.label !== 'string' || typeof d.before !== 'string' || typeof d.after !== 'string'))) ||
        (p.result?.gates != null && (!Array.isArray(p.result.gates) || p.result.gates.some(g => !g || typeof g.ok !== 'boolean')))) throw new Error('The conversation contains an invalid suggestion.');
  }
  for (const m of data.messages) { state.messages.set(m.id, m); state.after = Math.max(state.after, m.id); }
  for (const p of data.proposals) state.proposals.set(p.id, p);
}

function sessionRevisionPassed(proposal) {
  const result = proposal.result;
  return proposal.status === 'pending' && proposal.backtest_status === 'passed' && result?.passed === true &&
    [result.out_of_sample?.pnl, result.out_of_sample?.trades, result.out_of_sample?.max_drawdown].every(Number.isFinite) && result.out_of_sample.trades > 0 &&
    Array.isArray(result.gates) && result.gates.length > 0 && result.gates.every(g => g?.ok === true);
}
