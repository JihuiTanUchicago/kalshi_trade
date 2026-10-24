#!/usr/bin/env bash
set -euo pipefail

AWS_PROFILE=${AWS_PROFILE-agent}   # local dev defaults to the `agent` profile; set AWS_PROFILE="" to use env creds (cloud/CI)
# The AWS CLI reads AWS_PROFILE from the env, so an unset profile falls back to env/instance creds.
if [[ -n "${AWS_PROFILE}" ]]; then export AWS_PROFILE; else unset AWS_PROFILE; fi
AWS_REGION=${AWS_REGION:-us-east-1}
DB_INSTANCE_ID=${DB_INSTANCE_ID:-kalshi-trade-mysql}
DB_NAME=${DB_NAME:-kalshi_trade}
DB_USER=${DB_USER:-kalshi_admin}
DB_CLASS=${DB_CLASS:-db.t4g.micro}
ALLOCATED_STORAGE=${ALLOCATED_STORAGE:-20}
SG_NAME=${SG_NAME:-kalshi-trade-mysql-sg}
ENV_FILE=${ENV_FILE:-.env.aws}

random_pw() {
  python3 - <<'PY'
import secrets
import string
alphabet = string.ascii_letters + string.digits + "!@#%^*()_+-="
print("".join(secrets.choice(alphabet) for _ in range(24)))
PY
}

echo "[INFO] Using profile=${AWS_PROFILE:-<env credentials>} region=${AWS_REGION}"

VPC_ID=$(aws ec2 describe-vpcs \
  --region "$AWS_REGION" \
  --filters Name=isDefault,Values=true \
  --query 'Vpcs[0].VpcId' --output text)

if [[ "$VPC_ID" == "None" || -z "$VPC_ID" ]]; then
  echo "[ERROR] No default VPC found."
  exit 1
fi

echo "[INFO] Default VPC: $VPC_ID"

SG_ID=$(aws ec2 describe-security-groups \
  --region "$AWS_REGION" \
  --filters Name=group-name,Values="$SG_NAME" Name=vpc-id,Values="$VPC_ID" \
  --query 'SecurityGroups[0].GroupId' --output text)

if [[ "$SG_ID" == "None" || -z "$SG_ID" ]]; then
  SG_ID=$(aws ec2 create-security-group \
    --region "$AWS_REGION" \
    --group-name "$SG_NAME" \
    --description "Kalshi trade MySQL SG" \
    --vpc-id "$VPC_ID" \
    --query 'GroupId' --output text)
fi

echo "[INFO] Security group: $SG_ID"

PUBLIC_IP=$(curl -s https://checkip.amazonaws.com | tr -d '\n')
if [[ -n "$PUBLIC_IP" ]]; then
  aws ec2 authorize-security-group-ingress \
    --region "$AWS_REGION" \
    --group-id "$SG_ID" \
    --ip-permissions IpProtocol=tcp,FromPort=3306,ToPort=3306,IpRanges='[{CidrIp='"$PUBLIC_IP"'/32,Description="local-dev"}]' \
    >/dev/null 2>&1 || true
  echo "[INFO] Allowed MySQL ingress from ${PUBLIC_IP}/32"
fi

exists=$(aws rds describe-db-instances \
  --region "$AWS_REGION" \
  --db-instance-identifier "$DB_INSTANCE_ID" \
  --query 'DBInstances[0].DBInstanceIdentifier' --output text 2>/dev/null || true)

if [[ "$exists" == "None" || -z "$exists" ]]; then
  DB_PASSWORD=${DB_PASSWORD:-$(random_pw)}
  echo "[INFO] Creating RDS instance ${DB_INSTANCE_ID}"
  aws rds create-db-instance \
    --region "$AWS_REGION" \
    --db-instance-identifier "$DB_INSTANCE_ID" \
    --engine mysql \
    --db-instance-class "$DB_CLASS" \
    --allocated-storage "$ALLOCATED_STORAGE" \
    --storage-type gp3 \
    --master-username "$DB_USER" \
    --master-user-password "$DB_PASSWORD" \
    --db-name "$DB_NAME" \
    --publicly-accessible \
    --vpc-security-group-ids "$SG_ID" \
    --backup-retention-period 0 \
    --no-multi-az \
    >/dev/null
else
  echo "[INFO] RDS instance already exists: $exists"
  DB_PASSWORD=${DB_PASSWORD:-}
fi

echo "[INFO] Waiting for DB availability..."
aws rds wait db-instance-available \
  --region "$AWS_REGION" \
  --db-instance-identifier "$DB_INSTANCE_ID"

DB_ENDPOINT=$(aws rds describe-db-instances \
  --region "$AWS_REGION" \
  --db-instance-identifier "$DB_INSTANCE_ID" \
  --query 'DBInstances[0].Endpoint.Address' --output text)
DB_PORT=$(aws rds describe-db-instances \
  --region "$AWS_REGION" \
  --db-instance-identifier "$DB_INSTANCE_ID" \
  --query 'DBInstances[0].Endpoint.Port' --output text)

if [[ -z "$DB_PASSWORD" ]]; then
  echo "[WARN] Existing DB detected and DB_PASSWORD not provided."
  echo "[WARN] Set DB_PASSWORD in env before starting collectors if unknown."
fi

{
  # Only pin a profile when one is in use, so env/instance creds keep working.
  if [[ -n "${AWS_PROFILE:-}" ]]; then echo "export AWS_PROFILE=${AWS_PROFILE}"; fi
  cat <<EOT
export AWS_REGION=${AWS_REGION}
export MYSQL_HOST=${DB_ENDPOINT}
export MYSQL_PORT=${DB_PORT}
export MYSQL_USER=${DB_USER}
export MYSQL_PASSWORD=${DB_PASSWORD}
export MYSQL_DATABASE=${DB_NAME}
EOT
} > "$ENV_FILE"

chmod 600 "$ENV_FILE"
echo "[INFO] Wrote ${ENV_FILE} with RDS connection settings"
