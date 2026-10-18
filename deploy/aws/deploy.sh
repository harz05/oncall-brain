#!/usr/bin/env bash
# Ship the committed code (git HEAD) to the On-call Brain box and rebuild it there, without SSH (docs/DEPLOY.md
# section E). Run deploy/aws/provision.sh once first.
#   deploy/aws/deploy.sh [--allow-dirty]
# 1. Uploads HEAD as s3://<bucket>/oncall-brain/<sha>.tar.gz, and deploy/aws/host.sh next to it.
# 2. Writes the Parameter Store settings that are missing: MCP_TOKEN and FALKORDB_PASSWORD are generated once and
#    kept on every later deploy; LLM_API_KEY and the optional Slack values are copied from the repo's .env.
# 3. Runs host.sh on the box through SSM Run Command, prints its output, the URL and the health check.
set -euo pipefail

REGION=ap-south-1
PROJECT=graphhacks
NAME=oncall-brain
SSM_PATH=/graphhacks
COPIED_FROM_ENV=(LLM_API_KEY SLACK_WEBHOOK_URL SLACK_SIGNING_SECRET)  # copied once when set in .env
REPO=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
BOX=$NAME-box

ALLOW_DIRTY=0
for arg in "$@"; do
  case $arg in
    --allow-dirty) ALLOW_DIRTY=1 ;;
    *) echo "usage: $0 [--allow-dirty]" >&2; exit 2 ;;
  esac
done

ec2() { aws ec2 "$@" --region "$REGION"; }
none() { [ -z "$1" ] || [ "$1" = None ]; }
die() { echo "$*" >&2; exit 1; }

cd "$REPO"
if [ "$ALLOW_DIRTY" = 0 ] && ! git diff --quiet HEAD --; then
  die "Tracked files have uncommitted changes, and the box only gets what is committed (git archive HEAD).
Commit them, or pass --allow-dirty to ship HEAD without them."
fi
# New files the image or the stack needs (the Dockerfile's COPY lines, the compose files) must be committed too.
untracked=$(git ls-files --others --exclude-standard -- src web scripts pyproject.toml constraints.txt Dockerfile \
  docker-compose.yml deploy/aws/Caddyfile deploy/aws/docker-compose.aws.yml)
if [ "$ALLOW_DIRTY" = 0 ] && [ -n "$untracked" ]; then
  die "These files are not committed, so the box would not get them (git add them, or pass --allow-dirty):
$untracked"
fi
SHA=$(git rev-parse --short=12 HEAD)

ACCOUNT=$(aws sts get-caller-identity --region "$REGION" --query Account --output text)
BUCKET=$NAME-$ACCOUNT-$REGION
INSTANCE=$(ec2 describe-instances --filters "Name=tag:Name,Values=$BOX" "Name=tag:Project,Values=$PROJECT" \
  Name=instance-state-name,Values=running --query 'Reservations[0].Instances[0].InstanceId' --output text)
none "$INSTANCE" && die "No running $BOX in $REGION. Run deploy/aws/provision.sh (it also starts a stopped box)."
EIP=$(ec2 describe-addresses --filters "Name=instance-id,Values=$INSTANCE" --query 'Addresses[0].PublicIp' --output text)
none "$EIP" && die "$INSTANCE has no Elastic IP. Run deploy/aws/provision.sh to associate it."
DOMAIN=${EIP//./-}.sslip.io

echo "Deploying $SHA to $INSTANCE ($DOMAIN)"
git archive --format=tar.gz HEAD | aws s3 cp - "s3://$BUCKET/$NAME/$SHA.tar.gz" --region "$REGION" --only-show-errors
aws s3 cp "$REPO/deploy/aws/host.sh" "s3://$BUCKET/$NAME/host.sh" --region "$REGION" --only-show-errors

# ---- Settings in Parameter Store: write the missing ones, never print a value -------------------------------------
param_exists() {
  aws ssm get-parameter --region "$REGION" --name "$SSM_PATH/$1" --query Parameter.Name --output text >/dev/null 2>&1
}
put_secret() {  # <name> <value>: the value reaches the CLI through a pipe (file:///dev/fd/N): not in ps, not on disk
  aws ssm put-parameter --region "$REGION" --name "$SSM_PATH/$1" --type SecureString \
    --tags "Key=Project,Value=$PROJECT" --value file://<(printf %s "$2") >/dev/null
  echo "  wrote $SSM_PATH/$1"
}
env_value() {  # <name>: its value in the repo's .env (last line wins, surrounding quotes dropped)
  [ -f "$REPO/.env" ] || return 0
  sed -n "s/^$1=//p" "$REPO/.env" | tail -n 1 | sed -e 's/^"\(.*\)"$/\1/' -e "s/^'\(.*\)'$/\1/"
}
echo "Settings under $SSM_PATH:"
for n in MCP_TOKEN FALKORDB_PASSWORD; do
  if param_exists "$n"; then echo "  kept  $SSM_PATH/$n"; else put_secret "$n" "$(openssl rand -hex 24)"; fi
done
provider=$(env_value LLM_PROVIDER)
if [ -n "$provider" ] && [ "$provider" != anthropic ]; then
  echo "  note  .env says LLM_PROVIDER=$provider; the box runs anthropic unless $SSM_PATH/LLM_PROVIDER says otherwise"
fi
for n in "${COPIED_FROM_ENV[@]}"; do
  if param_exists "$n"; then echo "  kept  $SSM_PATH/$n"; continue; fi
  value=$(env_value "$n")
  if [ -z "$value" ] && [ "$n" = LLM_API_KEY ]; then value=$(env_value ANTHROPIC_API_KEY); fi
  if [ -n "$value" ]; then
    put_secret "$n" "$value"
  elif [ "$n" = LLM_API_KEY ]; then
    echo "  none  LLM_API_KEY (not in .env): the box runs the deterministic planner"
  else
    echo "  none  $n (not in .env)"
  fi
done
unset value

# ---- Run host.sh on the box --------------------------------------------------------------------------------------
echo "Waiting for the box to answer Systems Manager"
ping=""
for _ in $(seq 60); do
  ping=$(aws ssm describe-instance-information --region "$REGION" --filters "Key=InstanceIds,Values=$INSTANCE" \
    --query 'InstanceInformationList[0].PingStatus' --output text 2>/dev/null || true)
  [ "$ping" = Online ] && break
  sleep 10
done
[ "$ping" = Online ] || die "$INSTANCE is not Online in Systems Manager after 10 minutes (status: ${ping:-unknown})."

CMD="aws s3 cp s3://$BUCKET/$NAME/host.sh /root/oncall-brain-host.sh --region $REGION --only-show-errors"
CMD+=" && bash /root/oncall-brain-host.sh $BUCKET $SHA"
ID=$(aws ssm send-command --region "$REGION" --instance-ids "$INSTANCE" --document-name AWS-RunShellScript \
  --comment "On-call Brain deploy $SHA" --parameters "commands=[\"$CMD\"],executionTimeout=[\"1800\"]" \
  --query Command.CommandId --output text)
echo "Running host.sh on the box (SSM command $ID). The first deploy takes 5-10 minutes, a redeploy 2-4."
# `aws ssm wait command-executed` gives up after ~100 s, so poll.
status=Pending
for _ in $(seq 200); do
  status=$(aws ssm get-command-invocation --region "$REGION" --command-id "$ID" --instance-id "$INSTANCE" \
    --query Status --output text 2>/dev/null || echo Pending)
  case $status in Pending | InProgress | Delayed | Cancelling) sleep 10 ;; *) break ;; esac
done
invocation() {
  aws ssm get-command-invocation --region "$REGION" --command-id "$ID" --instance-id "$INSTANCE" \
    --query "$1" --output text
}
echo "---- box output ($status) ----"
invocation StandardOutputContent
err=$(invocation StandardErrorContent)
[ -z "$err" ] || [ "$err" = None ] || { echo "---- box errors ----"; echo "$err"; }
case $status in  # SSM returns the output only for these two
  Success | Failed) ;;
  *) echo "No output for status $status. Full log: aws ssm start-session --region $REGION --target $INSTANCE," \
       "then sudo tail -n 100 /var/log/oncall-brain-deploy.log" ;;
esac
echo "----"

# ---- Check from here -----------------------------------------------------------------------------------------
health="" healthy=0
for _ in $(seq 12); do  # 200 only when the app and FalkorDB are up (503 otherwise)
  if health=$(curl -fsS -m 15 "https://$DOMAIN/health" 2>&1); then healthy=1; break; fi
  sleep 10
done
echo "Health    $health"
echo "UI        https://$DOMAIN/"
echo "MCP       https://$DOMAIN/mcp (bearer token below)"
echo "Token     aws ssm get-parameter --region $REGION --name $SSM_PATH/MCP_TOKEN --with-decryption \\"
echo "            --query Parameter.Value --output text"
echo "Claude    export ONCALL_BRAIN_URL=https://$DOMAIN"
echo "          export ONCALL_BRAIN_TOKEN=\"\$(aws ssm get-parameter --region $REGION --name $SSM_PATH/MCP_TOKEN \\"
echo "            --with-decryption --query Parameter.Value --output text)\""
echo "          claude --plugin-dir ./plugin mcp list"
echo "Shell     aws ssm start-session --region $REGION --target $INSTANCE"
[ "$status" = Success ] && [ "$healthy" = 1 ] || exit 1
