#!/usr/bin/env bash
# Local director console: API on :18765, UI on :3101
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

python3 -m pip install -q -r requirements.txt
(
  cd studio
  if [[ ! -d node_modules ]]; then
    npm install
  fi
)

export DIRECTOR_API_PORT="${DIRECTOR_API_PORT:-18765}"
python3 scripts/director_server.py &
api_pid=$!
cleanup() {
  kill "$api_pid" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# wait until health
for _ in 1 2 3 4 5 6 7 8 9 10; do
  if curl -sf "http://127.0.0.1:${DIRECTOR_API_PORT}/api/health" >/dev/null; then
    break
  fi
  sleep 0.3
done

echo "Director API  http://127.0.0.1:${DIRECTOR_API_PORT}/api/health"
echo "Director UI   http://127.0.0.1:3101"
cd studio
npm run dev
