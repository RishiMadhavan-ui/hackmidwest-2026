# shellcheck shell=bash disable=SC2034
# Shared settings for deploy scripts. Sourced by other scripts; do not run directly.
# Resource labels match the workshop kit so you can reuse the same LKE cluster.

REPO=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$REPO" || exit 1

# Match linode-cli defaults from ~/.config/linode-cli (region / type).
REGION=us-central
LKE_LABEL=hackmidwest-lke
NB_LABEL=hackmidwest-nb
# LKE node pool type (CLI default g8-dedicated-16-8 is not enabled for LKE on this account).
LINODE_TYPE=g6-standard-4
KUBECONFIG_FILE=hackmidwest-kubeconfig.yaml
NAMESPACE=hackmidwest

# Managed PostgreSQL (Akamai Databases).
DB_LABEL=hackmidwest-db
DB_TYPE=g6-nanode-1
DB_ENGINE=postgresql/17

# Container images. Set IMAGE_REGISTRY in .env (for example ghcr.io/<user>/hackmidwest-2026).
# deploy_lke.sh builds api/web/agents and pushes :<tag> (default: latest).
IMAGE_TAG=${IMAGE_TAG:-latest}

if [[ ! -f .env ]]; then
  echo "No .env file. Run: cp .env.example .env"
  exit 1
fi

# get_env KEY: print KEY's value from .env, without surrounding quotes.
get_env() {
  { grep "^$1=" .env || true; } | tail -n 1 | tr -d '\r' | cut -d= -f2- | sed -e "s/^[\"']//" -e "s/[\"']\$//"
}

# set_env KEY VALUE: replace the KEY= line in .env, or add one at the end.
set_env() {
  local tmp
  tmp=$(mktemp)
  KEY="$1" VALUE="$2" awk '
    BEGIN { key = ENVIRON["KEY"]; line = key "=" ENVIRON["VALUE"] }
    index($0, key "=") == 1 { if (!done) print line; done = 1; next }
    { print }
    END { if (!done) print line }
  ' .env > "$tmp" && cat "$tmp" > .env
  rm -f "$tmp"
}

# my_ip: this machine's public IPv4, for the initial database allow list.
my_ip() {
  curl -s --max-time 10 https://api.ipify.org || curl -s --max-time 10 https://ipv4.icanhazip.com
}

# Docker requires lowercase repository names (GitHub usernames may be mixed case).
IMAGE_REGISTRY=$(echo "${IMAGE_REGISTRY:-$(get_env IMAGE_REGISTRY)}" | tr -d '[:space:]' | tr '[:upper:]' '[:lower:]')
API_IMAGE="${IMAGE_REGISTRY:+$IMAGE_REGISTRY/}api:$IMAGE_TAG"
WEB_IMAGE="${IMAGE_REGISTRY:+$IMAGE_REGISTRY/}web:$IMAGE_TAG"
AGENTS_IMAGE="${IMAGE_REGISTRY:+$IMAGE_REGISTRY/}agents:$IMAGE_TAG"

if [[ -z $IMAGE_REGISTRY ]]; then
  API_IMAGE="hackmidwest-api:$IMAGE_TAG"
  WEB_IMAGE="hackmidwest-web:$IMAGE_TAG"
  AGENTS_IMAGE="hackmidwest-agents:$IMAGE_TAG"
fi

# wait_for SECONDS WHAT COMMAND...: run COMMAND every 5 seconds until it succeeds.
wait_for() {
  local limit=$1 what=$2 waited=0
  shift 2
  until "$@" >/dev/null 2>&1; do
    if (( waited >= limit )); then
      echo "Gave up after $limit seconds waiting for $what."
      return 1
    fi
    sleep 5
    waited=$((waited + 5))
  done
}

# render_manifest FILE: substitute image placeholders for kubectl apply.
render_manifest() {
  sed -e "s|\${API_IMAGE}|${API_IMAGE}|g" \
      -e "s|\${WEB_IMAGE}|${WEB_IMAGE}|g" \
      -e "s|\${AGENTS_IMAGE}|${AGENTS_IMAGE}|g" \
      -e "s|\${MCP_IMAGE}|${MCP_IMAGE}|g" "$1"
}

# db_id: managed Postgres labeled hackmidwest-db, or empty.
db_id() {
  linode-cli databases postgresql-list --label "$DB_LABEL" --text --no-headers --format id 2>/dev/null || true
}

# minutes_since TIMESTAMP: human-readable age for provision logs.
minutes_since() {
  python3 -c '
import sys
from datetime import datetime, timezone
start = datetime.fromisoformat(sys.argv[1]).replace(tzinfo=timezone.utc)
seconds = int((datetime.now(timezone.utc) - start).total_seconds())
print(f"{seconds // 60} min {seconds % 60} s")' "$1"
}

# ensure_database: create or reuse managed Postgres; write DATABASE_URL to .env.
ensure_database() {
  local id status host port user password created
  id=$(db_id)
  if [[ -z $id ]]; then
    ip=$(my_ip)
    [[ -n $ip ]] || { echo "Could not find your public IP for the database allow list."; return 1; }
    echo "Creating managed Postgres $DB_LABEL in $REGION ($DB_TYPE / $DB_ENGINE). Allowing $ip/32."
    id=$(linode-cli databases postgresql-create \
      --label "$DB_LABEL" \
      --region "$REGION" \
      --type "$DB_TYPE" \
      --engine "$DB_ENGINE" \
      --cluster_size 1 \
      --allow_list "$ip/32" \
      --text --no-headers --format id)
    echo "Created database id $id."
  else
    echo "Managed Postgres $DB_LABEL already exists (id $id)."
  fi

  created=$(linode-cli databases postgresql-view "$id" --text --no-headers --format created)
  while true; do
    status=$(linode-cli databases postgresql-view "$id" --text --no-headers --format status)
    echo "$(date +%H:%M:%S)  $DB_LABEL is $status ($(minutes_since "$created") since create)"
    [[ $status == active ]] && break
    sleep 30
  done

  host=$(linode-cli databases postgresql-view "$id" --text --no-headers --format hosts.primary)
  port=$(linode-cli databases postgresql-view "$id" --text --no-headers --format port)
  resolves() { python3 -c 'import socket, sys; socket.gethostbyname(sys.argv[1])' "$host"; }
  if ! resolves 2>/dev/null; then
    echo "Waiting for $host to appear in DNS."
    wait_for 600 "$host to resolve" resolves
  fi

  read -r user password <<<"$(linode-cli databases postgresql-creds-view "$id" --text --no-headers --format username,password)"
  password=$(python3 -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1], safe=""))' "$password")
  set_env DATABASE_URL "postgresql://$user:$password@$host:$port/defaultdb?sslmode=require"
  echo "Wrote DATABASE_URL for $host:$port to .env."
}
