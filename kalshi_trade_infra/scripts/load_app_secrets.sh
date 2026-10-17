#!/usr/bin/env bash
# Pull Recursive's secrets from SSM Parameter Store into /opt/kalshi/.env.app
# and restart the services that read them. Run as root on the box.
#
# The owner creates these SecureString parameters in the AWS console
# (Systems Manager > Parameter Store), so no secret passes through chat,
# a terminal history or this repo:
#   /recursive/GOOGLE_CLIENT_ID
#   /recursive/GOOGLE_CLIENT_SECRET
#   /recursive/ANTHROPIC_API_KEY
#   /recursive/MASSIVE_API_KEY
#   /recursive/DATABENTO_API_KEY
#   /recursive/EXA_API_KEY
# Optional Massive activation/feed settings use the same /recursive/VAR_NAME path.
# Optional TAU_DATABENTO_ENABLED/DATASETS/MAX_COST_USD use the same path pattern.
# Optional TAU_EXA_ENABLED/HISTORICAL_ENABLED use the same path pattern.
# APP_SECRET_KEY is generated on the box at first deploy and kept as is.
set -euo pipefail
umask 077
ENV_FILE=/opt/kalshi/.env.app
REDIRECT_URI=${REDIRECT_URI:-https://d1gfpzcosqrjya.cloudfront.net/auth/google/callback}
unset AWS_PROFILE  # .env.aws sets it; on the box we must use the instance role

touch "$ENV_FILE" && chmod 600 "$ENV_FILE"
for name in GOOGLE_CLIENT_ID GOOGLE_CLIENT_SECRET ANTHROPIC_API_KEY \
            MASSIVE_API_KEY TAU_MASSIVE_ENABLED TAU_MASSIVE_FX_FEED TAU_MASSIVE_FX_SYMBOLS TAU_MASSIVE_DATASETS \
            DATABENTO_API_KEY TAU_DATABENTO_ENABLED TAU_DATABENTO_DATASETS TAU_DATABENTO_MAX_COST_USD \
            EXA_API_KEY TAU_EXA_ENABLED TAU_EXA_HISTORICAL_ENABLED \
            STRIPE_SECRET_KEY STRIPE_PUBLISHABLE_KEY STRIPE_WEBHOOK_SECRET STRIPE_PAYMENT_CONFIG; do
  if value=$(aws ssm get-parameter --region us-east-1 --name "/recursive/$name" --with-decryption \
               --query Parameter.Value --output text 2>/dev/null); then
    grep -v "^export $name=" "$ENV_FILE" > "$ENV_FILE.tmp" || true
    printf 'export %s=%q\n' "$name" "$value" >> "$ENV_FILE.tmp"
    mv "$ENV_FILE.tmp" "$ENV_FILE" && chmod 600 "$ENV_FILE"
    echo "$name: loaded"
  else
    echo "$name: not found in Parameter Store (skipped)"
  fi
done
grep -v '^export APP_GOOGLE_REDIRECT_URI=' "$ENV_FILE" > "$ENV_FILE.tmp" || true
printf 'export APP_GOOGLE_REDIRECT_URI=%q\n' "$REDIRECT_URI" >> "$ENV_FILE.tmp"
mv "$ENV_FILE.tmp" "$ENV_FILE" && chown root:root "$ENV_FILE" && chmod 600 "$ENV_FILE"
systemctl restart recursive-web recursive-agents
echo "restarted recursive-web recursive-agents"
