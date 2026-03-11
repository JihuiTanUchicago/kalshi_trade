#!/usr/bin/env bash
set -euo pipefail

AWS_PROFILE=${AWS_PROFILE:-agent}
AWS_REGION=${AWS_REGION:-us-east-1}
ENV_FILE=${ENV_FILE:-.env.aws}
INSTANCE_NAME=${INSTANCE_NAME:-kalshi-collector}
INSTANCE_TYPE=${INSTANCE_TYPE:-t4g.small}
EC2_SG_NAME=${EC2_SG_NAME:-kalshi-collector-ec2-sg}
ROLE_NAME=${ROLE_NAME:-kalshi-collector-ec2-role}
PROFILE_NAME=${PROFILE_NAME:-kalshi-collector-ec2-profile}
RUN_BACKFILL_ON_BOOT=${RUN_BACKFILL_ON_BOOT:-false}

if [[ ! -f "$ENV_FILE" ]]; then
  echo "[ERROR] ${ENV_FILE} missing. Run scripts/provision_rds_mysql.sh first."
  exit 1
fi
source "$ENV_FILE"

ACCOUNT_ID=$(aws sts get-caller-identity --profile "$AWS_PROFILE" --query Account --output text)
BUCKET="kalshi-trade-artifacts-${ACCOUNT_ID}-${AWS_REGION}"
KEY="bundle/kalshi_bundle_$(date +%Y%m%d_%H%M%S).tgz"

# ensure artifact bucket
aws s3api head-bucket --bucket "$BUCKET" --profile "$AWS_PROFILE" 2>/dev/null || \
  {
    if [[ "$AWS_REGION" == "us-east-1" ]]; then
      aws s3api create-bucket --bucket "$BUCKET" --region "$AWS_REGION" --profile "$AWS_PROFILE" >/dev/null
    else
      aws s3api create-bucket --bucket "$BUCKET" --region "$AWS_REGION" \
        --create-bucket-configuration LocationConstraint="$AWS_REGION" \
        --profile "$AWS_PROFILE" >/dev/null
    fi
  }

# package code
TAR_PATH="/tmp/kalshi_bundle.tgz"
tar -czf "$TAR_PATH" data_pipeline scripts requirements.txt
aws s3 cp "$TAR_PATH" "s3://${BUCKET}/${KEY}" --profile "$AWS_PROFILE" >/dev/null

# IAM role/profile for EC2 + SSM + S3 read
if ! aws iam get-role --role-name "$ROLE_NAME" --profile "$AWS_PROFILE" >/dev/null 2>&1; then
  cat >/tmp/assume-role-ec2.json <<JSON
{
  "Version":"2012-10-17",
  "Statement":[{"Effect":"Allow","Principal":{"Service":"ec2.amazonaws.com"},"Action":"sts:AssumeRole"}]
}
JSON
  aws iam create-role --role-name "$ROLE_NAME" --assume-role-policy-document file:///tmp/assume-role-ec2.json --profile "$AWS_PROFILE" >/dev/null
  aws iam attach-role-policy --role-name "$ROLE_NAME" --policy-arn arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore --profile "$AWS_PROFILE"
  aws iam attach-role-policy --role-name "$ROLE_NAME" --policy-arn arn:aws:iam::aws:policy/AmazonS3ReadOnlyAccess --profile "$AWS_PROFILE"
fi

if ! aws iam get-instance-profile --instance-profile-name "$PROFILE_NAME" --profile "$AWS_PROFILE" >/dev/null 2>&1; then
  aws iam create-instance-profile --instance-profile-name "$PROFILE_NAME" --profile "$AWS_PROFILE" >/dev/null
  aws iam add-role-to-instance-profile --instance-profile-name "$PROFILE_NAME" --role-name "$ROLE_NAME" --profile "$AWS_PROFILE"
  sleep 10
fi

# networking
VPC_ID=$(aws ec2 describe-vpcs --filters Name=isDefault,Values=true --query 'Vpcs[0].VpcId' --output text --profile "$AWS_PROFILE" --region "$AWS_REGION")
SUBNET_ID=$(aws ec2 describe-subnets --filters Name=vpc-id,Values="$VPC_ID" Name=default-for-az,Values=true --query 'Subnets[0].SubnetId' --output text --profile "$AWS_PROFILE" --region "$AWS_REGION")

EC2_SG_ID=$(aws ec2 describe-security-groups --profile "$AWS_PROFILE" --region "$AWS_REGION" \
  --filters Name=group-name,Values="$EC2_SG_NAME" Name=vpc-id,Values="$VPC_ID" \
  --query 'SecurityGroups[0].GroupId' --output text)
if [[ "$EC2_SG_ID" == "None" || -z "$EC2_SG_ID" ]]; then
  EC2_SG_ID=$(aws ec2 create-security-group --group-name "$EC2_SG_NAME" --description "Kalshi collector EC2 SG" --vpc-id "$VPC_ID" --profile "$AWS_PROFILE" --region "$AWS_REGION" --query GroupId --output text)
fi

PUBLIC_IP=$(curl -s https://checkip.amazonaws.com | tr -d '\n')
aws ec2 authorize-security-group-ingress --profile "$AWS_PROFILE" --region "$AWS_REGION" --group-id "$EC2_SG_ID" \
  --ip-permissions IpProtocol=tcp,FromPort=8080,ToPort=8080,IpRanges='[{CidrIp='"$PUBLIC_IP"'/32,Description="dashboard"}]' >/dev/null 2>&1 || true
aws ec2 authorize-security-group-ingress --profile "$AWS_PROFILE" --region "$AWS_REGION" --group-id "$EC2_SG_ID" \
  --ip-permissions IpProtocol=tcp,FromPort=22,ToPort=22,IpRanges='[{CidrIp='"$PUBLIC_IP"'/32,Description="ssh-optional"}]' >/dev/null 2>&1 || true

# allow EC2 SG -> RDS SG
RDS_SG_ID=$(aws rds describe-db-instances --profile "$AWS_PROFILE" --region "$AWS_REGION" \
  --query 'DBInstances[0].VpcSecurityGroups[0].VpcSecurityGroupId' --output text)
aws ec2 authorize-security-group-ingress --profile "$AWS_PROFILE" --region "$AWS_REGION" --group-id "$RDS_SG_ID" \
  --ip-permissions IpProtocol=tcp,FromPort=3306,ToPort=3306,UserIdGroupPairs='[{GroupId='"$EC2_SG_ID"'}]' >/dev/null 2>&1 || true

AMI_ID=$(aws ssm get-parameter --name /aws/service/ami-amazon-linux-latest/al2023-ami-kernel-6.1-arm64 --query 'Parameter.Value' --output text --profile "$AWS_PROFILE" --region "$AWS_REGION")

cat >/tmp/user-data-kalshi.sh <<USERDATA
#!/bin/bash
set -euxo pipefail
cd /opt
mkdir -p kalshi && cd kalshi

dnf install -y python3 python3-pip tar
aws s3 cp s3://${BUCKET}/${KEY} /opt/kalshi/bundle.tgz

tar -xzf /opt/kalshi/bundle.tgz -C /opt/kalshi
python3 -m venv /opt/kalshi/.venv
/opt/kalshi/.venv/bin/pip install -r /opt/kalshi/requirements.txt pymysql

cat >/opt/kalshi/.env.aws <<EOT
export AWS_PROFILE=${AWS_PROFILE}
export AWS_REGION=${AWS_REGION}
export MYSQL_HOST=${MYSQL_HOST}
export MYSQL_PORT=${MYSQL_PORT}
export MYSQL_USER=${MYSQL_USER}
export MYSQL_PASSWORD=${MYSQL_PASSWORD}
export MYSQL_DATABASE=${MYSQL_DATABASE}
export BACKFILL_INCLUDE_RAW_TRADES=false
EOT

cd /opt/kalshi
source /opt/kalshi/.env.aws
/opt/kalshi/.venv/bin/python -m data_pipeline.init_schema
if [[ "${RUN_BACKFILL_ON_BOOT}" == "true" ]]; then
  nohup /opt/kalshi/.venv/bin/python -m data_pipeline.backfill >/opt/kalshi/backfill.log 2>&1 &
fi
nohup /opt/kalshi/.venv/bin/python -m data_pipeline.forward_collector >/opt/kalshi/forward_collector.log 2>&1 &
nohup /opt/kalshi/.venv/bin/python -m data_pipeline.coinbase_collector >/opt/kalshi/coinbase_collector.log 2>&1 &
nohup /opt/kalshi/.venv/bin/python -m data_pipeline.feature_1m_collector >/opt/kalshi/feature_1m_collector.log 2>&1 &
nohup /opt/kalshi/.venv/bin/python -m data_pipeline.model_features_1m_builder >/opt/kalshi/model_features_1m_builder.log 2>&1 &
nohup /opt/kalshi/.venv/bin/python -m data_pipeline.simulated_trading_engine >/opt/kalshi/simulated_trading_engine.log 2>&1 &
nohup /opt/kalshi/.venv/bin/python -m data_pipeline.sim_portfolio_20s_updater >/opt/kalshi/sim_portfolio_20s_updater.log 2>&1 &
nohup /opt/kalshi/.venv/bin/python -m data_pipeline.live_trading_engine >/opt/kalshi/live_trading_engine.log 2>&1 &
nohup /opt/kalshi/.venv/bin/python -m data_pipeline.live_portfolio_20s_updater >/opt/kalshi/live_portfolio_20s_updater.log 2>&1 &
nohup /opt/kalshi/.venv/bin/python -m data_pipeline.dashboard_server >/opt/kalshi/dashboard.log 2>&1 &
USERDATA

INSTANCE_ID=$(aws ec2 run-instances \
  --profile "$AWS_PROFILE" --region "$AWS_REGION" \
  --image-id "$AMI_ID" \
  --instance-type "$INSTANCE_TYPE" \
  --iam-instance-profile Name="$PROFILE_NAME" \
  --security-group-ids "$EC2_SG_ID" \
  --subnet-id "$SUBNET_ID" \
  --user-data file:///tmp/user-data-kalshi.sh \
  --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=${INSTANCE_NAME}}]" \
  --query 'Instances[0].InstanceId' --output text)

echo "$INSTANCE_ID" > pids/ec2_instance_id.txt

echo "[INFO] Launched EC2 instance $INSTANCE_ID, waiting until running..."
aws ec2 wait instance-running --instance-ids "$INSTANCE_ID" --profile "$AWS_PROFILE" --region "$AWS_REGION"

PUBLIC_DNS=$(aws ec2 describe-instances --instance-ids "$INSTANCE_ID" --profile "$AWS_PROFILE" --region "$AWS_REGION" --query 'Reservations[0].Instances[0].PublicDnsName' --output text)
PUBLIC_IP_OUT=$(aws ec2 describe-instances --instance-ids "$INSTANCE_ID" --profile "$AWS_PROFILE" --region "$AWS_REGION" --query 'Reservations[0].Instances[0].PublicIpAddress' --output text)

echo "[INFO] EC2 ready"
echo "INSTANCE_ID=$INSTANCE_ID"
echo "PUBLIC_DNS=$PUBLIC_DNS"
echo "PUBLIC_IP=$PUBLIC_IP_OUT"
echo "DASHBOARD_URL=http://${PUBLIC_IP_OUT}:8080"
