#!/usr/bin/env bash
set -euo pipefail

AWS_PROFILE=${AWS_PROFILE-agent}   # local dev defaults to the `agent` profile; set AWS_PROFILE="" to use env creds (cloud/CI)
# The AWS CLI reads AWS_PROFILE from the env, so an unset profile falls back to env/instance creds.
if [[ -n "${AWS_PROFILE}" ]]; then export AWS_PROFILE; else unset AWS_PROFILE; fi
AWS_REGION=${AWS_REGION:-us-east-1}
ENV_FILE=${ENV_FILE:-.env.aws}
RUN_BACKFILL=${RUN_BACKFILL:-false}

if [[ ! -f "$ENV_FILE" ]]; then
  echo "[ERROR] ${ENV_FILE} missing. Run scripts/provision_rds_mysql.sh first."
  exit 1
fi

source "$ENV_FILE"

mkdir -p logs pids

./.venv/bin/python -m data_pipeline.init_schema > logs/schema.log 2>&1

if [[ "${RUN_BACKFILL}" == "true" ]]; then
  nohup ./.venv/bin/python -m data_pipeline.backfill > logs/backfill.log 2>&1 &
  echo $! > pids/backfill.pid
fi

nohup ./.venv/bin/python -m data_pipeline.forward_collector > logs/forward_collector.log 2>&1 &
echo $! > pids/forward_collector.pid

nohup ./.venv/bin/python -m data_pipeline.coinbase_collector > logs/coinbase_collector.log 2>&1 &
echo $! > pids/coinbase_collector.pid

nohup ./.venv/bin/python -m data_pipeline.feature_1m_collector > logs/feature_1m_collector.log 2>&1 &
echo $! > pids/feature_1m_collector.pid

nohup ./.venv/bin/python -m data_pipeline.model_features_1m_builder > logs/model_features_1m_builder.log 2>&1 &
echo $! > pids/model_features_1m_builder.pid

nohup ./.venv/bin/python -m data_pipeline.simulated_trading_engine > logs/simulated_trading_engine.log 2>&1 &
echo $! > pids/simulated_trading_engine.pid

nohup ./.venv/bin/python -m data_pipeline.sim_portfolio_20s_updater > logs/sim_portfolio_20s_updater.log 2>&1 &
echo $! > pids/sim_portfolio_20s_updater.pid

nohup ./.venv/bin/python -m data_pipeline.live_trading_engine > logs/live_trading_engine.log 2>&1 &
echo $! > pids/live_trading_engine.pid

nohup ./.venv/bin/python -m data_pipeline.live_portfolio_20s_updater > logs/live_portfolio_20s_updater.log 2>&1 &
echo $! > pids/live_portfolio_20s_updater.pid

nohup ./.venv/bin/python -m data_pipeline.dashboard_server > logs/dashboard.log 2>&1 &
echo $! > pids/dashboard.pid

echo "[INFO] Started jobs"
if [[ -f pids/backfill.pid ]]; then
  cat pids/backfill.pid pids/forward_collector.pid pids/coinbase_collector.pid pids/feature_1m_collector.pid pids/model_features_1m_builder.pid pids/simulated_trading_engine.pid pids/sim_portfolio_20s_updater.pid pids/live_trading_engine.pid pids/live_portfolio_20s_updater.pid pids/dashboard.pid | nl -ba
else
  cat pids/forward_collector.pid pids/coinbase_collector.pid pids/feature_1m_collector.pid pids/model_features_1m_builder.pid pids/simulated_trading_engine.pid pids/sim_portfolio_20s_updater.pid pids/live_trading_engine.pid pids/live_portfolio_20s_updater.pid pids/dashboard.pid | nl -ba
fi
