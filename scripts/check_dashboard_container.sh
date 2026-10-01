#!/usr/bin/env bash
set -euo pipefail
IMAGE=${1:?Specify the dashboard image}
CONTAINER=$(docker run -d --platform linux/amd64 -e PORT=8090 "$IMAGE")
trap 'docker rm -f "$CONTAINER" >/dev/null' EXIT
for attempt in {1..30}; do
  if docker exec "$CONTAINER" python -c "import urllib.request; assert urllib.request.urlopen('http://127.0.0.1:8090/_stcore/health', timeout=2).read() == b'ok'" 2>/dev/null; then
    docker exec "$CONTAINER" python -c "import os; assert os.getuid() == 10001"
    echo "PASS: custom PORT=8090 health endpoint; UID=10001; no cloud credentials"
    exit 0
  fi
  sleep 1
done
docker logs "$CONTAINER"
exit 1
