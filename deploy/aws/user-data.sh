#!/bin/bash
# On-call Brain on one Ubuntu 24.04 box (EC2 or Lightsail), docs/DEPLOY.md section D.
# Paste it as user data (EC2) or launch script (Lightsail), or run it by hand as root. It is safe to run again: a
# second run keeps .env (tokens, the LLM key), pulls the latest code, rebuilds and restarts:
#   sudo bash /opt/oncall-brain/deploy/aws/user-data.sh
# Output goes to /var/log/oncall-brain-setup.log.

REPO_URL=""    # the public git repo, e.g. https://github.com/<you>/<repo>.git; empty = copy the code in by hand
BRANCH="main"
DOMAIN=""      # empty = <public-ip-with-dashes>.sslip.io; or a name whose A record points at this box

APP_DIR=/opt/oncall-brain
LOG=/var/log/oncall-brain-setup.log

set -euo pipefail

# Everything runs inside main: bash reads a script as it goes, and `git pull` may rewrite this very file.
main() {
  exec > >(tee -a "$LOG") 2>&1
  echo "== $(date -Is) On-call Brain setup"
  export DEBIAN_FRONTEND=noninteractive HOME="${HOME:-/root}"

  install_docker
  add_swap
  get_code
  cd "$APP_DIR"
  write_env

  dc up -d --build
  docker image prune -f >/dev/null  # drop the previous build's image so updates do not fill the disk
  wait_healthy
  report
}

dc() { docker compose -f docker-compose.yml -f deploy/aws/docker-compose.aws.yml "$@"; }
# Lock::Timeout makes install wait for dpkg, but update does not wait for the lists lock (apt-daily on first boot).
apt_update() { for _ in $(seq 30); do apt-get -o DPkg::Lock::Timeout=600 update && return; sleep 10; done; return 1; }

install_docker() {  # Docker Engine + compose plugin from Docker's apt repo (docs.docker.com/engine/install/ubuntu)
  if docker compose version >/dev/null 2>&1; then return; fi
  apt_update
  apt-get -o DPkg::Lock::Timeout=600 install -y ca-certificates curl git openssl
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  # shellcheck source=/dev/null
  . /etc/os-release
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc]" \
    "https://download.docker.com/linux/ubuntu ${UBUNTU_CODENAME:-$VERSION_CODENAME} stable" \
    > /etc/apt/sources.list.d/docker.list
  apt_update
  apt-get -o DPkg::Lock::Timeout=600 install -y \
    docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  systemctl enable --now docker
}

add_swap() {  # 2 GB of swap, so the image build does not run out of memory on a 2 GB box
  if grep -q '^/swapfile ' /proc/swaps; then return; fi
  if [ ! -f /swapfile ]; then
    fallocate -l 2G /swapfile
    chmod 600 /swapfile
    mkswap /swapfile
  fi
  swapon /swapfile
  grep -q '^/swapfile ' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
}

get_code() {
  if [ -d "$APP_DIR/.git" ]; then
    git -C "$APP_DIR" pull --ff-only
  elif [ -f "$APP_DIR/docker-compose.yml" ]; then
    echo "Using the code already in $APP_DIR (not a git checkout: copy a new tarball in to update)."
  elif [ -n "$REPO_URL" ]; then
    git clone --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
  else
    cat <<EOF
No code in $APP_DIR and REPO_URL is empty. Copy it in from your checkout, then run this script again:
  git archive --format=tar.gz -o oncall-brain.tar.gz HEAD             # on your machine, in the repo
  scp oncall-brain.tar.gz ubuntu@<public-ip>:/tmp/
  ssh ubuntu@<public-ip>
  sudo mkdir -p $APP_DIR && sudo tar -xzf /tmp/oncall-brain.tar.gz -C $APP_DIR
  sudo bash $APP_DIR/deploy/aws/user-data.sh
EOF
    exit 0
  fi
}

public_ip() {  # IMDSv2 first (EC2); checkip.amazonaws.com where instance metadata has no public address
  local token ip=""
  if token=$(curl -fsS -m 5 -X PUT http://169.254.169.254/latest/api/token \
               -H "X-aws-ec2-metadata-token-ttl-seconds: 60"); then
    ip=$(curl -fsS -m 5 -H "X-aws-ec2-metadata-token: $token" \
           http://169.254.169.254/latest/meta-data/public-ipv4 || true)
  fi
  [ -n "$ip" ] || ip=$(curl -fsS -m 5 https://checkip.amazonaws.com)
  ip=$(echo "$ip" | tr -d '[:space:]')
  [[ $ip =~ ^[0-9]+(\.[0-9]+){3}$ ]] || { echo "Could not find this box's public IPv4 (got '$ip')." >&2; exit 1; }
  echo "$ip"
}

write_env() {
  if [ ! -f .env ]; then  # first run: tokens are generated once and kept on every later run
    (umask 077 && sed -e "s|^MCP_TOKEN=.*|MCP_TOKEN=$(openssl rand -hex 24)|" \
                      -e "s|^FALKORDB_PASSWORD=.*|FALKORDB_PASSWORD=$(openssl rand -hex 24)|" \
                      deploy/aws/env.example > .env)
  fi
  chmod 600 .env
  # DOMAIN: the value set at the top wins; else an sslip.io name that follows the public IP (an Elastic IP attached
  # later is picked up by running this script again). A custom domain already in .env is left alone.
  local current
  current=$(sed -n 's/^DOMAIN=//p' .env)
  if [ -z "$DOMAIN" ]; then
    if [ -z "$current" ] || [[ $current == *.sslip.io ]]; then
      DOMAIN="$(public_ip | tr . -).sslip.io"
    else
      DOMAIN=$current
    fi
  fi
  sed -i "s|^DOMAIN=.*|DOMAIN=$DOMAIN|" .env
}

wait_healthy() {  # the app turns healthy once the demo company is seeded and uvicorn answers
  local id status=""
  id=$(dc ps -q app)
  for _ in $(seq 60); do
    status=$(docker inspect -f '{{.State.Health.Status}}' "$id" 2>/dev/null || true)
    [ "$status" = healthy ] && return
    sleep 5
  done
  echo "The app is not healthy after 5 minutes (status: ${status:-unknown}). Look at:"
  echo "  cd $APP_DIR && sudo docker compose logs --tail 100 app falkordb"
  exit 1
}

report() {
  cat <<EOF

On-call Brain is up. The first HTTPS request can take ~30 s while Caddy gets the certificate.
  UI       https://$DOMAIN/
  Health   curl -fsS https://$DOMAIN/health
  MCP      https://$DOMAIN/mcp   token: sudo grep ^MCP_TOKEN= $APP_DIR/.env
  LLM key  (empty: the deterministic planner runs). To set it without leaving it in the shell history:
             read -rsp 'Anthropic API key: ' K; echo; sudo sed -i "s|^LLM_API_KEY=.*|LLM_API_KEY=\$K|" $APP_DIR/.env; unset K
             cd $APP_DIR && sudo docker compose up -d
  Update   cd $APP_DIR && sudo git pull --ff-only && sudo docker compose up -d --build
           (or run this script again: sudo bash $APP_DIR/deploy/aws/user-data.sh)
  Logs     cd $APP_DIR && sudo docker compose logs -f app
EOF
}

main "$@"
