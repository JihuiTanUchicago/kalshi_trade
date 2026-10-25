#!/usr/bin/env bash
# Deploy data_pipeline/ to the COLLECTOR box (tau-collector), the counterpart of deploy_web.sh.
#
# The collector box runs only data_pipeline modules (forward/coinbase/feature collectors, the
# feature builder, the sim engine, snapshots, watchdog, and the catalog/alerter timers); none of
# them import app/. Same rules as the web deploy: whole-package tar from a git ref (never
# file-by-file), compile before restart, and roll back if any restarted unit fails to stay up.
# Timers (tau-catalog, kalshi-alerter) pick the new code up on their next run. Disabled units
# (kalshi-live-engine) are never started by this script.
#
# Usage:
#   scripts/deploy_collector.sh [--ref GITREF] [--dry-run]
set -euo pipefail

AWS_PROFILE=${AWS_PROFILE-agent}   # local dev defaults to the `agent` profile; CI sets AWS_PROFILE="" to use env creds
AWS_REGION=${AWS_REGION:-us-east-1}
INSTANCE_ID=${INSTANCE_ID:-i-0bd0683cc7e86243d}
BUCKET=${BUCKET:-kalshi-trade-artifacts-568386354218-us-east-1}
BOX_DIR=${BOX_DIR:-/opt/kalshi}
BOX_PY=${BOX_PY:-/opt/kalshi/.venv313/bin/python}
SERVICES=${SERVICES:-"kalshi-forward-collector kalshi-coinbase-collector kalshi-feature-1m kalshi-feature-builder kalshi-sim-engine tau-snapshot kalshi-tick-recorder coinbase-tick-recorder spot-tick-recorder deribit-options-recorder polymarket-recorder"}
# Unit files this script owns on the box: copied from scripts/systemd when they differ, then
# enabled. Timers are enabled --now; services start with the SERVICES restart below.
UNITS=${UNITS:-"kalshi-tick-recorder.service coinbase-tick-recorder.service spot-tick-recorder.service deribit-options-recorder.service polymarket-recorder.service kalshi-tick-archiver.service kalshi-tick-archiver.timer"}

if [[ -n "${AWS_PROFILE}" ]]; then export AWS_PROFILE; else unset AWS_PROFILE; fi

REF=HEAD; DRY_RUN=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --ref) REF="$2"; shift 2;;
    --dry-run) DRY_RUN=1; shift;;
    -h|--help) sed -n '2,13p' "$0"; exit 0;;
    *) echo "unknown arg: $1" >&2; exit 2;;
  esac
done

cd "$(git rev-parse --show-toplevel)"
SHA=$(git rev-parse --short "$REF")
TS=$(date +%Y%m%d_%H%M%S)
TMPD=$(mktemp -d)
trap 'rm -rf "$TMPD"' EXIT
BUNDLE="$TMPD/collector_${TS}.tgz"
SCRIPT="$TMPD/deploy_collector_${TS}.sh"
BKEY="bundle/collector_${TS}.tgz"
SKEY="bundle/deploy_collector_${TS}.sh"

echo "[deploy-collector] ref=$REF ($SHA) -> box=$INSTANCE_ID  dry_run=$DRY_RUN"

UNIT_PATHS=""; for u in $UNITS; do UNIT_PATHS="$UNIT_PATHS scripts/systemd/$u"; done
git archive --format=tar.gz -o "$BUNDLE" "$REF:kalshi_trade_infra" data_pipeline trading_core $UNIT_PATHS
CONTENTS="$TMPD/bundle.contents"
tar -tzf "$BUNDLE" > "$CONTENTS"
for p in data_pipeline/forward_collector.py data_pipeline/common.py trading_core/__init__.py; do
  grep -Fxq -- "$p" "$CONTENTS" || { echo "[deploy-collector] FATAL: bundle missing $p, aborting"; exit 1; }
done
echo "[deploy-collector] bundle ok ($(wc -c <"$BUNDLE") bytes)"

# On-box: backup -> extract -> compile -> restart -> every unit still active after 15s -> else rollback.
# Extracting over the old tree keeps box-only files (one-off research scripts) in place.
cat > "$SCRIPT" <<EOF
#!/bin/bash
set -uo pipefail
cd ${BOX_DIR}
T=\$(date +%s)
aws s3 cp "s3://${BUCKET}/${BKEY}" /tmp/collector_bundle.tgz || { echo "S3 FETCH FAILED"; exit 1; }
# trading_core/ (ARCHITECTURE.md) may import nothing from data_pipeline, but data_pipeline may import it,
# so it ships here too. New at its first deploy: mkdir -p gives it an empty backup to roll back to.
mkdir -p trading_core
cp -r data_pipeline data_pipeline.bak.\$T && cp -r trading_core trading_core.bak.\$T || { echo "BACKUP FAILED"; exit 1; }
rollback(){ echo "[box] ROLLBACK"; rm -rf data_pipeline trading_core; mv data_pipeline.bak.\$T data_pipeline; mv trading_core.bak.\$T trading_core; systemctl restart ${SERVICES}; }
tar -xzf /tmp/collector_bundle.tgz -C ${BOX_DIR} || { rollback; echo "EXTRACT FAILED"; exit 1; }
${BOX_PY} -m py_compile data_pipeline/*.py trading_core/*.py trading_core/*/*.py 2>&1 || { rollback; echo "COMPILE FAILED"; exit 1; }
mkdir -p ${BOX_DIR}/logs ${BOX_DIR}/ticks
RELOAD=0
for u in ${UNITS}; do
  cmp -s scripts/systemd/\$u /etc/systemd/system/\$u || { cp scripts/systemd/\$u /etc/systemd/system/\$u; RELOAD=1; echo "[box] installed unit \$u"; }
done
[ "\$RELOAD" = 1 ] && systemctl daemon-reload
for u in ${UNITS}; do
  case "\$u" in
    *.timer) systemctl enable --now "\$u" ;;
    *.service) grep -q '^WantedBy' scripts/systemd/\$u && systemctl enable "\$u" ;;
  esac
done
systemctl restart ${SERVICES}
sleep 15
DOWN=""
for s in ${SERVICES}; do systemctl is-active --quiet "\$s" || DOWN="\$DOWN \$s"; done
if [ -n "\$DOWN" ]; then
  for s in \$DOWN; do journalctl -u "\$s" -n 20 --no-pager 2>&1; done
  rollback; echo "HEALTH FAILED:\$DOWN"; exit 1
fi
rm -rf data_pipeline.bak.\$T trading_core.bak.\$T
echo "[box] DEPLOY OK ts=\$T"
EOF

if [[ "$DRY_RUN" == 1 ]]; then
  echo "[deploy-collector] DRY RUN: would upload $BKEY + $SKEY and SSM-run on $INSTANCE_ID"
  echo "[deploy-collector] on-box script:"; sed 's/^/    /' "$SCRIPT"
  exit 0
fi

aws s3 cp "$BUNDLE" "s3://${BUCKET}/${BKEY}" --region "$AWS_REGION" >/dev/null
aws s3 cp "$SCRIPT" "s3://${BUCKET}/${SKEY}" --region "$AWS_REGION" >/dev/null
CMD_ID=$(aws ssm send-command --region "$AWS_REGION" \
  --instance-ids "$INSTANCE_ID" --document-name AWS-RunShellScript \
  --comment "deploy-collector $SHA" \
  --parameters "commands=[\"aws s3 cp s3://${BUCKET}/${SKEY} /tmp/dc.sh && bash /tmp/dc.sh\"]" \
  --query Command.CommandId --output text)
echo "[deploy-collector] SSM command $CMD_ID, polling..."
for i in $(seq 1 60); do
  sleep 5
  ST=$(aws ssm get-command-invocation --region "$AWS_REGION" \
       --command-id "$CMD_ID" --instance-id "$INSTANCE_ID" --query Status --output text 2>/dev/null || echo Pending)
  [[ "$ST" == Success || "$ST" == Failed || "$ST" == TimedOut || "$ST" == Cancelled ]] && break
done
OUT=$(aws ssm get-command-invocation --region "$AWS_REGION" \
      --command-id "$CMD_ID" --instance-id "$INSTANCE_ID" --query StandardOutputContent --output text)
if [[ "$ST" == Success ]]; then
  echo "$OUT" | tail -4
else
  ERR=$(aws ssm get-command-invocation --region "$AWS_REGION" \
        --command-id "$CMD_ID" --instance-id "$INSTANCE_ID" --query StandardErrorContent --output text 2>/dev/null || true)
  echo "$OUT" | tail -40
  [[ -n "$ERR" ]] && { echo "[deploy-collector] --- box stderr ---"; echo "$ERR" | tail -30; }
  echo "[deploy-collector] ON-BOX FAILED (status=$ST)"; exit 1
fi
echo "[deploy-collector] DONE: $SHA on $INSTANCE_ID"
