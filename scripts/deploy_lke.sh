#!/usr/bin/env bash
# Deploy api + web + agents on Akamai LKE, with managed PostgreSQL.
# Adapted from the workshop deploy_lke.sh for this repo.
#
# Prerequisites:
#   - linode-cli configured, kubectl, docker
#   - .env with at least IMAGE_REGISTRY (and any API secrets you need)
#   - docker logged in to that registry
#
#   bash scripts/deploy_lke.sh
#
# Reuses cluster label hackmidwest-lke. Builds/pushes images unless SKIP_BUILD=1.
# Creates or reuses managed Postgres hackmidwest-db and writes DATABASE_URL.
set -euo pipefail
source "$(dirname "$0")/lib.sh"
start=$(date +%s)
elapsed() { echo "$(( ($(date +%s) - start) / 60 )) min $(( ($(date +%s) - start) % 60 )) s"; }

need() {
  if ! command -v "$1" >/dev/null; then
    echo "$1 not found. $2"
    exit 1
  fi
}

need kubectl "Install: https://kubernetes.io/docs/tasks/tools/"
need linode-cli "Install and configure the Linode CLI."
need docker "Install Docker to build and push images."

if [[ -z $(get_env IMAGE_REGISTRY) && -z ${IMAGE_REGISTRY:-} ]]; then
  echo "IMAGE_REGISTRY is required (set it in .env)."
  echo "Example: IMAGE_REGISTRY=ghcr.io/your-user/hackmidwest-2026"
  exit 1
fi
# Re-resolve images now that IMAGE_REGISTRY is known to be set.
IMAGE_REGISTRY=$(echo "${IMAGE_REGISTRY:-$(get_env IMAGE_REGISTRY)}" | tr -d '[:space:]' | tr '[:upper:]' '[:lower:]')
API_IMAGE="$IMAGE_REGISTRY/api:$IMAGE_TAG"
WEB_IMAGE="$IMAGE_REGISTRY/web:$IMAGE_TAG"
AGENTS_IMAGE="$IMAGE_REGISTRY/agents:$IMAGE_TAG"

echo "API image:    $API_IMAGE"
echo "Web image:    $WEB_IMAGE"
echo "Agents image: $AGENTS_IMAGE"

# 1. Cluster: one node on the newest Kubernetes version LKE offers.
cluster_id=$(linode-cli lke clusters-list --label "$LKE_LABEL" --text --no-headers --format id)
if [[ -z $cluster_id ]]; then
  version=$(linode-cli lke versions-list --text --no-headers --format id | head -n 1)
  cluster_id=$(linode-cli lke cluster-create --label "$LKE_LABEL" --region "$REGION" --k8s_version "$version" \
    --node_pools.type "$LINODE_TYPE" --node_pools.count 1 --text --no-headers --format id)
  echo "Created LKE cluster $LKE_LABEL (id $cluster_id) on Kubernetes $version ($LINODE_TYPE)."
else
  echo "LKE cluster $LKE_LABEL already exists (id $cluster_id)."
fi

# 2. Kubeconfig (credential — gitignored).
kubeconfig() { linode-cli lke kubeconfig-view "$cluster_id" --text --no-headers; }
wait_for 600 "the cluster's kubeconfig" kubeconfig
kubeconfig | python3 -c 'import base64, sys; sys.stdout.buffer.write(base64.b64decode(sys.stdin.read()))' > "$KUBECONFIG_FILE"
chmod 600 "$KUBECONFIG_FILE"
export KUBECONFIG="$REPO/$KUBECONFIG_FILE"
node_ready() { kubectl get nodes --no-headers 2>/dev/null | grep -q " Ready "; }
wait_for 900 "a Ready node" node_ready
echo "$(elapsed): the node is Ready."

# 3. Managed Postgres: create/reuse, wait active, write DATABASE_URL.
if [[ ${SKIP_DB:-0} != 1 ]]; then
  ensure_database
  echo "$(elapsed): database ready."
else
  echo "SKIP_DB=1 — using existing DATABASE_URL in .env (if set)."
fi

# 4. Build linux/amd64 images and push (skip with SKIP_BUILD=1 when tags already exist).
# LKE workers are amd64; Apple Silicon defaults to arm64. Build with buildx --load, then
# docker push so host GHCR credentials (Docker Desktop credsStore) are used.
if [[ ${SKIP_BUILD:-0} != 1 ]]; then
  echo "Building and pushing linux/amd64 images..."
  BUILDX="${BUILDX:-$HOME/.docker/cli-plugins/docker-buildx}"
  if [[ ! -x $BUILDX ]] && ! command -v docker-buildx >/dev/null; then
    echo "docker buildx plugin not found at $BUILDX"
    exit 1
  fi
  [[ -x $BUILDX ]] || BUILDX=$(command -v docker-buildx)
  PLATFORM=${PLATFORM:-linux/amd64}
  "$BUILDX" build --platform "$PLATFORM" -t "$API_IMAGE" --load "$REPO/api"
  docker push "$API_IMAGE"
  "$BUILDX" build --platform "$PLATFORM" -t "$WEB_IMAGE" --build-arg NEXT_PUBLIC_API_URL=/backend --load "$REPO/web"
  docker push "$WEB_IMAGE"
  "$BUILDX" build --platform "$PLATFORM" -t "$AGENTS_IMAGE" --load "$REPO/services/agents"
  docker push "$AGENTS_IMAGE"
  echo "$(elapsed): images pushed ($PLATFORM)."
else
  echo "SKIP_BUILD=1 — using existing $API_IMAGE, $WEB_IMAGE, $AGENTS_IMAGE."
fi

# 5. Namespace + Secret from .env (IMAGE_REGISTRY is not needed inside the pods).
kubectl create namespace "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f - >/dev/null
tmp_env=$(mktemp)
grep -vE '^(IMAGE_REGISTRY|IMAGE_TAG)=' .env | tr -d '\r' > "$tmp_env" || true
kubectl -n "$NAMESPACE" create secret generic app-env --from-env-file="$tmp_env" --dry-run=client -o yaml \
  | kubectl apply -f - >/dev/null
rm -f "$tmp_env"

# 6. Allow the worker node into managed Postgres.
node_ip=$(kubectl get nodes -o jsonpath='{.items[0].status.addresses[?(@.type=="ExternalIP")].address}' \
  | tr ' ' '\n' | grep -E '^[0-9.]+$' | head -n 1)
id=$(db_id)
if [[ -n $id && -n $(get_env DATABASE_URL) && -n $node_ip ]]; then
  allowed=$(linode-cli databases postgresql-view "$id" --text --no-headers --format allow_list | tr ',' ' ')
  if [[ " $allowed " != *" $node_ip/32 "* ]]; then
    args=()
    for address in $allowed "$node_ip/32"; do
      [[ -n $address ]] && args+=(--allow_list "$address")
    done
    linode-cli databases postgresql-update "$id" "${args[@]}" >/dev/null
    echo "$(elapsed): added the node, $node_ip/32, to the Postgres allow list."
  fi
fi

# 7. Apply workloads. Restart on rerun so new images/env are picked up.
existed=$(kubectl -n "$NAMESPACE" get deployment api -o name 2>/dev/null || true)
render_manifest k8s/agents.yaml | kubectl apply -f -
render_manifest k8s/api.yaml | kubectl apply -f -
render_manifest k8s/web.yaml | kubectl apply -f -
kubectl apply -f k8s/service.yaml
if [[ -n $existed ]]; then
  kubectl -n "$NAMESPACE" rollout restart deployment/api deployment/web deployment/agents
fi
kubectl -n "$NAMESPACE" rollout status deployment/agents --timeout=600s
kubectl -n "$NAMESPACE" rollout status deployment/api --timeout=600s
kubectl -n "$NAMESPACE" rollout status deployment/web --timeout=600s

# 8. Wait for NodeBalancer, rename for cleanup visibility.
lb_ip() { kubectl -n "$NAMESPACE" get service web -o jsonpath='{.status.loadBalancer.ingress[0].ip}'; }
has_lb_ip() { [[ -n $(lb_ip) ]]; }
wait_for 600 "the cluster to create a NodeBalancer" has_lb_ip
nb_ip=$(lb_ip)
nb_id=$(linode-cli nodebalancers list --ipv4 "$nb_ip" --text --no-headers --format id)
named=$(linode-cli nodebalancers list --label "$NB_LABEL" --text --no-headers --format id)
if [[ -n $named && $named != "$nb_id" ]]; then
  echo "Another NodeBalancer is already named $NB_LABEL (id $named). Delete it or change NB_LABEL."
  exit 1
elif [[ -z $named ]]; then
  linode-cli nodebalancers update "$nb_id" --label "$NB_LABEL" >/dev/null
  echo "$(elapsed): named the cluster's NodeBalancer $NB_LABEL (id $nb_id)."
fi

# 9. Verify through the public web Service and in-cluster agents.
healthy() { curl -sf --max-time 5 "http://$nb_ip/backend/health"; }
wait_for 600 "http://$nb_ip/backend/health" healthy
agents_healthy() {
  kubectl -n "$NAMESPACE" run "agents-health-$$" --rm -i --restart=Never --image=curlimages/curl:8.5.0 -- \
    curl -sf --max-time 5 "http://agents:8000/health" >/dev/null
}
if agents_healthy; then
  echo "$(elapsed): agents /health OK in-cluster."
else
  echo "Warning: could not probe agents in-cluster; check: kubectl -n $NAMESPACE logs deploy/agents"
fi

echo
healthy | python3 -m json.tool
echo
echo "App is up on LKE after $(elapsed):"
echo "  Web:     http://$nb_ip"
echo "  API:     http://$nb_ip/backend/health"
echo "  Agents:  ClusterIP http://agents:8000/health (in-cluster)"
echo "  Postgres: managed $DB_LABEL (DATABASE_URL in .env / app-env Secret)"
echo "kubectl: export KUBECONFIG=$REPO/$KUBECONFIG_FILE"
