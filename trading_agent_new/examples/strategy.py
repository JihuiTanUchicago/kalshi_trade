"""A simple generated-strategy API example. No investment-performance claim."""


def target_weights(context, state):
    weights = {}
    count = len(context["universe"])
    cap = min(context["limits"]["position"],0.95/max(1,count))
    for security in context["universe"]:
        asset = security["asset_id"]
        history = context["history"][asset]
        total = 1.0
        for previous,current in zip(history,history[1:]):
            total *= (current["close"]+current["dividend"])*current["split"]/previous["close"]
        weights[asset] = cap if total>1 else 0.0
    return {"weights":weights,"state":{}}
