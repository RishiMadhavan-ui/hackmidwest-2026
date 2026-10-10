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

# Container images. Set IMAGE_REGISTRY in .env (for example ghcr.io/<user>/hackmidwest-2026).
# deploy_lke.sh builds api/web and pushes :<tag> (default: latest).
IMAGE_TAG=${IMAGE_TAG:-latest}

if [[ ! -f .env ]]; then
  echo "No .env file. Run: cp .env.example .env"
  exit 1
fi

# get_env KEY: print KEY's value from .env, without surrounding quotes.
get_env() {
  { grep "^$1=" .env || true; } | tail -n 1 | tr -d '\r' | cut -d= -f2- | sed -e "s/^[\"']//" -e "s/[\"']\$//"
}

# Docker requires lowercase repository names (GitHub usernames may be mixed case).
IMAGE_REGISTRY=$(echo "${IMAGE_REGISTRY:-$(get_env IMAGE_REGISTRY)}" | tr -d '[:space:]' | tr '[:upper:]' '[:lower:]')
API_IMAGE="${IMAGE_REGISTRY:+$IMAGE_REGISTRY/}api:$IMAGE_TAG"
WEB_IMAGE="${IMAGE_REGISTRY:+$IMAGE_REGISTRY/}web:$IMAGE_TAG"

if [[ -z $IMAGE_REGISTRY ]]; then
  API_IMAGE="hackmidwest-api:$IMAGE_TAG"
  WEB_IMAGE="hackmidwest-web:$IMAGE_TAG"
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
  sed -e "s|\${API_IMAGE}|${API_IMAGE}|g" -e "s|\${WEB_IMAGE}|${WEB_IMAGE}|g" "$1"
}

# db_id: optional managed Postgres labeled hackmidwest-db (workshop default).
db_id() {
  linode-cli databases postgresql-list --label hackmidwest-db --text --no-headers --format id 2>/dev/null || true
}
