# API credential deployment handoff

Workstream: `tau-api-secret-handoff-20261017`; started 2026-10-17T21:48:25.895790+08:00, Asia/Shanghai.
Status: encrypted secret sync verified / deployment-owner handoff ready; advisory reservation released.

The user requests API sharing through GitHub for a teammate's production deployment. The repository is public; keep the real ignored mode-0600 `.env` outside Git history. Authorized safe upload scope: only configured `MASSIVE_API_KEY` and `EXA_API_KEY`, stored as encrypted repository GitHub Actions Secrets via stdin. Initial remote secret list is empty; no existing credential will be overwritten. Alpaca and Databento keys are absent from the current product `.env`; no unrelated key locations are searched or copied.

Root owns PLAN/MVP, app README/deployment handoff and workstream evidence. No-touch: actual private `.env` contents/modes, provider enable flags, trading controls, live services, production AWS resources, DB/schema, other products/worktrees. No paid provider/model calls, deployment or service restart.

GitHub Actions Secrets support workflow injection and do not provide a readable download for a manual deployer. Existing `scripts/load_app_secrets.sh` reads `/recursive/NAME` SSM parameters into `/opt/kalshi/.env.app` and restarts web/agents when explicitly run on the server. Do not run it in this task. The user answered that the deployment method is not known yet. Both delivery paths are documented; no target is assumed.

Next: synchronize the two named secrets, verify names/metadata without printing values, document the deployment handoff and its remaining boundary.

## Encrypted GitHub sync completed

Both `MASSIVE_API_KEY` and `EXA_API_KEY` were read as literal values from the ignored product `.env`, passed over stdin to `gh secret set --app actions`, encrypted by the CLI before transmission and stored in the public repository's encrypted Actions secret storage. Both commands returned success; the subsequent names/timestamp read confirms creation. Values were never printed, placed in command arguments, written to new plaintext files or committed. The `.env` bytes and mode are unchanged. `UPLOAD_RECEIPT.json` contains only names, timestamps and result metadata; GitHub does not return stored values for readback.

The user is not sure which deployment method the teammate uses. `app/DEPLOYMENT_SECRETS.md` covers trusted Actions environment injection and the existing AWS SSM path. No workflow has been created/run and no AWS parameter has been written. A git pull alone cannot make these APIs available to a running service. Production delivery/activation remains the deployment owner's responsibility under the already-recorded provider rollout gates.

New operator guide is linked from app README. `.env.example` is already committed and contains blank credentials; no template change or copying of development flags is needed. Alpaca/Databento keys are absent from this current `.env`, not asserted absent from all environments. The selected secret sync is a one-time snapshot, not a recurring sync daemon.

Final verification: infrastructure **878 passed / 9 skipped (6.35s)** with all data providers and opt-in MySQL disabled and AWS metadata disabled. Independent read-only source review confirmed loader/systemd/key/activation claims and requested explicit callback handling: the guide now passes the production callback through `sudo env REDIRECT_URI=...` and states that the loader refreshes other app secrets/settings and restarts web/agents. No runtime code or public Dev Log shipped-capability entry changes are warranted for this operational handoff.

## Completion and delivery boundary

[Deployment-owner guide](../../app/DEPLOYMENT_SECRETS.md) and README are ready to publish alongside PLAN/MVP and this metadata-only evidence. `UPLOAD_RECEIPT.json` contains actual GitHub creation timestamps and no secret values. `VERIFICATION.json` records source checks and test results. Completion recorded 2026-10-17T13:51:57.245321+00:00; reservation released.

The real APIs have not been tested from production by this handoff. Teammate must select a deployment target, arrange server-side secret delivery and accept a real worker/provider canary under the existing rollout plan. GitHub secret storage is not a human-readable credential download. No automatic synchronization or deployed secret-store changes are claimed.

## Local provider environment consolidation — subsequent user request

Workstream `tau-local-provider-env-20261017`; status in progress, advisory reservation active. The user now authorizes copying the available Alpaca pair from Polygon's private `.env` to Tau's ignored private `.env`, preserving existing entries. Root owns only the target private file and narrow PLAN/MVP/README/deployment-guide/handoff updates. Preserve the original Polygon file, runtime code, provider enable flags, other credentials and GitHub/AWS state. Databento has no available local value; prepare an empty named field without claiming a restored credential. No commits, cloud writes, service restart, paid/provider call or trading activation. Verification is literal parsing, source/other-field preservation and offline provider configuration only.

### Local consolidation result

**Available Alpaca pair copied and offline verified; advisory reservation released.** The private target now contains the exact source pair and a blank `DATABENTO_API_KEY=` placeholder. All prior target bytes/assignments and source bytes/mode are preserved. Target remains ignored/untracked and mode0600. Actual Alpaca `Config.from_env` accepted the pair using literal in-memory parsing; no shell evaluation or provider request. Provider enable flags are unchanged.

`LOCAL_ENV_CONSOLIDATION.json` records names/booleans only; no values or private-file contents are in evidence. PLAN/MVP, README and operator guide now distinguish this local credential state from the earlier Massive/Exa GitHub-only sync. Databento’s existing open item now includes restoring its missing key. Public Dev Logs remain appropriate to the unchanged production capability; no shipped entry is added. Runtime code/tests/architecture are unchanged, so no redundant full-suite or live-provider run was made for this private configuration copy.

The user must re-enter the unavailable Databento value in Tau’s ignored `.env` to complete that credential. No production/GitHub/AWS operation, service restart, provider HTTP/paid/model call, commit or push occurred in this local-consolidation workstream.

## Alpaca and Databento encrypted secret synchronization

Workstream `tau-alpaca-databento-secret-sync-20261017`; started 2026-10-17T21:59:16.458234+08:00 (Asia/Shanghai). Status: in progress; advisory reservation active. User restored Databento in Tau’s private `.env` and explicitly requested updating GitHub. Root owns the three encrypted repository secrets `APCA_API_KEY_ID`, `APCA_API_SECRET_KEY`, `DATABENTO_API_KEY` and narrow handoff/PLAN/MVP/README/operator-guide updates. Preserve the earlier Massive/Exa secret values, all private file bytes/modes, provider activation/trading settings and runtime source. No provider/paid calls, workflow execution, AWS write, deployment or service restart. Values pass only through stdin to client-side-encrypting GitHub CLI; never into Git, command arguments or evidence.

### Four-provider GitHub secret coverage verified

The user-restored Databento value is present in Tau’s private `.env`. Explicitly synchronized `APCA_API_KEY_ID`, `APCA_API_SECRET_KEY` and `DATABENTO_API_KEY` using client-side encryption and stdin; all three commands succeeded. All three entries existed by the immediate pre-upload metadata read and were updated under the user’s explicit sync instruction. `PROVIDER_UPLOAD_RECEIPT.json` retains actual create/update timestamps.

The post-upload metadata lists five fields across all four providers. Massive/Exa timestamps are unchanged; target private bytes/mode are unchanged. No secret value is in evidence/arguments/Git. Values cannot be downloaded/read back through GitHub metadata, so this verifies storage success and names, not provider authentication. No runtime code, deployment workflow, AWS/SSM/service, provider/paid call or trading flag was changed.

PLAN/MVP now resolve the local Databento restoration gate while preserving actual worker/accounting/production gates. README/operator guide list all five GitHub fields and the Actions environment snippet. The guide explicitly states the unchanged AWS loader does not load Alpaca credentials; a deployment owner must configure that runtime injection separately. Public Dev Log rollout entries remain planned because credential storage is not production feature availability. Final source/secret/links/regression verification follows in `PROVIDER_SYNC_VERIFICATION.json`; advisory reservation released.

Final verification for the three-secret sync: **878 infrastructure tests passed / 9 skipped (7.17s)** with all providers/opt-in MySQL disabled and AWS metadata disabled. Independent read-only guide review found no concrete error. The eight selected documentation/metadata files pass known-private-value and relative-link checks; private `.env` remains ignored, untracked and mode0600. Runtime source is unchanged. Only public-safe records are included in the GitHub documentation update; actual keys remain exclusively in private local configuration and encrypted GitHub storage.
