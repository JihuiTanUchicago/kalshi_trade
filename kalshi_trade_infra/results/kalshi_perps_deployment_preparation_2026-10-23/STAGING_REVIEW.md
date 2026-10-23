# Native perpetual manual-order staging acceptance

Workstream: `bitcoin_perps_data` / October 23, 2026, Asia/Shanghai.
Status: implemented and offline verified; hosted full-schema/MySQL/HTTP acceptance
remains pending. No workflow dispatch or production change performed.

Scope: a separate `verify-perps` process, new synthetic native broker acceptance
script and offline tests, the staging entrypoint/image allowlist, the exact image
COPY contract, and minimal hosted-workflow integration. Existing Alpaca acceptance
remains a separate first run. Root owns runtime integration, schema, shared
trackers and publication. No compose service, host port, provider credential,
production setting, deployment, worker or real order is authorized here.

The published staging web keeps `TAU_KALSHI_PERPS_LIVE_ENABLED=0`. Only the
unpublished loopback verifier uses the enabled flag with a synthetic client;
socket restrictions permit the disposable database and its own local HTTP
server. The full candidate `app.schema` must create the new order tables before
verification. Preview and proposal review must send no broker order; exact manual
confirmation must commit its single-send claim before the synthetic POST.

The verifier has 19 checks. It covers authenticated owner sessions and CSRF,
encrypted ephemeral keys bound to each user, explicit real-money opt-in,
idempotent previews, precise native USD/contract and BTC-unit arithmetic,
owner isolation, exact ticket/version/digest confirmation, independent visibility
of the committed claim before a single synthetic POST, duplicate confirmation,
accepted-but-uncertain response handling without retry, GET-only reconciliation,
agent proposal creation/review/preview without submission, exact proposal
confirmation, draft cancellation, stale/ineligible preflight, transaction rollback,
the native identity uniqueness constraint, opt-out, and unchanged binary paper
money with no active jobs. The agent proposal check calls the real `agent.act`
adapter with its action envelope and `autopilot=True`; a separate confirmation is
still required. Synthetic order notional is allowed to exceed synthetic account
equity, so the verifier does not introduce a Tau leverage/notional cap.

The existing five compose services and gateway policy are unchanged. The hosted
workflow runs the original 14-check Alpaca verifier first, then overrides only
the existing unpublished verifier's command with `verify-perps`. It requires the
new 19-check receipt, three synthetic submissions and three independently visible
claims, no provider calls, no active jobs, and no order in another environment.
It separately checks the published web process's three disabled flags and gateway
authentication/write rejection, and hashes the perps UI assets. Only predicates,
counts, fixed check codes and source hashes enter artifacts; raw process
environment, keys, account/order responses and container logs are excluded.

Owned paths:

- `scripts/kalshi_perps_staging_smoke.py`, `tests/test_kalshi_perps_staging.py`.
- `staging/entrypoint.py`, `staging/Dockerfile`, and one image-allowlist line in
  `staging/Dockerfile.dockerignore`.
- The exact COPY expectation in `tests/test_staging_stack.py` and minimal
  `.github/workflows/paper-staging.yml` integration.
- This handoff. `staging/compose.yml` was not changed. Runtime source, schema,
  shared trackers, credentials and production remain outside this workstream.

Offline verification used Python 3.12 from the existing isolated product venv:

```text
python -m pytest tests/test_staging_stack.py tests/test_paper_staging_smoke.py \
  tests/test_kalshi_perps_staging.py tests/test_kalshi_perps_orders_repository.py \
  tests/test_kalshi_perps_trading.py tests/test_kalshi_perps_trading_client.py -q
365 passed

python -m py_compile staging/entrypoint.py scripts/kalshi_perps_staging_smoke.py \
  tests/test_kalshi_perps_staging.py
passed

git diff --check
passed
```

There are 70 new offline staging cases (107 including the existing stack/paper
tests), covering flag and credential rejection, image/schema/workflow contracts,
compiled embedded workflow Python, receipt sanitization, independent committed
claim checks and native synthetic fixture behavior. The current full candidate
schema includes the new order-store DDL; this is a source assertion, not a claim
that schema has run here. The independent guard reviewer found no concrete
isolation or receipt-secret blocker in the scoped changes and likewise did not
run Docker/MySQL.

The local machine has neither Docker nor MySQL executables, so the full hosted
acceptance has not run in this workstream. The release owner must publish an
immutable candidate and obtain passing `paper-staging` evidence before treating
these real-DB/HTTP gates as accepted. The required sequence remains full
`app.schema`, public preview/runtime checks, old `verify`, new `verify-perps`,
receipt validation, and disposable volume cleanup. Hosted evidence will prove
only synthetic broker lifecycle acceptance; real Kalshi eligibility, connectivity,
margin, fees, liquidity and order acceptance remain separate production gates.
No real key, provider/API/order call, model call, commit, push, deployment or
workflow dispatch occurred. Ownership is handed back to root; shared records
remain root-owned as requested.
