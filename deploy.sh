#!/usr/bin/env bash
# deploy.sh — pull, build, migrate, restart
# Usage: ./deploy.sh [--no-build]
set -euo pipefail

COMPOSE="docker compose -f docker-compose.prod.yml"

# ── Env check ────────────────────────────────────────────────────────────────
if [[ ! -f .env ]]; then
  echo "ERROR: .env not found. Copy .env.example and fill in POSTGRES_PASSWORD and SLACK_WEBHOOK_URL."
  exit 1
fi

if ! grep -q "POSTGRES_PASSWORD=" .env || grep -q "POSTGRES_PASSWORD=$" .env; then
  echo "ERROR: POSTGRES_PASSWORD not set in .env"
  exit 1
fi

# ── Build ─────────────────────────────────────────────────────────────────────
if [[ "${1:-}" != "--no-build" ]]; then
  echo "==> Building images..."
  $COMPOSE build --pull
fi

# ── Start DB + Redis first ─────────────────────────────────────────────────────
echo "==> Starting dependencies..."
$COMPOSE up -d postgres redis
echo "==> Waiting for postgres to be healthy..."
until $COMPOSE exec -T postgres pg_isready -U pricechecker -d pricechecker &>/dev/null; do
  sleep 2
done

# ── Alembic migrations ────────────────────────────────────────────────────────
echo "==> Running database migrations..."
$COMPOSE run --rm backend alembic upgrade head

# ── Start all services ────────────────────────────────────────────────────────
echo "==> Starting all services..."
$COMPOSE up -d

# ── Health check ──────────────────────────────────────────────────────────────
echo "==> Waiting for backend to be healthy..."
for i in $(seq 1 30); do
  if $COMPOSE exec -T backend curl -sf http://localhost:8000/api/products &>/dev/null; then
    echo "==> Backend is up."
    break
  fi
  if [[ $i -eq 30 ]]; then
    echo "ERROR: Backend did not become healthy after 60s. Check logs:"
    $COMPOSE logs --tail=50 backend
    exit 1
  fi
  sleep 2
done

echo ""
echo "✓  Deployed. Services:"
$COMPOSE ps
echo ""
echo "  App:  https://amazonscraper.viet.bui"
echo "  Docs: https://docs.amazonscraper.viet.bui"
echo ""
echo "  To trust the Caddy CA on this machine:"
echo "    docker compose -f docker-compose.prod.yml cp caddy:/data/caddy/pki/authorities/local/root.crt ./caddy-root.crt"
echo "    sudo cp caddy-root.crt /usr/local/share/ca-certificates/caddy-root.crt"
echo "    sudo update-ca-certificates"
