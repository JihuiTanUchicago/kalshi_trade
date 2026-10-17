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
