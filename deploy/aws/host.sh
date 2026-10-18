#!/usr/bin/env bash
# Runs ON the On-call Brain box as root. deploy/aws/deploy.sh sends it through SSM Run Command (no SSH):
#   host.sh <bucket> <git-sha>
# Swaps the code at <git-sha> into /opt/oncall-brain, writes .env from Parameter Store, rebuilds the app image,
# restarts the stack and waits for https://<domain>/health. The graphs (FalkorDB) and the certificate (Caddy) live in
# Docker volumes, so they survive. Safe to run again. Full output: /var/log/oncall-brain-deploy.log
set -euo pipefail

BUCKET=${1:?usage: host.sh <bucket> <git-sha>}
SHA=${2:?usage: host.sh <bucket> <git-sha>}
NAME=oncall-brain                  # compose project name; deploy.sh uploads to s3://<bucket>/$NAME/
SSM_PATH=/graphhacks               # every parameter under it becomes NAME=value in .env
APP=/opt/oncall-brain
LLM_PROVIDER_DEFAULT=anthropic     # a /graphhacks/LLM_PROVIDER or /graphhacks/LLM_MODEL parameter wins
LLM_MODEL_DEFAULT=claude-opus-5-5
LOG=/var/log/oncall-brain-deploy.log

say() { echo "== $(date +%T) $*" | tee -a "$LOG"; }
quiet() { "$@" >>"$LOG" 2>&1 || { tail -n 40 "$LOG"; return 1; }; }  # noisy steps: output goes to the log only
dc() { docker compose -p "$NAME" -f docker-compose.yml -f deploy/aws/docker-compose.aws.yml "$@"; }
imds() { curl -fsS -m 5 -H "X-aws-ec2-metadata-token: $IMDS_TOKEN" "http://169.254.169.254/latest/meta-data/$1"; }
fail() {
  say "$1"
  dc ps || true
  dc logs --no-color --tail 50 app || true
  dc logs --no-color --tail 15 caddy || true
  exit 1
}
# One deploy at a time: SSM keeps a deploy running after deploy.sh is stopped, and two would race on $APP.new/.old.
exec 9>/run/oncall-brain-deploy.lock
flock -n 9 || {
  echo "Another deploy is still running on the box (SSM keeps it going after deploy.sh stops)." \
    "Wait 2-5 min and run deploy.sh again."
  exit 1
}

say "Deploying $SHA"

# 1. Docker from the first boot (bootstrap-al2023.sh, the user data). Run it again if that boot failed halfway.
cloud-init status --wait >/dev/null 2>&1 || true
if ! docker compose version >/dev/null 2>&1 || ! docker buildx version >/dev/null 2>&1; then
  say "Docker is not ready; running the bootstrap again"
  bash /var/lib/cloud/instance/user-data.txt || { tail -n 30 /var/log/oncall-brain-bootstrap.log; exit 1; }
fi

# 2. Region and the public address from instance metadata (IMDSv2). The address is the Elastic IP.
IMDS_TOKEN=$(curl -fsS -m 5 -X PUT http://169.254.169.254/latest/api/token \
  -H "X-aws-ec2-metadata-token-ttl-seconds: 300")
REGION=$(imds placement/region)
IP=$(imds public-ipv4)
DOMAIN=${IP//./-}.sslip.io

# 3. The code, into a new directory first.
NEW=$APP.new
rm -rf "$NEW"
mkdir -p "$NEW"
aws s3 cp "s3://$BUCKET/$NAME/$SHA.tar.gz" - --region "$REGION" --only-show-errors | tar -xz -C "$NEW"

# 4. .env, readable by root only: the parameters, then the defaults they do not set, then what this box decides.
#    Values are single-quoted so compose takes them literally (no $ interpolation).
(
  umask 077
  aws ssm get-parameters-by-path --region "$REGION" --path "$SSM_PATH" --recursive --with-decryption \
      --query 'Parameters[].[Name,Value]' --output text |
    awk -F'\t' -v q="'" '{ n = $1; sub(".*/", "", n); print n "=" q $2 q }' >"$NEW/.env"
)
has() { grep -q "^$1=" "$NEW/.env"; }
if ! has MCP_TOKEN || ! has FALKORDB_PASSWORD; then
  say "MCP_TOKEN or FALKORDB_PASSWORD is missing under $SSM_PATH: run deploy.sh from your machine"
  exit 1
fi
{
  has LLM_PROVIDER || echo "LLM_PROVIDER=$LLM_PROVIDER_DEFAULT"
  has LLM_MODEL || echo "LLM_MODEL=$LLM_MODEL_DEFAULT"
  echo "DOMAIN=$DOMAIN"
  echo "COMPOSE_PROJECT_NAME=$NAME"  # so a manual `docker compose ...` in $APP addresses the same stack
  echo "COMPOSE_FILE=docker-compose.yml:deploy/aws/docker-compose.aws.yml"
} >>"$NEW/.env"
chmod 600 "$NEW/.env"
say "Settings: $(cut -d= -f1 "$NEW/.env" | tr '\n' ' ')"  # names only

# 5. Swap the directories. A running Caddy keeps the Caddyfile it started with, so note whether it changed.
caddy_changed=0
if [ -d "$APP" ] && ! cmp -s "$APP/deploy/aws/Caddyfile" "$NEW/deploy/aws/Caddyfile"; then caddy_changed=1; fi
rm -rf "$APP.old"
if [ -d "$APP" ]; then mv "$APP" "$APP.old"; fi
mv "$NEW" "$APP"
rm -rf "$APP.old"
cd "$APP"

# 6. Build while the old app still serves.
say "Building the app image (a few minutes on the first deploy)"
quiet dc build

# 7. Do not cut an agent run short. A run holds oncall_brain:lock:<tenant> and renews its 2-minute lease on every step
#    (adapters/falkordb/repository.py), so a held lock means a run is in flight. Wait for it; never delete the lock.
locks() { dc exec -T falkordb redis-cli --scan --pattern 'oncall_brain:lock:*' 2>/dev/null || true; }
if [ -n "$(dc ps -q --status running falkordb 2>/dev/null)" ]; then
  for i in $(seq 30); do
    [ -z "$(locks)" ] && break
    [ "$i" = 1 ] && say "An agent run is in flight; waiting up to 150 s for it to finish"
    sleep 5
  done
  [ -z "$(locks)" ] || say "Still locked: restarting anyway. That run stops, and its lease frees the company within 2 min."
fi

# 8. Start (recreates only what changed), then drop the previous image and old build cache so the disk does not fill.
say "Starting the stack"
quiet dc up -d
if [ "$caddy_changed" = 1 ]; then quiet dc up -d --no-deps --force-recreate caddy; fi
quiet docker image prune -f
docker builder prune -f --filter until=72h >>"$LOG" 2>&1 || true

# 9. Healthy container (seeded and answering), then the public URL (the first deploy waits for the certificate).
say "Waiting for the app to seed and answer"
for _ in $(seq 60); do
  [ "$(docker inspect -f '{{.State.Health.Status}}' "$(dc ps -q app)" 2>/dev/null)" = healthy ] && break
  sleep 5
done
[ "$(docker inspect -f '{{.State.Health.Status}}' "$(dc ps -q app)" 2>/dev/null)" = healthy ] ||
  fail "The app is not healthy after 5 minutes."
say "Checking https://$DOMAIN/health"
for _ in $(seq 36); do
  if out=$(curl -fsS -m 10 "https://$DOMAIN/health" 2>&1); then
    echo "$out"
    say "Up: https://$DOMAIN/ ($SHA)"
    exit 0
  fi
  sleep 5
done
fail "https://$DOMAIN/health does not answer after 3 minutes: $out"
