# Open-Source Readiness Security Audit

**Repo:** `/Users/toddtan/Desktop/kalshi_trade` (git root; app in `kalshi_trade_infra/`, plus a second project `trading_agent_new/`)
**Scope:** working tree + full git history (`--all`, 181 commits)
**Date:** 2026-10-15
**Nature:** read-only analysis. Nothing in git was changed, nothing published.

---

## 1. Verdict

**NO — do not publish the current repo or its history as-is.**

The good news: **no live API key or private key was ever committed** — not in the working tree, not anywhere in the 181-commit history. `.gitignore` did its job (`.env*`, `credentials`, `venv/` are excluded, and no real `.env` was ever committed before being ignored). Every Stripe/Kalshi/AWS credential in the code is an `os.getenv(...)` reference, an SSM parameter *path*, a doc description, or a test stub.

But it is still unsafe to publish because of four separate problems, any one of which is disqualifying:

1. A **real shared default password** (`kalshimakesmepoor`) is hardcoded in client code and present throughout history.
2. **Heavy PII** — the owner's personal Gmail appears ~360 times across history; real contributor names/emails are the git authorship.
3. **Full deployment coordinates** (AWS account id, EC2/CloudFront/RDS/S3/SG/SNS identifiers) are strewn through docs, scripts, and code.
4. **`venv/` (7,527 files) was committed in history** — pure bloat, and it means history can never be made clean by editing current files.

Because the problems live in **history** (PII in 360 commits, the password, the venv), scrubbing current files is not enough. The safe path is a fresh repo with clean/squashed history (Section 4, option c).

---

## 2. Hard blockers

### 2a. Secrets — NONE found (the good case)
Searched working tree and `git log --all -S<pattern>` for: `sk_live`, `sk_test`, `pk_live`, `whsec_`, `BEGIN RSA/EC/PRIVATE KEY`, `PRIVATE KEY`, `AKIA`, `aws_secret_access_key`, `sk-ant-`, `AIza`, `xai-`, `ghp_`, `GOCSPX-`, Google OAuth client ids.

| Apparent hit | Reality | Verdict |
|---|---|---|
| `sk_live_` / `pk_live_` / `whsec_` in `PLAN.md:248-249`, `mvp.md:79` | Describe SSM parameter *names*, not values | Not a secret (but scrub infra doc — §3) |
| `STRIPE_*` in `app/billing.py` | All `os.getenv("STRIPE_*", "")` | Safe |
| `whsec_test` in `tests/test_app_billing.py:31-41` | Test stub string | Safe |
| `BEGIN RSA PRIVATE KEY` in `app/static/app.js` (hist `0a69de9`) | `placeholder=` text in a `<textarea>` | Safe |
| `PRIVATE KEY` / `test.key` in `e31c635`, `4051dee` | `venv/.../tornado/test/test.key` — library file | Safe (but see venv bloat §3) |
| `AKIA` / `aws_secret_access_key` in history | A *negative* sentence in `PLAN.md:10` + venv files | Safe |

**No RSA/PEM Kalshi key, no Stripe live key, no AWS access key, no OAuth secret was ever committed.** Keep it that way.

### 2b. Real credential in code + history — BLOCKER
| Item | Location (current) | History |
|---|---|---|
| Default dashboard Basic-Auth password `kalshimakesmepoor` | `client_api/client.py:72` (default arg), `client_api/README.md:19`, `PLAN.md:507` | Present since `a351337` ("password protect"); in ~12 commits |

This is a **live shared secret** if the deployed dashboard still accepts it. Action: **rotate the dashboard password now** (treat it as burned regardless of publishing), change `client.py` to default to `os.getenv("DASHBOARD_PASSWORD")` with no literal fallback, and ensure the literal is gone from current files *and* excluded from any published history.

### 2c. Apple Pay domain-association file — not secret, but note
`app/static/apple-developer-merchantid-domain-association` is a signed cert chain served publicly at `/.well-known/` by design. Not a private secret, but it ties the repo to a specific Apple Pay merchant. Keep only if the public project actually serves Apple Pay; otherwise drop it.

---

## 3. Infra / PII leak inventory

### Infrastructure coordinates
| Identifier | Value | Appears in | Scrub recommendation |
|---|---|---|---|
| AWS account id | `568386354218` | `PLAN.md:715`, `app/server.py:1002`, `data_pipeline/snapshot_collector.py:49` | Replace with env var / placeholder `<ACCOUNT_ID>`. Already behind `os.getenv("DATALAKE_BUCKET", ...)` in code — just change the default. |
| EC2 instance ids | `i-077d6f7873e7836ba`, `i-0bd0683cc7e86243d` | `PLAN.md:381,410`, `mvp.md:45`, `pids/ec2_instance_id.txt` | Remove; `pids/ec2_instance_id.txt` should not be tracked at all (add to `.gitignore`). |
| CloudFront dist ids | `EEQ00Y93RTB1K`, `E3W0CV5JMD953I` | `PLAN.md:382,384,462,678` | Scrub from docs. |
| CloudFront domains | `d1gfpzcosqrjya.cloudfront.net`, `dehiuraiut9ro.cloudfront.net` | `PLAN.md` (several), `README.md:295`, `client_api/README.md:17`, `client_api/example.ipynb:42`, `data_pipeline/live_alerter.py:43`, `scripts/load_app_secrets.sh:14` | Replace public-doc/example URLs with `https://your-dashboard.example.com`; keep as `os.getenv` default only if generic. |
| RDS instance name | `kalshi-trade-mysql` (+ `-sg`) | `PLAN.md:410`, `scripts/provision_rds_mysql.sh:6,11` | Low severity (name, not endpoint host; real endpoint resolves via secrets). Parameterize in script. |
| S3 buckets | `kalshi-trade-datalake-568386354218-us-east-1`, `kalshi-trade-artifacts-${ACCOUNT}-${REGION}` | `app/server.py:1002`, `snapshot_collector.py:49`, `scripts/deploy_ec2_runner.sh:21` | Already env-driven; change hardcoded default to a placeholder. |
| Security group | `sg-0eb5783d005711504` (`recursive-web-sg`) | `PLAN.md:386` | Scrub from docs. |
| SNS topic ARN | `arn:aws:sns:us-east-1:568386354218:kalshi-live-alerts` | `PLAN.md:715` | Scrub. |

### PII
| Identifier | Count | Where | Scrub recommendation |
|---|---|---|---|
| `tjhprivate0416@gmail.com` (owner) | ~360 in history; current: `PLAN.md`, `app/notify.py:18-19`, `app/server.py:46` | Hardcoded as `ADMIN_EMAIL`/`OPERATOR_EMAIL`/`FROM_EMAIL` **defaults** | Change defaults to `os.getenv(...)` with no personal literal (e.g. `""` or `admin@example.com`). Admin gate is `email == ADMIN_EMAIL`, so this also stops leaking who the admin is. |
| `tjhprivate016@gmail.com` (typo variant) | ~180 in history | docs/history | Same. |
| Contributor git authors | — | history authorship | `tanjihui@uchicago.edu` (112 commits), `jonathan@codestart.tech`, `arushguliani@gmail.com`, `aldrichenghaow`, `Jonathan-Zhang`. Standard for OSS, but a squashed fresh repo (option c) drops them. Get contributor consent if keeping history. |
| Third-party / account data | — | `trading_agent_new/` tests use dummy IBKR account `DU999999` | Not real — safe. |

### Operational docs (decide per file)
| File | Contents | Recommendation |
|---|---|---|
| `kalshi_trade_infra/PLAN.md` (98 KB) | Full internal roadmap, incident post-mortems, box IDs, SNS/CloudFront/SG ids, private strategy, billing/SSM layout | **Exclude** from public repo. Too much leakage to scrub safely; keep private. |
| `mvp.md` (root) | Internal TODO queue, Stripe live-key flip notes, collector box id | **Exclude.** |
| `DESIGN.md`, `PRODUCT.md` | Product/design detail | Review and **scrub** if kept; probably exclude. |
| `AGENTS.md` | Dev guide — references `.env.aws`, SSM, admin passwords by name | **Scrub** infra specifics, or replace with a clean `CONTRIBUTING.md`. |
| `.impeccable/`, `.pytest_cache/` | Session/cache artifacts | Exclude (gitignore the dirs). |
| `trading_agent_new/data/**` | Committed CSV/JSON market data & Alpaca import audits | Decide if this data is yours to redistribute (Alpaca ToS); likely **exclude** from a public kalshi repo — it's a separate project anyway. |

---

## 4. Recommended path to open-source

**Chosen: (c) fresh public repo with clean/squashed history.** Not (a) — not clean. Not (b) — history carries the password, ~360 PII hits, and 7,527 venv files that editing current files cannot remove.

### Exact steps
```bash
# 0. FIRST, out-of-band: rotate the dashboard password (it is burned either way).

# 1. Pick what ships. From a clean checkout of HEAD, keep only kalshi_trade_infra/
#    app + data_pipeline + client_api + research + tests + scripts (sanitized) +
#    requirements.txt + a NEW public README/LICENSE. Exclude PLAN.md, mvp.md,
#    DESIGN.md, PRODUCT.md, AGENTS.md (replace), .impeccable/, pids/, trading_agent_new/.

# 2. Scrub the kept files (Section 3): account id, CloudFront domains/ids, EC2 ids,
#    SNS ARN, SG id, owner email defaults, the hardcoded password default.
#    Verify clean:
grep -rInE '568386354218|i-0[0-9a-f]+|cloudfront\.net|EEQ00Y93RTB1K|E3W0CV5JMD953I|sg-[0-9a-f]+|kalshimakesmepoor|tjhprivate0?16?@' . --exclude-dir=.git
#    (must return nothing)

# 3. Start history from scratch (no old commits travel):
rm -rf .git
git init
git add -A
git commit -m "chore: initial public release"

# 4. Create a brand-new EMPTY GitHub repo and push. Do NOT reuse the private
#    repo's remote (its history stays private). Then enable branch protection, etc.
```
Do **not** attempt `git filter-repo`/BFG on the existing repo and publish that — one missed blob (e.g. the password or an email in a commit message) re-leaks it. A fresh `git init` is simpler and provably clean. Keep the private repo private as the real working history.

Add a secret-scanner to CI before first push (`gitleaks detect` or `trufflehog`) as a backstop.

---

## 5. Proposed LICENSE

This is **live trading alpha with a paid SaaS layer**. The core question is whether you want adoption or want to stop competitors from running your edge.

**Recommendation: Apache-2.0** if the goal is genuine open-source adoption — it adds a patent grant (useful for a trading method) and a `NOTICE` file for required attributions, which this repo needs. One line: *permissive, patent-protective, and its NOTICE mechanism cleanly carries the third-party attributions below.*

**Alternative: PolyForm Noncommercial 1.0.0 or BSL 1.1** if you want the code public for credibility/learning but not legal for a competitor to deploy commercially. One line: *source-available, keeps others from monetizing your live alpha while still being readable.* This is the hedge-fund-mindset choice; pick it if the strategy edge is the asset.

**Attributions required regardless of license** (put in `NOTICE` / README):
- **Dream-RSI** — the Tau-RSI self-evolving research is "Dream-RSI adapted" (`PLAN.md:1319-1321`, `mvp.md:59`): arXiv 2609.14858 (Google/UMD), `github.com/zhengkid/Dream-RSI`. Check that repo's license; if you reused *code* (not just the idea), comply with and reproduce its license/NOTICE.
- **karpathy / autoresearch influence** — if any code derives from a karpathy project (MIT-style), reproduce its copyright line.
- Verify `requirements.txt` deps are all compatible (all common PyPI libs — MySQL/requests/etc. — are permissive; no issue expected).

---

## 6. Draft public README outline

```
# <Project Name>  (drop the "kalshi"/"recursive"/"tau" internal codenames or keep one)

> A research-to-live pipeline for short-horizon binary-options (Kalshi BTC 15-min)
> trading: data ingestion, feature engineering, a simulated trading engine, a
> live execution engine behind a risk layer, and a dashboard.

## What it is
- Collectors (Coinbase spot, Kalshi order book) → MySQL feature store
- Feature builder (1m/forward features)
- Simulated + live trading engines sharing a risk/execution abstraction
  (data_pipeline/architecture/)
- Dashboard for monitoring strategies and promoting sim → live

## Architecture
- diagram: collectors → feature store → engines (sim/live) → dashboard
- diagram: signal flow (order book → features → strategy → risk gate → venue)
  (reuse the signal-flow description from the internal docs, with infra removed)

## Setup
- Python 3.12+, `python -m venv .venv && pip install -r requirements.txt`
- Copy `.env.example` → `.env` and fill: DB creds, Kalshi key material
  (KALSHI_WS_KEY_ID / KALSHI_WS_PRIVATE_KEY_PATH), dashboard password.
  (ship a NEW .env.example listing every var name, NO values)
- `python -m <pkg>.init_schema` to create the schema
- `python -m pytest tests/` (no live DB required — FakeCursor fixture)

## Disclaimer
- Research/educational. Not investment advice. Live trading risks real capital;
  live orders fire only when explicitly enabled.

## License / attribution  (see Section 5)
```
Keep it generic. **No** AWS account id, box ids, CloudFront URLs, SNS ARNs, admin email, or the dashboard password. Replace all with env vars + placeholders.

---

## 7. `.gitignore` / scrub checklist

**Exclude entirely from the public repo:**
- [ ] `kalshi_trade_infra/PLAN.md` (roadmap, incidents, box ids, strategy)
- [ ] `mvp.md` (internal queue, Stripe-flip notes)
- [ ] `kalshi_trade_infra/DESIGN.md`, `PRODUCT.md` (review; likely exclude)
- [ ] `kalshi_trade_infra/pids/ec2_instance_id.txt` (and add `pids/` to `.gitignore`)
- [ ] `.impeccable/`, `**/.impeccable/` (design session artifacts)
- [ ] `.pytest_cache/` (add to `.gitignore`)
- [ ] `trading_agent_new/` (separate project; Alpaca data redistribution + its own review)
- [ ] `app/static/apple-developer-merchantid-domain-association` (unless Apple Pay is served publicly)

**Sanitize before shipping (exact edits):**
- [ ] `client_api/client.py:72` — remove `password="kalshimakesmepoor"` default → `os.getenv("DASHBOARD_PASSWORD")`
- [ ] `client_api/README.md:19` — remove the password literal
- [ ] `app/notify.py:18-19`, `app/server.py:46` — email defaults → env var / `""` (no personal gmail)
- [ ] `app/server.py:1002`, `data_pipeline/snapshot_collector.py:49` — bucket default → placeholder (drop account id)
- [ ] `scripts/deploy_ec2_runner.sh`, `provision_rds_mysql.sh`, `load_app_secrets.sh`, `start_aws_collectors.sh` — parameterize account id, bucket, CloudFront URL, redirect URI
- [ ] `data_pipeline/live_alerter.py:43` — `DASHBOARD_URL` default → placeholder
- [ ] `README.md:295`, `client_api/README.md:17`, `client_api/example.ipynb:42` — example base_url → `https://your-dashboard.example.com`
- [ ] `AGENTS.md` → replace with a clean `CONTRIBUTING.md` (strip `.env.aws`/SSM/admin-password references)

**Add / verify in `.gitignore`:** `.env*` ✓ already, `credentials` ✓, `venv/`/`.venv/` ✓, `.pytest_cache/` ✓, plus add `pids/`, `**/.impeccable/` (currently only the `review/`+`questions/` subdirs are ignored; `design.json` and `surfaces/` are tracked).

**Add a new file:** `.env.example` (var names only, no values), `LICENSE`, `NOTICE`.

**CI backstop:** run `gitleaks`/`trufflehog` in CI so a future secret never lands.
```
```
