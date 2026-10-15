# Session conversation connection contract

Status: **active frontend connection contract**, October 15, 2026 (started
October 14). After completing the restoration, Research sessions now put the
conversation on the left and strategy artifacts in tabs on the right.
`session-chat.js` is loaded by the active entrypoint and receives the existing
same-origin transport. Artifact selection changes the composer context; message
and proposal targets retain their immutable source strategy IDs.

These backend endpoints remain **unimplemented**. Missing routes show Not
connected, preserve drafts and disable writes. The approved UI-plus-contract scope
is unchanged. Do not forward scoped messages to account-wide `/api/chat`, whose
history and worker context are shared across the user. Current layout/evidence:
[workspace handoff](../results/meridian_frontend_pr_2026-10-15/HANDOFF.md).

## Identity and transport

A research family uses `run:{run_id}` and `/api/sessions/run/{run_id}`. An adjustment
family without a research run uses `strategy:{root_strategy_id}` and
`/api/sessions/strategy/{root_strategy_id}`. Candidate revisions retain ancestry.
Resolve the family and ownership on the server, including older ancestors beyond
the frontend's list window. Echo the requested `session_key` in every response.
IDs are positive JSON integers, timestamps are ISO 8601 with a timezone, and
strategy IDs identify immutable candidate versions. Display labels are not IDs.

Requests use the existing same-origin cookie session and `X-Recursive: 1` on JSON
POSTs. There is no separate credential, transport, CORS service or global-chat
fallback. Authenticate and check owner/session membership on **every** read and
write, including proposals, candidates and any targeted deployment. Frontend
capabilities control affordances, not authorization.

After the October 14 upstream sync, `/api/me` also supplies `needs_card`,
`billing_enabled`, `credit_balance` and `free_bonus`. The current Research form and
global payment dialog honor these fields. Future session sends/queued agent work
must reuse `_require_billing_ready` and the existing rate limits, including the
operator's card requirement. Agent credits are separate from paper trading funds.
No billing/customer/card response is added to the session message payload.

## Read history and current suggestions

`GET {base}/chat?after=0`

```json
{
  "session_key": "run:7",
  "messages": [{
    "id": 15,
    "role": "agent",
    "content": "Try a higher entry edge while keeping the stake fixed.",
    "created_at": "2026-10-14T06:20:00Z",
    "strategy_id": 8,
    "proposal_id": 3
  }],
  "proposals": [{
    "id": 3,
    "kind": "revise",
    "status": "pending",
    "base_strategy_id": 8,
    "reason": "Reduce weak entries without raising the stake.",
    "diff": [{"label": "Minimum entry edge", "before": "6%", "after": "8%"}],
    "backtest_status": "not_run",
    "result": null
  }],
  "capabilities": {
    "send": true,
    "backtest": true,
    "queue": false,
    "approve": true,
    "reject": true
  },
  "agent_busy": false,
  "has_more": false
}
```

Read messages with `id > after`, ordered by ID, scoped to this session. The UI polls
every three seconds while visible, deduplicates IDs and tracks the greatest ID.
For a limited page return `has_more: true`; the client continues until false and
rejects a page that cannot advance. Define the initial history window explicitly
when implementing the backend (the UI does not provide older-history browsing).

Return the session's current proposals on every read, even if no message is new:
backtest status and decisions can change independently of the message cursor.
Include the applied/rejected final record so cached pending suggestions disappear.
Messages are append-only and their strategy/proposal association is immutable;
proposal identity, kind and base target are immutable. Omitted capability values
mean disabled. `agent_busy` permits another message; backend controls scheduling.

Message roles: `user`, `agent`, `system`. `strategy_id` can be null for research
context. `proposal_id` is optional/null. Content is plain text, escaped by the UI.

Proposal kinds:

| Kind | Target | UI action |
|---|---|---|
| `revise` | `base_strategy_id` | Backtest → review comparison → save a new candidate |
| `adjust` | `base_strategy_id`, `deployment_id`, `mode` | Same review; apply only when `mode` is `paper` |
| `trial` | optional `base_strategy_id` | Queue next trial only during active research |

Statuses are `pending`, `applied`, `rejected`. Backtest statuses are `not_run`,
`running`, `passed`, `failed`. `diff` contains display strings for before/after;
server stores and validates the exact proposed spec independently of these labels.
An `applied` revision may include its new `strategy_id`.

When a backtest finishes, `result` follows the existing evaluator's metric names:

```json
{
  "passed": true,
  "in_sample": {"pnl": 54.8, "trades": 70, "max_drawdown": 12.6},
  "out_of_sample": {"pnl": 32.4, "trades": 32, "max_drawdown": 9.6},
  "gates": [{"name": "Positive unseen P&L", "threshold": "> $0", "value": 32.4, "ok": true}]
}
```

These figures are **synthetic contract examples**, not research evidence. Actual
results must use the existing evaluator/fees/gates and include all required gates.
The comparison displays the original saved candidate's unseen P&L, trades and
maximum drawdown beside the proposed result. What-if results stay separate. A
save requires pending status, passed backtest, finite unseen metrics, positive
trade count and nonempty all-passed gate evidence. Backend must enforce the full
verdict and bind it to the exact immutable spec/base version being approved.
Live adjustments are handed to Position; this UI does not approve live changes.

## Send a message

`POST {base}/chat`

```json
{
  "content": "Keep stake fixed and reduce weak entries.",
  "strategy_id": 8,
  "client_message_id": "3e696586-88de-4c39-88b1-23c216747e7e"
}
```

Content: 1–2,000 trimmed characters. The UI captures the selected candidate at send
time; use null during research. Store that association rather than the candidate
later selected in the browser. UUID `client_message_id` remains the same when
retrying the same draft/target. Deduplicate per authenticated user and session;
a repeated key with a different body must be rejected. Persist the user message
and schedule session-scoped agent work before acknowledging:

```json
{"session_key": "run:7", "message_id": 16}
```

The acknowledgement clears only the submitted draft. New typing survives a late
response. Agent messages arrive through reads; the frontend never invents a reply.
A route change discards late DOM updates, while acknowledging the cached draft
safely. Session state is keyed by user and session and clears on sign out. Drafts
and cached transcripts last only for the current page instance; persistent
history, agent work and reload recovery belong to the backend.

## Suggestion actions

`POST {base}/proposals/{proposal_id}/{action}` with `{}`.

| Action | Required backend behavior |
|---|---|
| `backtest` | Queue an idempotent test of the frozen proposed spec; expose running/passed/failed on subsequent reads. A retry of a failed test is supported. |
| `queue` | Only an active research session and pending trial; schedule at a safe agent boundary, preserving the run and evaluation protocol. |
| `approve` | Recheck owner, current proposal/base, exact test verdict and risk limits. For `revise`, create a new candidate with parent/run ancestry and retain the original. For `adjust`, require explicit paper target and preserve engine safeguards. |
| `reject` | Record rejection, retain original candidate/deployment, cancel or ignore pending test work safely. |

Acknowledgement:

```json
{"session_key": "run:7", "proposal_id": 3, "strategy_id": 21}
```

`strategy_id` is optional and used after approval to open the saved candidate. An
approved adjustment must associate its new strategy with the same family. Repeated
actions must not duplicate tests, trials, candidates or deployment changes. Return
the previous outcome for an identical retry, or `409` for incompatible stale state.
The frontend blocks concurrent actions per proposal and requires opening the
comparison on its original candidate before approval. It never modifies a spec,
calculates a backtest or executes a trade locally.

## Errors and backend acceptance gate

JSON errors: `{"error":"Human-readable explanation"}`. Use `401` for sign-in,
`403` for unavailable permission, `404` for missing/foreign records or currently
unimplemented routes, `409` for stale/conflicting state, `429` for rate limiting,
and `5xx` for transient failures. `501` also means not connected. Reads recover on
later polls or Retry connection. Drafts and cached messages survive errors; sends
and writes remain disabled until a successful read supplies capabilities. Failed
POSTs retain the draft/proposal and show an error; a later successful read clears
the connection notice. Send/action failures remain visible until a retry; successful
connection polling does not erase them. Avoid leaking another session's identifiers or content in
an error response.

Future backend work must add session persistence/ownership, scoped worker context
and queue semantics, revision creation and idempotency. Keep unseen evaluation
isolated from the agent's hypothesis iteration, and preserve existing deployment,
autopilot and live-money gates. Test multiple accounts/sessions, concurrent agents,
retry/restart, stale approvals and authenticated non-production paper behavior
before considering this integrated. Scoped session routes, schema and worker business logic remain unimplemented
by this frontend contract. Existing upstream research/deployment APIs are retained.
