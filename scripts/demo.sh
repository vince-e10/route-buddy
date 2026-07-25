#!/bin/sh
set -eu

if [ ! -f .env ]; then
  echo "Missing .env. Copy .env.example to .env and set OPENROUTER_API_KEY, WEBHOOK_SHARED_SECRET, ONEMAP_EMAIL, and ONEMAP_PASSWORD." >&2
  exit 1
fi

docker compose up -d --build
for attempt in $(seq 1 30); do
  if curl --fail --silent http://localhost:8000/healthz >/dev/null; then
    echo "Route Buddy is ready at http://localhost:8000"
    echo "Try: Take me from Changi Airport to Marina Bay Sands"
    echo "Then: book UberX"
    echo "Later: cancel that one"
    exit 0
  fi
  sleep 2
done

docker compose logs --tail 50 --no-color
echo "Route Buddy did not become ready within 60 seconds." >&2
exit 1
