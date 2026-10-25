#!/usr/bin/env bash
# Ship whatever main has merged since the last deploy: the :20/:50 batch, run by
# .github/workflows/batch-deploy.yml so it doesn't depend on any Claude session staying alive.
#
# Each run:
#   1. reads the S3 markers deploy_web.sh / deploy_collector.sh write (bundle/markers/*)
#   2. nothing new on main -> exit 0
#   3. CI (test, money-path-mysql, isolated-staging) must be green on main's head; pending -> wait
#      for the next batch, red -> fail (GitHub mails the repo owner)
#   4. a diff that only touches the UI/tests/docs restarts recursive-web alone; anything else is a
#      full restart, which first requires 0 sent order intents (a restart mid-send loses the ack)
#   5. deploy_collector.sh too when data_pipeline/ or trading_core/ changed since the collector's ref
#   6. alarm: fails the run when merges on main have waited longer than STALE_MINUTES to ship
#
# Usage: scripts/batch_deploy.sh [--dry-run]   (needs AWS creds, GITHUB_TOKEN and GITHUB_REPOSITORY)
set -euo pipefail

AWS_REGION=${AWS_REGION:-us-east-1}
BUCKET=${BUCKET:-kalshi-trade-artifacts-568386354218-us-east-1}
WEB_INSTANCE=${WEB_INSTANCE:-i-077d6f7873e7836ba}
BOX_PY=${BOX_PY:-/opt/kalshi/.venv313/bin/python}
REQUIRED_CHECKS=${REQUIRED_CHECKS-"test money-path-mysql isolated-staging"}
STALE_MINUTES=${STALE_MINUTES:-90}
DRY_RUN=0
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=1
if [[ -n "${AWS_PROFILE:-}" ]]; then export AWS_PROFILE; else unset AWS_PROFILE; fi

cd "$(git rev-parse --show-toplevel)"
MAIN=$(git rev-parse HEAD)
marker() { aws s3 cp "s3://${BUCKET}/bundle/markers/$1" - --region "$AWS_REGION" 2>/dev/null | tr -d '[:space:]' || true; }
WEB=$(marker web_sha); WEB_FULL=$(marker web_full_sha); COLLECTOR=$(marker collector_sha)
echo "[batch] main=${MAIN:0:7} web=${WEB:0:7} web_full=${WEB_FULL:0:7} collector=${COLLECTOR:0:7}"

known() { [[ -n "$1" ]] && git cat-file -e "$1^{commit}" 2>/dev/null; }
changed() {  # files changed between a marker and main; an unknown marker means everything
  if known "$1"; then git diff --name-only "$1" "$MAIN"; else git ls-files; fi
}
WEB_FILES=$(changed "$WEB_FULL")
COLLECTOR_FILES=$(changed "$COLLECTOR" | grep -E '^kalshi_trade_infra/(data_pipeline|trading_core)/' || true)
NEED_WEB=0; [[ "$WEB" != "$MAIN" ]] && NEED_WEB=1
NEED_COLLECTOR=0; [[ -n "$COLLECTOR_FILES" ]] && NEED_COLLECTOR=1

# Oldest commit on main that the web box doesn't run yet, for the staleness alarm.
stale_minutes() {
  local base="$WEB" oldest
  known "$base" || { echo 0; return; }
  oldest=$(git log --reverse --format=%ct "$base..$MAIN" | head -1)
  [[ -z "$oldest" ]] && { echo 0; return; }
  echo $(( ( $(date +%s) - oldest ) / 60 ))
}
alarm_if_stale() {
  local m; m=$(stale_minutes)
  if (( m > STALE_MINUTES )); then
    echo "::error::main has waited ${m} minutes to ship (limit ${STALE_MINUTES}): $1"; exit 1
  fi
  echo "[batch] holding: $1 (oldest unshipped merge is ${m} min old)"; exit 0
}

if [[ "$NEED_WEB" == 0 && "$NEED_COLLECTOR" == 0 ]]; then
  echo "[batch] nothing new on main"; exit 0
fi

# CI on main's head: every required check completed and successful.
API="https://api.github.com/repos/${GITHUB_REPOSITORY}/commits/${MAIN}/check-runs?per_page=100"
RUNS='{"check_runs": []}'
[[ -n "$REQUIRED_CHECKS" ]] && RUNS=$(curl -fsS -H "Authorization: Bearer ${GITHUB_TOKEN}" -H "Accept: application/vnd.github+json" "$API")
for check in $REQUIRED_CHECKS; do
  state=$(echo "$RUNS" | python3 -c '
import json, sys
runs = [r for r in json.load(sys.stdin)["check_runs"] if r["name"] == sys.argv[1]]
r = max(runs, key=lambda r: r["id"]) if runs else None
print("missing" if r is None else (r["conclusion"] or r["status"]))' "$check")
  case "$state" in
    success) ;;
    queued|in_progress|pending|missing|requested|waiting) alarm_if_stale "CI check $check is $state on ${MAIN:0:7}";;
    *) echo "::error::CI check $check is $state on ${MAIN:0:7}; not deploying"; exit 1;;
  esac
done

UI_ONLY=1
while read -r f; do
  [[ -z "$f" ]] && continue
  [[ "$f" =~ ^kalshi_trade_infra/(app/static|tests)/ || "$f" == *.md ]] || { UI_ONLY=0; break; }
done <<< "$WEB_FILES"
known "$WEB_FULL" || UI_ONLY=0

# Order intents the engine has sent but not yet seen acknowledged, read on the web box itself.
SENT_PY='from data_pipeline.common import get_db_conn
c = get_db_conn().cursor()
c.execute("SELECT COUNT(*) n FROM app_order_intents WHERE status=%s", ("sent",))
print("SENT=%d" % c.fetchone()["n"])'
sent_intents() {
  local params cid st out
  params=$(python3 -c 'import json, sys
cmd = ("cd /opt/kalshi && set -a && . ./.env.aws && . ./.env.app && set +a && unset AWS_PROFILE && "
       "echo %s | base64 -d > /tmp/batch_sent.py && PYTHONPATH=/opt/kalshi timeout 60 %s /tmp/batch_sent.py")
print(json.dumps({"commands": [cmd % (sys.argv[1], sys.argv[2])]}))' "$(printf '%s' "$SENT_PY" | base64 -w0)" "$BOX_PY")
  cid=$(aws ssm send-command --region "$AWS_REGION" --instance-ids "$WEB_INSTANCE" \
    --document-name AWS-RunShellScript --comment "batch: sent intents" \
    --parameters "$params" --query Command.CommandId --output text)
  for _ in $(seq 1 24); do
    sleep 5
    st=$(aws ssm get-command-invocation --region "$AWS_REGION" --command-id "$cid" \
         --instance-id "$WEB_INSTANCE" --query Status --output text 2>/dev/null || echo Pending)
    [[ "$st" == Success || "$st" == Failed || "$st" == TimedOut || "$st" == Cancelled ]] && break
  done
  out=$(aws ssm get-command-invocation --region "$AWS_REGION" --command-id "$cid" \
        --instance-id "$WEB_INSTANCE" --query StandardOutputContent --output text 2>/dev/null || true)
  echo "$out" | sed -n 's/^SENT=\([0-9][0-9]*\)$/\1/p' | tail -1
}

if [[ "$NEED_WEB" == 1 ]]; then
  if [[ "$UI_ONLY" == 1 ]]; then
    export SERVICES="recursive-web"
    echo "[batch] UI-only since ${WEB_FULL:0:7}: restarting recursive-web alone"
  else
    n=$(sent_intents)
    [[ -z "$n" ]] && alarm_if_stale "could not read sent order intents on the web box"
    [[ "$n" != 0 ]] && alarm_if_stale "$n order intents are mid-send; a full restart would orphan them"
    echo "[batch] full restart (0 sent intents)"
  fi
fi

if [[ "$DRY_RUN" == 1 ]]; then
  echo "[batch] DRY RUN: web=$NEED_WEB ui_only=$UI_ONLY collector=$NEED_COLLECTOR"; exit 0
fi
[[ "$NEED_WEB" == 1 ]] && bash kalshi_trade_infra/scripts/deploy_web.sh --ref "$MAIN"
# An empty SERVICES gives deploy_collector.sh its own default, not the web's UI-only override.
[[ "$NEED_COLLECTOR" == 1 ]] && SERVICES= bash kalshi_trade_infra/scripts/deploy_collector.sh --ref "$MAIN"
echo "[batch] shipped ${MAIN:0:7}"
