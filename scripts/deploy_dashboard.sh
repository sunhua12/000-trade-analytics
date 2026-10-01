#!/usr/bin/env bash
# Prerequisites and runtime IAM are documented in docs/day18-cloud-run-manual.md.
set -euo pipefail
PROJECT=${TRADE_BQ_PROJECT:-trade-analytics-508604}
REGION=${TRADE_RUN_REGION:-asia-northeast1}
SERVICE=${TRADE_RUN_SERVICE:-trade-dashboard}
REPOSITORY=${TRADE_RUN_REPOSITORY:-trade-dashboard}
RUNTIME_SA="trade-dashboard-runtime@${PROJECT}.iam.gserviceaccount.com"
GIT_SHA=$(git rev-parse HEAD)
SOURCE_HASH=$(python3 -c 'import hashlib,pathlib; h=hashlib.sha256(); paths=[pathlib.Path("Dockerfile.dashboard"),pathlib.Path("dashboard.py"),pathlib.Path("pyproject.toml"),*sorted(pathlib.Path("src").rglob("*.py"))]; [(h.update(str(p).encode()),h.update(p.read_bytes())) for p in paths]; print(h.hexdigest()[:16])')
IMAGE="${REGION}-docker.pkg.dev/${PROJECT}/${REPOSITORY}/dashboard"
TAG="${GIT_SHA}-${SOURCE_HASH}"
# Explicit source hash distinguishes uncommitted source from its base commit.
gcloud auth configure-docker "${REGION}-docker.pkg.dev" --quiet
docker build --platform linux/amd64 --provenance=false -f Dockerfile.dashboard -t "${IMAGE}:${TAG}" .
docker push "${IMAGE}:${TAG}"
DIGEST=$(gcloud artifacts docker images describe "${IMAGE}:${TAG}" --project="$PROJECT" --format='value(image_summary.digest)')
[[ "$DIGEST" == sha256:* ]]
gcloud run deploy "$SERVICE" --project="$PROJECT" --region="$REGION" \
  --image="${IMAGE}@${DIGEST}" --service-account="$RUNTIME_SA" \
  --port=8080 --cpu=1 --memory=1Gi --concurrency=10 --timeout=3600 \
  --min=0 --max=1 --min-instances=0 --max-instances=1 \
  --allow-unauthenticated --ingress=all \
  --set-env-vars="TRADE_BQ_PROJECT=${PROJECT},TRADE_BQ_LOCATION=${TRADE_BQ_LOCATION:-asia-northeast1},TRADE_BQ_MAX_BYTES_BILLED=1000000000,TRADE_DASHBOARD_CACHE_TTL=3600,TRADE_DASHBOARD_FIRST_MONTH=2023-01-01,TRADE_DASHBOARD_AFTER_LAST_MONTH=${TRADE_DASHBOARD_AFTER_LAST_MONTH:-2025-05-01}" \
  --labels="source-sha=${GIT_SHA},source-hash=${SOURCE_HASH}" --quiet
mkdir -p docs/evidence/day18
gcloud run services describe "$SERVICE" --project="$PROJECT" --region="$REGION" --format=json > docs/evidence/day18/service.json
gcloud run services get-iam-policy "$SERVICE" --project="$PROJECT" --region="$REGION" --format=json > docs/evidence/day18/service-iam.json
printf 'Base Git SHA: %s\nSource hash: %s\nImage: %s@%s\n' "$GIT_SHA" "$SOURCE_HASH" "$IMAGE" "$DIGEST"
