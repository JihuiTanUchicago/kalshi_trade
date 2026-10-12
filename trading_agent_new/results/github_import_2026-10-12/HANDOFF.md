# GitHub import handoff

Status: copied and offline verified; branch publication and review PR in progress.

Destination: `JihuiTanUchicago/kalshi_trade`, new `trading_agent_new/` folder. User-requested branch: `jonathan-20261012`; PR base: `main`. Initial base: `217d755983ba9943d65bc41cac9cf80a70cee51d`. The existing Kalshi application and root files are outside this workstream.

The initial copy contains 631 project files (84,820,149 bytes), including all exportable code, data and research evidence. Additional files describe this import and its verification. Private environment/configuration files, installed environments, VM/tool directories, caches and the mutable agent database are excluded using the project's existing ignore rules. `.env.example` is retained as a public template.

Verification: zero initial SHA-256 mismatches, no matches for three live credential values or common private-key/token patterns, largest file 2,484,691 bytes. The copied package resolves its own module path. `PYTHONPATH=src:tests /Users/jonathanzhang/Desktop/Polygon/.agent-venv/bin/python -m unittest discover -s tests -v` runs 137 tests: 122 pass, 15 Docker-dependent checks skip. The existing local environment supplies the IBKR SDK; no environment or credentials are bundled. [Regression log](offline_regression.log) and [initial copy verification](INITIAL_COPY_VERIFICATION.json) retain the checks.

The initial generic Git whitespace check treated CSV CRLF endings as trailing whitespace. Recognizing CRLF removes those notices and leaves five pre-existing blank-at-EOF notices. Original files are not normalized, preserving dataset and archived-specification hashes. New metadata is separate from frozen research artifacts.

The immutable import inventory preserves original source/data/evidence hashes; `docs/PROGRESS.md` and new import records are intentionally mutable documentation. Historical manifests are not rewritten. The private live state is absent, so reproducing authentic-state audits requires the original private state and budget ledger. Numerical outcomes and qualification/broker gates are unchanged.

Next: verify all staged paths/blobs, commit and push the requested branch, open a ready-for-review PR against main, verify remote SHA/file scope and attach the PR to this chat. No merge, deployment, runtime integration, paid service call or broker operation is performed.

Setup and scope: [GITHUB_IMPORT.md](../../docs/GITHUB_IMPORT.md). Canonical tracker: [PROGRESS.md](../../docs/PROGRESS.md).
