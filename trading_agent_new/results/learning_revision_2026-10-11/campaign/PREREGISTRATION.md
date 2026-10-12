# Revised verified-memory evaluation

Frozen before new model results.

Plan: dcf4e8a36449bbb58f5d3fc32dcb8dd85b6941bfc08e3be6a643d8f062728389
Suite: 8a47f95633398985fbd26df6553343fffc78a1e94f5a0547e3739e282bfeb67e
Model: grok-4.20-0309-non-reasoning

40 new synthetic tasks across eight research families; three conditions, two repetitions, 240 calls. All conditions receive the same explicit schemas, units and enums. Verified memory is ranked by task relevance; raw context contains unranked chunks of the same underlying research evidence. Both are bounded to 4,000 bytes. The model, frozen memory/context, source hashes, ordering seed, 700-output-token limit and grader are pinned.

Unchanged acceptance: +10 percentage points vs no learning, +5 vs raw context, positive paired task-bootstrap 95% lower bound, and zero hard failures. Exact schema failures remain failures; separate semantic diagnostics cannot override the gates. A full 240-episode campaign is required; partial consumption retires this plan.

This is a new evaluation design. Do not compare absolute scores to the retired original study as a learning gain. It measures structured task performance, not investment alpha or open-ended discovery. No broker authority.
