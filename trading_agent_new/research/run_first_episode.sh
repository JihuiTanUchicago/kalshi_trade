#!/usr/bin/env bash
# Provider-neutral first-episode sequence. Defaults use the user's chosen Grok
# configuration; change the configuration/env-file arguments for another route.
# Never source a credential file or echo credentials.
set -euo pipefail
task_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd -- "$task_root"
task_model_config="${1:-config/grok.local.json}"
task_model_env="${2:-.env}"
task_dataset="${3:-data/agent_imports/alpaca_proxy_20261010}"
source sandbox/environment.sh

# Validate and bind the exact import before any paid model request.
task_episode_run="$(.agent-venv/bin/quant-agent first-episode prepare --dataset "$task_dataset" |
  .agent-venv/bin/python -c 'import json,sys; print(json.load(sys.stdin)["run"])')"
task_sandbox_image="$(.agent-venv/bin/python -c 'import json; print(json.load(open("sandbox/image.lock.json"))["image_id"])')"

# Every command shares .quant-agent's durable $50 aggregate validation cap.
# Once both smoke cases pass, their receipts are reused on resume.
if ! .agent-venv/bin/python - "$task_model_config" <<'PY'
import json, sys
from quant_agent.common import GateError
from quant_agent.first_episode import require_smokes
from quant_agent.store import Store
store = Store('.quant-agent')
try:
    require_smokes(store, json.loads(open(sys.argv[1]).read()))
except GateError:
    sys.exit(2)
finally:
    store.close()
PY
then
  .agent-venv/bin/quant-agent --model-env "$task_model_env" model-smoke --model-config "$task_model_config" --case json
  .agent-venv/bin/quant-agent --model-env "$task_model_env" model-smoke --model-config "$task_model_config" --case workflow
fi

.agent-venv/bin/quant-agent --model-env "$task_model_env" first-episode run \
  --run "$task_episode_run" --dataset "$task_dataset" --model-config "$task_model_config" --image "$task_sandbox_image"
.agent-venv/bin/quant-agent --model-env "$task_model_env" first-episode transfer \
  --run "$task_episode_run" --model-config "$task_model_config"
.agent-venv/bin/quant-agent --model-env "$task_model_env" first-episode benchmark \
  --run "$task_episode_run" --model-config "$task_model_config"
.agent-venv/bin/quant-agent first-episode paper-gate --run "$task_episode_run"
# Broker setup/acceptance remains a separate operation after all gates pass.
