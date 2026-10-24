# GitHub Actions deploy — one-time setup

The `Deploy web app` workflow (`.github/workflows/deploy.yml`) lets anyone with **write (push)
access to the repo** redeploy the web box from the GitHub UI, without the AWS key on their laptop.
GitHub only shows the **Run workflow** button to collaborators with push access, so this is the
"push-to-main-gated redeploy" — your friend can ship once they're a collaborator, no AWS key needed.

It reuses `scripts/deploy_web.sh` unchanged, so a CI deploy and a local `./deploy_web.sh` run the
exact same rollback-guarded path (whole-app tar → S3 → SSM extract/compile/`app.schema`/restart →
live curl 200 → CloudFront invalidate).

The `Deploy collector box` workflow (`.github/workflows/deploy-collector.yml`) does the same for
the collector box (i-0bd0683cc7e86243d) via `scripts/deploy_collector.sh`: data_pipeline/ only,
compile, restart the collector units, roll back if any of them fails to stay up. It uses the same
keys, which is why `RunOnBox` below lists both instances.

## How to deploy (for anyone with push access)

GitHub → **Actions** tab → **Deploy web app** → **Run workflow** → pick the ref (default `main`) →
**Run workflow**. Watch the live log; the run fails loudly (and the box auto-rolls-back) if the
on-box health check doesn't return 200.

---

## One-time AWS setup (owner, ~5 min)

Done once by whoever owns the AWS account (`568386354218`). It creates a GitHub OIDC trust + a
least-privilege role the workflow assumes for a few minutes per run — **no long-lived AWS keys are
ever stored in GitHub**. Run these with your admin AWS creds.

```bash
ACCOUNT=568386354218
REPO=JihuiTanUchicago/kalshi_trade        # owner/repo exactly as on GitHub
REGION=us-east-1

# 1. Register GitHub's OIDC provider (idempotent — skip the error if it already exists).
aws iam create-open-id-connect-provider \
  --url https://token.actions.githubusercontent.com \
  --client-id-list sts.amazonaws.com \
  --thumbprint-list 6938fd4d98bab03faadb97b34396831e3780aea1

# 2. Trust policy: only this repo's Actions can assume the role.
cat > /tmp/trust.json <<JSON
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": { "Federated": "arn:aws:iam::${ACCOUNT}:oidc-provider/token.actions.githubusercontent.com" },
    "Action": "sts:AssumeRoleWithWebIdentity",
    "Condition": {
      "StringEquals": { "token.actions.githubusercontent.com:aud": "sts.amazonaws.com" },
      "StringLike":   { "token.actions.githubusercontent.com:sub": "repo:${REPO}:*" }
    }
  }]
}
JSON
aws iam create-role --role-name tau-deploy --assume-role-policy-document file:///tmp/trust.json

# 3. Least-privilege deploy permissions (exactly what deploy_web.sh calls).
cat > /tmp/perms.json <<JSON
{
  "Version": "2012-10-17",
  "Statement": [
    { "Sid": "Bundle", "Effect": "Allow",
      "Action": ["s3:PutObject", "s3:GetObject"],
      "Resource": "arn:aws:s3:::kalshi-trade-artifacts-${ACCOUNT}-${REGION}/bundle/*" },
    { "Sid": "RunOnBox", "Effect": "Allow", "Action": "ssm:SendCommand",
      "Resource": [
        "arn:aws:ec2:${REGION}:${ACCOUNT}:instance/i-077d6f7873e7836ba",
        "arn:aws:ec2:${REGION}:${ACCOUNT}:instance/i-0bd0683cc7e86243d",
        "arn:aws:ssm:${REGION}::document/AWS-RunShellScript" ] },
    { "Sid": "PollCommand", "Effect": "Allow",
      "Action": ["ssm:GetCommandInvocation", "ssm:ListCommandInvocations"], "Resource": "*" },
    { "Sid": "Invalidate", "Effect": "Allow", "Action": "cloudfront:CreateInvalidation",
      "Resource": "arn:aws:cloudfront::${ACCOUNT}:distribution/EEQ00Y93RTB1K" }
  ]
}
JSON
aws iam put-role-policy --role-name tau-deploy --policy-name tau-deploy --policy-document file:///tmp/perms.json

# 4. Print the role ARN — paste it into the GitHub secret below.
aws iam get-role --role-name tau-deploy --query Role.Arn --output text
```

Then in GitHub → repo **Settings → Secrets and variables → Actions → New repository secret**:

| Name | Value |
|------|-------|
| `AWS_DEPLOY_ROLE_ARN` | the `arn:aws:iam::568386354218:role/tau-deploy` printed by step 4 |

That's it — the workflow is live. (Optionally, Settings → Environments → `production` → add required
reviewers to gate every deploy behind a human approval.)

### Tightening further (optional)
Restrict step 2's `sub` from `repo:${REPO}:*` to `repo:${REPO}:ref:refs/heads/main` (only `main`
can deploy) or `repo:${REPO}:environment:production` (pairs with the `production` environment gate).

---

## Quick alternative: access-key secrets (less secure, no AWS role)

If you'd rather not set up OIDC, store an IAM user's keys as repo secrets `AWS_ACCESS_KEY_ID` and
`AWS_SECRET_ACCESS_KEY` (scoped to the step-3 policy above) and replace the "Assume the AWS deploy
role" step in `deploy.yml` with:

```yaml
      - name: Configure AWS credentials (static keys)
        uses: aws-actions/configure-aws-credentials@v4
        with:
          aws-access-key-id: ${{ secrets.AWS_ACCESS_KEY_ID }}
          aws-secret-access-key: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
          aws-region: us-east-1
```

OIDC is preferred: the keys above are long-lived and sit in GitHub until rotated.
