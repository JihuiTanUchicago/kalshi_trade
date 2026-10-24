#!/usr/bin/env bash
# Run scripts/prune_untraded_markets.py on the WEB box from a git ref, without a web deploy
# (deploy_web.sh ships app/ + data_pipeline/ only). Used by .github/workflows/prune-untraded.yml.
#
# Usage:
#   scripts/run_prune_on_web.sh --ref GITREF --mode dry-run|apply|drop-old [--stop-at HH:MM]
#     dry-run   counts only, writes nothing
#     apply     --apply --rebuild-markets (old markets kept as markets__untraded_old)
#     drop-old  --drop-old-only (drops markets__untraded_old after checking curated series)
#
# The ref's prune script + data_pipeline/ are extracted to /tmp/prune-<sha> on the box and run
# ahead of /opt/kalshi on PYTHONPATH, with the box's own env files. Full log: /tmp/prune-<sha>/<mode>.log
set -euo pipefail

AWS_PROFILE=${AWS_PROFILE-agent}
AWS_REGION=${AWS_REGION:-us-east-1}
INSTANCE_ID=${INSTANCE_ID:-i-077d6f7873e7836ba}
BUCKET=${BUCKET:-kalshi-trade-artifacts-568386354218-us-east-1}
BOX_DIR=${BOX_DIR:-/opt/kalshi}
BOX_PY=${BOX_PY:-/opt/kalshi/.venv313/bin/python}
REF=HEAD; MODE=""; STOP_AT=23:45
while [[ $# -gt 0 ]]; do
  case "$1" in
    --ref) REF=$2; shift 2 ;;
    --mode) MODE=$2; shift 2 ;;
    --stop-at) STOP_AT=$2; shift 2 ;;
    *) echo "unknown arg $1"; exit 2 ;;
  esac
done
case "$MODE" in
  dry-run) ARGS="" ;;
  apply) ARGS="--apply --rebuild-markets --stop-at $STOP_AT" ;;
  drop-old) ARGS="--drop-old-only" ;;
  *) echo "--mode must be dry-run, apply or drop-old"; exit 2 ;;
esac
[[ "$STOP_AT" =~ ^[0-9]{2}:[0-9]{2}$ ]] || { echo "--stop-at must be HH:MM"; exit 2; }

ROOT=$(git rev-parse --show-toplevel)
SHA=$(git -C "$ROOT" rev-parse --short "$REF")
TMP=$(mktemp -d)
git -C "$ROOT" archive --format=tar.gz -o "$TMP/prune.tgz" "$SHA" \
  kalshi_trade_infra/scripts/prune_untraded_markets.py kalshi_trade_infra/data_pipeline
DIR=/tmp/prune-$SHA
cat > "$TMP/run.sh" <<SH
set -euo pipefail
rm -rf $DIR && mkdir -p $DIR && cd $DIR
aws s3 cp s3://${BUCKET}/bundle/prune-${SHA}.tgz prune.tgz >/dev/null
tar xzf prune.tgz --strip-components=1
touch scripts/__init__.py
set -a; . ${BOX_DIR}/.env.aws; [ -f ${BOX_DIR}/.env ] && . ${BOX_DIR}/.env; set +a
unset AWS_PROFILE
export PYTHONPATH=${BOX_DIR}
echo "[prune-run] ref=$SHA mode=$MODE start=\$(date -u +%FT%TZ)"
set +e
${BOX_PY} -u -m scripts.prune_untraded_markets $ARGS > $DIR/$MODE.log 2>&1
RC=\$?
set -e
tail -c 20000 $DIR/$MODE.log
echo "[prune-run] exit=\$RC end=\$(date -u +%FT%TZ)"
exit \$RC
SH

aws s3 cp "$TMP/prune.tgz" "s3://${BUCKET}/bundle/prune-${SHA}.tgz" --region "$AWS_REGION" >/dev/null
aws s3 cp "$TMP/run.sh" "s3://${BUCKET}/bundle/prune-${SHA}-${MODE}.sh" --region "$AWS_REGION" >/dev/null
CMD_ID=$(aws ssm send-command --region "$AWS_REGION" \
  --instance-ids "$INSTANCE_ID" --document-name AWS-RunShellScript \
  --comment "prune $MODE $SHA" \
  --parameters "commands=[\"aws s3 cp s3://${BUCKET}/bundle/prune-${SHA}-${MODE}.sh /tmp/prune-run.sh && bash /tmp/prune-run.sh\"],executionTimeout=[\"14400\"]" \
  --query Command.CommandId --output text)
echo "[prune] ref=$SHA mode=$MODE box=$INSTANCE_ID SSM command $CMD_ID; polling (log on box: $DIR/$MODE.log)"
ST=Pending
for i in $(seq 1 1500); do
  sleep 10
  ST=$(aws ssm get-command-invocation --region "$AWS_REGION" \
       --command-id "$CMD_ID" --instance-id "$INSTANCE_ID" --query Status --output text 2>/dev/null || echo Pending)
  [[ "$ST" == Success || "$ST" == Failed || "$ST" == TimedOut || "$ST" == Cancelled ]] && break
done
aws ssm get-command-invocation --region "$AWS_REGION" \
  --command-id "$CMD_ID" --instance-id "$INSTANCE_ID" --query StandardOutputContent --output text
ERR=$(aws ssm get-command-invocation --region "$AWS_REGION" \
      --command-id "$CMD_ID" --instance-id "$INSTANCE_ID" --query StandardErrorContent --output text 2>/dev/null || true)
[[ -n "$ERR" ]] && { echo "[prune] --- box stderr ---"; echo "$ERR" | tail -30; }
[[ "$ST" == Success ]] || { echo "[prune] status=$ST"; exit 1; }
