# PLAN

## Current Codebase Knowledge
- Repository is a Kalshi trading project with AWS helper scripts under `scripts/`.
- AWS-related scripts default to `AWS_PROFILE` (`agent` or `assumed-admin`) and `AWS_REGION=us-east-1`.
- Repo contains non-AWS key material for Kalshi in `credentials/demo_key.txt` and `credentials/prod_key.txt`.

## AWS Access Audit (2026-03-24)
- Searched repo for AWS credential markers and key patterns.
- No `aws_access_key_id` / `aws_secret_access_key` / `aws_session_token` or `AKIA...`/`ASIA...` patterns found in repo files.
- `.env.aws` sets profile/region and DB env vars, indicating operational setup but not AWS access keys.
- Local machine has CLI credential profiles in `~/.aws/credentials` and `~/.aws/config`, including `agent` and `assumed-admin`.

## Action Plan
1. Report findings to user with clear separation of repo vs local machine credentials.
2. Recommend immediate credential hygiene for any long-lived or exposed keys (rotate/reissue, prefer SSO/short-lived creds).
3. Offer to validate active profile and launch permissions with safe AWS CLI checks.

## Open Assumptions
- User intent is to reuse existing local CLI profiles for another project.
- User can rotate/reissue credentials if needed.
