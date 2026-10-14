#!/usr/bin/env bash
# Checks that Caddy (with docker/Caddyfile) passes the answer stream through as it is sent:
# events unbuffered and uncompressed, other pages still compressed, and a client that goes
# away is noticed upstream (so Cancel reaches the API and the model). No models, database or
# Ollama: a stand-in plays the UI (docker/stream_check.py). Runs in CI (deploy job).
#   scripts/check_proxy_stream.sh            CADDYFILE=path/to/Caddyfile to check another one
#   STAND_IN_DEAF=1 scripts/check_proxy_stream.sh   self-check: the cancel step must then fail
#   TRUSTED_PROXIES=private_ranges scripts/check_proxy_stream.sh   the Cloudflare Tunnel setting:
#     a forwarded X-Forwarded-Proto must then reach the UI (by default Caddy replaces it)
set -euo pipefail
cd "$(dirname "$0")/.."

caddyfile="${CADDYFILE:-docker/Caddyfile}"
port="${CHECK_PORT:-18080}"
caddy_image="$(awk '/image: caddy/ {print $2; exit}' docker-compose.yml)"
python_image="python:3.13-alpine"
name="ej-stream-check-$$"

# Clean up however the script ends (inline, not a function: shellcheck versions disagree on
# how to report functions only a trap calls).
trap 'docker rm -f "$name-ui" "$name-caddy" >/dev/null 2>&1 || true
      docker network rm "$name" >/dev/null 2>&1 || true' EXIT

docker network create "$name" >/dev/null
docker run -d --name "$name-ui" --network "$name" --network-alias ui \
  -e STAND_IN_DEAF="${STAND_IN_DEAF:-0}" \
  -v "$PWD/docker/stream_check.py:/stream_check.py:ro" \
  "$python_image" python -u /stream_check.py serve >/dev/null
docker run -d --name "$name-caddy" --network "$name" -e SITE_ADDRESS=:80 \
  -e TRUSTED_PROXIES="${TRUSTED_PROXIES:-127.0.0.1/32}" \
  -p "127.0.0.1:$port:80" -v "$PWD/$caddyfile:/etc/caddy/Caddyfile:ro" \
  "$caddy_image" >/dev/null

base="http://127.0.0.1:$port"
for _ in $(seq 1 60); do
  curl -sf -o /dev/null "$base/" && break
  sleep 0.5
done
curl -sf -o /dev/null "$base/" || { echo "Caddy did not come up" >&2; docker logs "$name-caddy" >&2; exit 1; }

echo "checking $caddyfile with $caddy_image"
# The check sends X-Forwarded-Proto: https from the host, which reaches Caddy from the Docker
# network's gateway (a private address): kept only when private ranges are trusted.
expect=http
[[ -n "${TRUSTED_PROXIES:-}" ]] && expect=https
EXPECT_FORWARDED_PROTO="$expect" python3 docker/stream_check.py check "$base"

# Cancel while nothing is being sent (the model drafting): Caddy must close the upstream
# connection within 2 s of the client leaving, or the answer would run on.
python3 docker/stream_check.py cancel "$base"
for _ in $(seq 1 4); do
  if docker logs "$name-ui" 2>&1 | grep -q "upstream closed"; then
    echo "ok: $(docker logs "$name-ui" 2>&1 | grep "upstream closed") (the stream was silent)"
    exit 0
  fi
  sleep 0.5
done
echo "FAIL: the upstream was not closed when the client left a silent stream" >&2
docker logs "$name-ui" >&2
exit 1
