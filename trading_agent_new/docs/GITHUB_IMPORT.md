# Polygon import into kalshi_trade

This project is imported as the standalone `trading_agent_new/` directory in the private `JihuiTanUchicago/kalshi_trade` repository. The local `main` checkout contains the merged [PR #3](https://github.com/JihuiTanUchicago/kalshi_trade/pull/3), at merge commit `4151c5e`. The import itself preserved the Kalshi application files without integration or deployment. October 13 adds the [read-only BTC feed interface](../README.md#read-kalshi-and-coinbase-btc-feeds) in the merged Polygon package; authenticated live feed verification still requires locally configured dashboard credentials.

The import includes source, tests, research scripts, configuration templates, datasets, archived experiment outputs and validation records. Initial inventory: 631 files and 84,820,149 bytes. Import notes and verification records are added separately. Original code/data/archive bytes and CSV line endings are preserved.

Existing ignore rules exclude the private `.env`, `config/*.local.json`, `.venv/`, `.agent-venv/`, `.runtime/`, `.quant-agent/`, caches, bytecode and package metadata. The public `.env.example` is included explicitly despite the destination repository's broader environment-file ignore rule. No credentials are published.

## Work from the copied package

Run project commands inside `trading_agent_new/`, rather than the repository root. Core installation requires Python 3.12 or newer:

```bash
cd trading_agent_new
python3.12 -m venv .agent-venv
.agent-venv/bin/python -m pip install -e .
.agent-venv/bin/quant-agent doctor
```

Restore optional dependencies and the Docker runtime using the package README before their relevant checks. The import regression used the original local Python environment, including the official IBKR SDK; that environment is not bundled. It tested imports from the copied source and passed 122 tests, with 15 container-dependent tests skipped. It made no model, data-provider or broker requests.

Configure private credentials locally from `.env.example`, and copy the relevant public configuration example to an ignored `config/*.local.json`. Existing secrets and source-machine paths are not automatic configuration for a new checkout.

The live SQLite/evidence store and its persistent budget ledger remain private and are not in Git. Historical authentic-state audits need that original state restored locally under the documented rights and original caps. Exported reports remain evidence of the original run; they do not reconstruct its complete database. Do not represent already published benchmark cases as unseen evaluation inputs. Original absolute paths in archived provenance are historical records and are not rewritten.

## Verification and review

[Import manifest](../results/github_import_2026-10-12/IMPORT_MANIFEST.json) records original-file hashes and exclusions. Its immutable inventory omits the evolving progress tracker and newly generated import records, so review/publication updates do not rewrite numerical evidence. [Handoff](../results/github_import_2026-10-12/HANDOFF.md) records checks and publication state. The canonical project tracker remains [PROGRESS.md](PROGRESS.md).

Data remains an exploratory proxy. The reference strategy and measured-learning gates retain their prior failed outcomes; licensed-data, self-improvement and broker acceptance remain pending. Copying the package does not alter those gates.
