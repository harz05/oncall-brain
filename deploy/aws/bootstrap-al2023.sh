#!/bin/bash
# EC2 user data for the On-call Brain box (Amazon Linux 2023, arm64), passed by deploy/aws/provision.sh.
# Installs Docker, the Compose and Buildx CLI plugins (pinned versions, checksums checked) and 2 GB of swap.
# Nothing secret and no code here: deploy/aws/host.sh brings the code and writes .env from Parameter Store.
# Safe to run again (host.sh does when a first boot failed halfway). Log: /var/log/oncall-brain-bootstrap.log
set -euo pipefail

COMPOSE_VERSION=v5.5.1  # needs v2.24+ for `!reset` in docker-compose.aws.yml
COMPOSE_SHA256=732e3a84c1a0f67256ce80bc2598a24546b10ca05f9faa97efceb1171ece2ef7
BUILDX_VERSION=v0.37.2  # Compose builds images through Buildx
BUILDX_SHA256=efa38cb7aa7db2dbb9ad049b00b0a9737f66f033626177b5a4e845184ad7ab29
# Searched before /usr/libexec/docker/cli-plugins and never written by dnf, so a docker update cannot replace these.
PLUGINS=/usr/local/lib/docker/cli-plugins
LOG=/var/log/oncall-brain-bootstrap.log

exec >>"$LOG" 2>&1
echo "== $(date -Is) bootstrap"

dnf install -y docker tar  # the AMI already has curl and the AWS CLI
systemctl enable --now docker

plugin() {  # <name> <url> <sha256>: download unless the pinned binary is already in place
  local dest=$PLUGINS/docker-$1
  if [ -x "$dest" ] && echo "$3  $dest" | sha256sum -c --status; then return; fi
  # --retry-all-errors: attaching the Elastic IP resets downloads in progress (curl error 56), which --retry skips.
  curl -fsSL --retry 5 --retry-all-errors --retry-delay 3 -o "$dest.part" "$2"
  echo "$3  $dest.part" | sha256sum -c -
  chmod 755 "$dest.part"
  mv "$dest.part" "$dest"
}
mkdir -p "$PLUGINS"
plugin compose "https://github.com/docker/compose/releases/download/$COMPOSE_VERSION/docker-compose-linux-aarch64" \
  "$COMPOSE_SHA256"
plugin buildx "https://github.com/docker/buildx/releases/download/$BUILDX_VERSION/buildx-$BUILDX_VERSION.linux-arm64" \
  "$BUILDX_SHA256"
docker compose version
docker buildx version

# 2 GB of swap: the image build and FalkorDB share 2 GB of RAM.
if ! grep -q '^/swapfile ' /proc/swaps; then
  if [ ! -f /swapfile ]; then
    fallocate -l 2G /swapfile
    chmod 600 /swapfile
    mkswap /swapfile
  fi
  swapon /swapfile
fi
grep -q '^/swapfile ' /etc/fstab || echo '/swapfile none swap defaults 0 0' >>/etc/fstab

echo "== $(date -Is) bootstrap done"
