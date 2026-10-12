"""Installed inside the image. Only a single as-of context arrives at a time."""
import importlib.util
import json
import random
import sys

random.seed(0)
try:
    import numpy as np
    np.random.seed(0)
except ImportError:
    pass
spec = importlib.util.spec_from_file_location("candidate", "/strategy.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
if not callable(getattr(module, "target_weights", None)):
    raise ValueError("Strategy must define target_weights(context, state)")
state = {}
first = True
for line in sys.stdin:
    if len(line) > 2_000_000:
        raise ValueError("Input quota exceeded")
    message = json.loads(line)
    context = message["context"]
    if first:
        state = message.get("initial_state",{})
        first = False
    result = module.target_weights(context, state)
    if not isinstance(result, dict) or set(result) != {"weights", "state"}:
        raise ValueError("Expected weights and JSON state")
    state = result["state"]
    print(json.dumps(result, allow_nan=False, separators=(",", ":")), flush=True)
