import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import vm from 'node:vm';

const context = vm.createContext({});
vm.runInContext(readFileSync(new URL('../app/static/session-chat.js', import.meta.url), 'utf8'), context);
const { sessionChatApi, newSessionChatState, mergeSessionChat, sessionRevisionPassed, sessionTargetChanged } = context;
const payload = (messages = [], proposals = [], key = 'run:7') => ({ session_key: key, messages, proposals });
const message = (id, content = 'Question') => ({ id, content, role: 'user', strategy_id: 8 });

test('compact message targets identify each context change without altering source records', () => {
  const messages = [8, 8, 9, null, undefined, 8].map((strategy_id, i) => Object.freeze({ id: i + 1, strategy_id }));
  assert.deepEqual(messages.map((_, i) => sessionTargetChanged(messages, i)), [true, false, true, true, false, true]);
  assert.deepEqual(messages.map(m => m.strategy_id), [8, 8, 9, null, undefined, 8]);
});

test('reads use a scoped endpoint and the existing after cursor convention', async () => {
  const calls = [];
  const client = sessionChatApi((...args) => { calls.push(args); return Promise.resolve({}); }, 'run:7');
  await client.read(15);
  assert.deepEqual(calls, [['/api/sessions/run/7/chat?after=15']]);
});

test('an orphan strategy family has its own connection key', async () => {
  let path;
  await sessionChatApi(value => { path = value; }, 'strategy:9').read();
  assert.equal(path, '/api/sessions/strategy/9/chat?after=0');
});

test('outgoing messages retain captured candidate identity and an idempotency key', async () => {
  let body;
  const client = sessionChatApi((path, value) => { body = value; }, 'run:7');
  await client.send('  Make fewer trades  ', 8, 'message-123');
  assert.equal(body.content, 'Make fewer trades');
  assert.equal(body.strategy_id, 8);
  assert.equal(body.client_message_id, 'message-123');
  await client.send('How is research progressing?', null, 'message-124');
  assert.equal(body.strategy_id, null);
});

test('invalid scope, cursors, message bodies and actions cannot reach the transport', () => {
  const request = () => assert.fail('transport called');
  for (const key of ['user:7', 'run:0', 'run:../9', 'run:7/chat', 'run:9007199254740993']) assert.throws(() => sessionChatApi(request, key));
  const client = sessionChatApi(request, 'run:7');
  assert.throws(() => client.read(-1));
  assert.throws(() => client.send(' ', 8, 'one'));
  assert.throws(() => client.send('x'.repeat(2001), 8, 'one'));
  assert.throws(() => client.send('A question', 8.5, 'one'));
  assert.throws(() => client.send('A question', 8, ''));
  assert.throws(() => client.action(1, 'live'));
  assert.throws(() => client.action('../1', 'approve'));
});

test('proposal actions remain inside the conversation scope', async () => {
  const paths = [];
  const client = sessionChatApi(path => { paths.push(path); }, 'run:7');
  for (const action of ['backtest', 'queue', 'approve', 'reject']) await client.action(3, action);
  assert.deepEqual(paths, ['backtest', 'queue', 'approve', 'reject'].map(a => `/api/sessions/run/7/proposals/3/${a}`));
});

test('incremental messages deduplicate IDs and never move the cursor backwards', () => {
  const state = newSessionChatState();
  mergeSessionChat(state, payload([message(4), message(2)]), 'run:7');
  mergeSessionChat(state, payload([message(2), message(5)]), 'run:7');
  assert.equal(state.messages.size, 3);
  assert.equal(state.after, 5);
  assert.deepEqual(Array.from(state.messages.keys()).sort((a,b) => a-b), [2,4,5]);
});

test('proposal changes update even when no new message arrives', () => {
  const state = newSessionChatState();
  mergeSessionChat(state, payload([message(1)], [{ id: 3, kind: 'revise', base_strategy_id: 8, status: 'pending', backtest_status: 'running' }]), 'run:7');
  mergeSessionChat(state, payload([], [{ id: 3, kind: 'revise', base_strategy_id: 8, status: 'pending', backtest_status: 'passed' }]), 'run:7');
  assert.equal(state.proposals.size, 1);
  assert.equal(state.proposals.get(3).backtest_status, 'passed');
  assert.equal(state.after, 1);
});

test('foreign or malformed responses do not partially overwrite cached conversation', () => {
  const state = newSessionChatState();
  mergeSessionChat(state, payload([message(1)]), 'run:7');
  assert.throws(() => mergeSessionChat(state, payload([message(2)], [], 'run:8'), 'run:7'));
  assert.throws(() => mergeSessionChat(state, payload([message(2), { id: 3, role: 'agent', content: null }]), 'run:7'));
  assert.throws(() => mergeSessionChat(state, payload([message(2)], [{ id: 3, kind: 'revise', status: 'pending', base_strategy_id: '../9' }]), 'run:7'));
  assert.throws(() => mergeSessionChat(state, payload([message(2)], [{ id: 3, kind: 'revise', status: 'pending', base_strategy_id: 8, diff: 'invalid' }]), 'run:7'));
  assert.throws(() => mergeSessionChat(state, payload([{ ...message(2), strategy_id: '8' }]), 'run:7'));
  assert.throws(() => mergeSessionChat(state, null, 'run:7'));
  assert.equal(state.messages.size, 1);
  assert.equal(state.after, 1);
});

test('scopes have independent drafts and conversation state', () => {
  const a = newSessionChatState(), b = newSessionChatState();
  a.draft = 'First session only';
  mergeSessionChat(a, payload([message(1)]), 'run:7');
  assert.equal(b.draft, '');
  assert.equal(b.messages.size, 0);
});

test('only a current passed revision with real gate evidence can be approved', () => {
  const p = { status: 'pending', backtest_status: 'passed', result: { passed: true, out_of_sample: { pnl: 32.4, trades: 32, max_drawdown: 9.6 }, gates: [{ ok: true }] } };
  assert.equal(sessionRevisionPassed(p), true);
  assert.equal(sessionRevisionPassed({ ...p, result: { ...p.result, gates: [] } }), false);
  assert.equal(sessionRevisionPassed({ ...p, result: { ...p.result, gates: [{ ok: false }] } }), false);
  assert.equal(sessionRevisionPassed({ ...p, backtest_status: 'running' }), false);
  assert.equal(sessionRevisionPassed({ ...p, status: 'applied' }), false);
  assert.equal(sessionRevisionPassed({ ...p, result: { passed: true, gates: [{ ok: true }] } }), false);
  assert.equal(sessionRevisionPassed({ ...p, result: { ...p.result, out_of_sample: { ...p.result.out_of_sample, pnl: NaN } } }), false);
});
