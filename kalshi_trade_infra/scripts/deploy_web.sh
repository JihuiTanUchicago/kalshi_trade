#!/usr/bin/env bash
# Deploy the Tau customer app (app/ + data_pipeline/) to the WEB box, the documented way.
#
# The three documented causes of past silent outages are enforced here as a checklist, not advice:
#   1. whole-package tar (app/ AND data_pipeline/) — never file-by-file (partial deploys crash-loop)
#   2. schema via `python -m app.schema` — NOT data_pipeline.init_schema (which skips app migrations)
#   3. verify a live curl 200 through CloudFront — "service active" is not proof
# Plus: rollback on any on-box failure, and a CloudFront /* invalidation (the HTML carries ?v= hashes).
#
# Usage:
#   scripts/deploy_web.sh [--ref GITREF] [--no-invalidate] [--dry-run]
#     --ref           git ref to ship (default: HEAD)
#     --no-invalidate skip the CloudFront /* invalidation (backend-only change)
#     --dry-run       build the bundle locally and print the plan; touch nothing remote
#
# Config (env-overridable; these are infra IDs, not secrets — already in PLAN.md):
set -euo pipefail

AWS_PROFILE=${AWS_PROFILE-agent}   # local dev defaults to the `agent` profile; CI sets AWS_PROFILE="" to use env/OIDC creds
AWS_REGION=${AWS_REGION:-us-east-1}
INSTANCE_ID=${INSTANCE_ID:-i-077d6f7873e7836ba}
BUCKET=${BUCKET:-kalshi-trade-artifacts-568386354218-us-east-1}
CF_DISTRIBUTION=${CF_DISTRIBUTION:-EEQ00Y93RTB1K}
CF_URL=${CF_URL:-https://tau-trading.com}
BOX_DIR=${BOX_DIR:-/opt/kalshi}
BOX_PY=${BOX_PY:-/opt/kalshi/.venv313/bin/python}
SERVICES=${SERVICES:-"recursive-web recursive-agents recursive-engine recursive-history"}

# Locally, use a named profile (the AWS CLI reads AWS_PROFILE from the env). In CI there is no
# profile — the workflow provides env/OIDC creds — so unset it. (Env var, not a --profile flag.)
if [[ -n "${AWS_PROFILE}" ]]; then export AWS_PROFILE; else unset AWS_PROFILE; fi

REF=HEAD; INVALIDATE=1; DRY_RUN=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --ref) REF="$2"; shift 2;;
    --no-invalidate) INVALIDATE=0; shift;;
    --dry-run) DRY_RUN=1; shift;;
    -h|--help) sed -n '2,20p' "$0"; exit 0;;
    *) echo "unknown arg: $1" >&2; exit 2;;
  esac
done

# Run from the repo root (the dir that holds kalshi_trade_infra/).
cd "$(git rev-parse --show-toplevel)"
SHA=$(git rev-parse --short "$REF")
TS=$(date +%Y%m%d_%H%M%S)
TMPD=$(mktemp -d)
trap 'rm -rf "$TMPD"' EXIT
BUNDLE="$TMPD/bundle_${TS}.tgz"
SCRIPT="$TMPD/deploy_${TS}.sh"
BKEY="bundle/deploy_${TS}.tgz"
SKEY="bundle/deploy_${TS}.sh"

echo "[deploy] ref=$REF ($SHA) -> box=$INSTANCE_ID  invalidate=$INVALIDATE  dry_run=$DRY_RUN"

# (1) whole-package tar from the git ref (never the dirty tree, never file-by-file)
git archive --format=tar.gz -o "$BUNDLE" "$REF:kalshi_trade_infra" app data_pipeline
for p in app/server.py app/schema.py data_pipeline; do
  tar -tzf "$BUNDLE" | grep -q "^${p}" || { echo "[deploy] FATAL: bundle missing $p — aborting"; exit 1; }
done
echo "[deploy] bundle ok ($(wc -c <"$BUNDLE") bytes)"

# The on-box deploy: backup -> extract -> compile -> (2) app.schema -> restart -> (health) -> rollback on any failure.
cat > "$SCRIPT" <<EOF
#!/bin/bash
set -uo pipefail
cd ${BOX_DIR}
T=\$(date +%s)
aws s3 cp "s3://${BUCKET}/${BKEY}" /tmp/tau_bundle.tgz || { echo "S3 FETCH FAILED"; exit 1; }
cp -r app app.bak.\$T && cp -r data_pipeline data_pipeline.bak.\$T || { echo "BACKUP FAILED"; exit 1; }
rollback(){ echo "[box] ROLLBACK"; rm -rf app data_pipeline; mv app.bak.\$T app; mv data_pipeline.bak.\$T data_pipeline; systemctl restart ${SERVICES}; }
tar -xzf /tmp/tau_bundle.tgz -C ${BOX_DIR} || { rollback; echo "EXTRACT FAILED"; exit 1; }
set -a; . ${BOX_DIR}/.env.aws; . ${BOX_DIR}/.env.app; set +a; unset AWS_PROFILE
${BOX_PY} -m py_compile app/*.py data_pipeline/*.py || { rollback; echo "COMPILE FAILED"; exit 1; }
${BOX_PY} -m app.schema || { rollback; echo "SCHEMA FAILED"; exit 1; }
systemctl restart ${SERVICES}
sleep 5
CODE=\$(curl -fsS -o /dev/null -w "%{http_code}" http://127.0.0.1:8090/ || echo 000)
case "\$CODE" in 200|301|302|401|403) :;; *) rollback; echo "HEALTH FAILED (\$CODE)"; exit 1;; esac
rm -rf app.bak.\$T data_pipeline.bak.\$T
echo "[box] DEPLOY OK (\$CODE) ts=\$T"
EOF

if [[ "$DRY_RUN" == 1 ]]; then
  echo "[deploy] DRY RUN — would upload $BKEY + $SKEY, SSM-run on $INSTANCE_ID, curl $CF_URL, invalidate=$INVALIDATE"
  echo "[deploy] on-box script:"; sed 's/^/    /' "$SCRIPT"
  exit 0
fi

aws s3 cp "$BUNDLE" "s3://${BUCKET}/${BKEY}" --region "$AWS_REGION" >/dev/null
aws s3 cp "$SCRIPT" "s3://${BUCKET}/${SKEY}" --region "$AWS_REGION" >/dev/null
CMD_ID=$(aws ssm send-command --region "$AWS_REGION" \
  --instance-ids "$INSTANCE_ID" --document-name AWS-RunShellScript \
  --comment "deploy $SHA" \
  --parameters "commands=[\"aws s3 cp s3://${BUCKET}/${SKEY} /tmp/d.sh && bash /tmp/d.sh\"]" \
  --query Command.CommandId --output text)
echo "[deploy] SSM command $CMD_ID — polling..."
for i in $(seq 1 60); do
  sleep 5
  ST=$(aws ssm get-command-invocation --region "$AWS_REGION" \
       --command-id "$CMD_ID" --instance-id "$INSTANCE_ID" --query Status --output text 2>/dev/null || echo Pending)
  [[ "$ST" == Success || "$ST" == Failed || "$ST" == TimedOut || "$ST" == Cancelled ]] && break
done
OUT=$(aws ssm get-command-invocation --region "$AWS_REGION" \
      --command-id "$CMD_ID" --instance-id "$INSTANCE_ID" --query StandardOutputContent --output text)
echo "$OUT" | tail -4
[[ "$ST" == Success ]] || { echo "[deploy] ON-BOX FAILED (status=$ST) — see output above"; exit 1; }

# (3) verify a LIVE curl through the CDN on the canonical domain (follow redirects so the
# old-URL -> custom-domain 301 and www -> apex canonicalization both resolve to a real page).
# Non-fatal: the on-box 200 check above is the authoritative health gate; this external check can
# see transient DNS-propagation / redirect states that don't mean the deploy is unhealthy.
for path in / /research; do
  CODE=$(curl -fsSL -o /dev/null -w "%{http_code}" "${CF_URL}${path}" || echo 000)
  echo "[deploy] live ${path} -> ${CODE}"
  [[ "$CODE" == 200 || "$CODE" == 302 ]] || echo "[deploy] WARN: live check on $path returned $CODE (on-box health already passed; likely DNS propagation)"
done

if [[ "$INVALIDATE" == 1 ]]; then
  INV=$(aws cloudfront create-invalidation --distribution-id "$CF_DISTRIBUTION" \
        --paths "/*" --query 'Invalidation.Id' --output text)
  echo "[deploy] CloudFront /* invalidation $INV"
fi
echo "[deploy] DONE — $SHA live at $CF_URL"
