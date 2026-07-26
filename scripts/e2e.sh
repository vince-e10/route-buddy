#!/bin/sh
set -eu

created_env=0
evidence_dir=$(mktemp -d)

cleanup() {
  status=$?
  if [ "$status" -ne 0 ]; then
    docker compose logs --tail 50 --no-color || true
  fi
  docker compose down -v || true
  rm -rf "$evidence_dir"
  if [ "$created_env" -eq 1 ]; then
    rm -f .env
  fi
  exit "$status"
}
trap cleanup EXIT INT TERM

if [ ! -f .env ]; then
  cp .env.example .env
  created_env=1
fi

docker compose down -v
docker compose config --quiet
cp docker-compose.yml "$evidence_dir/docker-compose.yml"
LLM_MODE=fake MOCK_DETERMINISTIC=1 WEBHOOK_SHARED_SECRET=e2e-webhook-secret FLOCI_STORAGE_MODE=memory \
  docker compose up -d --build

for attempt in $(seq 1 90); do
  iac_id=$(docker compose ps -aq iac)
  iac_state=$(docker inspect "$iac_id" --format '{{.State.Status}} {{.State.ExitCode}}' 2>/dev/null || true)
  if [ "$iac_state" = "exited 0" ] \
    && docker compose exec -T api python -c "from urllib.request import urlopen; assert urlopen('http://localhost:8000/healthz').status == 200; assert urlopen('http://mock-uber:8001/healthz').status == 200" 2>/dev/null \
    && docker compose exec -T api python -c "import boto3; assert set(boto3.client('dynamodb').list_tables()['TableNames']) == {'sessions', 'trips', 'action_log', 'pending_actions'}"; then
    break
  fi
  if [ "$attempt" -eq 90 ]; then
    echo "Route Buddy stack did not become ready within 180 seconds." >&2
    exit 1
  fi
  sleep 2
done

docker compose exec -T api id -u > "$evidence_dir/api-uid.txt"
docker compose exec -T mock-uber id -u > "$evidence_dir/mock-uber-uid.txt"
docker compose ps --format json > "$evidence_dir/compose-ps.jsonl"
docker compose exec -T api mkdir -p /tmp/route-buddy-e2e
docker compose cp "$evidence_dir/." api:/tmp/route-buddy-e2e

docker compose exec -T api python -m pytest tests -v
docker compose run --rm --no-deps -v "$PWD/mock-uber/tests:/tests:ro" mock-uber python -m pytest -p no:cacheprovider /tests -v
