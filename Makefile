.PHONY: up down logs rebuild test lint seed-users token

# ── Docker lifecycle ──────────────────────────────────────────────────────────
up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f

rebuild: down
	docker compose up -d --build --force-recreate

# ── Testing ───────────────────────────────────────────────────────────────────
test:
	pip install -q -r tests/requirements.txt && \
	pytest tests/unit tests/integration -v --tb=short

test-cov:
	pip install -q -r tests/requirements.txt && \
	pytest tests/ --cov=services --cov-report=term-missing --cov-fail-under=80

lint:
	pip install -q ruff && ruff check services/ tests/

# ── Database ──────────────────────────────────────────────────────────────────
seed-users:
	@echo "Seeding default users (admin/operator, viewer/viewer) via init.sql..."
	@grep -E "psql|supabase" .env | head -1 || true
	@echo "Run init.sql against your Supabase DB manually if needed."

migrate:
	@echo "Applying init.sql to Supabase..."
	@export $$(grep -v '^#' .env | xargs) && \
	PGPASSWORD=$$(echo $$SUPABASE_DB_URL | sed 's|.*:\(.*\)@.*|\1|') \
	psql "$$SUPABASE_DB_URL" -f init.sql

# ── Auth helpers ──────────────────────────────────────────────────────────────
token-admin:
	@curl -s -X POST http://localhost:8000/auth/login \
	  -H "Content-Type: application/json" \
	  -d '{"username":"admin","password":"admin123"}' | python3 -m json.tool

token-viewer:
	@curl -s -X POST http://localhost:8000/auth/login \
	  -H "Content-Type: application/json" \
	  -d '{"username":"viewer","password":"viewer123"}' | python3 -m json.tool

# ── Observability ─────────────────────────────────────────────────────────────
open-grafana:
	@echo "Opening Grafana at http://localhost:3000"
	@start http://localhost:3000 2>/dev/null || open http://localhost:3000 2>/dev/null || true

open-jaeger:
	@echo "Opening Jaeger at http://localhost:16686"
	@start http://localhost:16686 2>/dev/null || open http://localhost:16686 2>/dev/null || true

open-prometheus:
	@echo "Opening Prometheus at http://localhost:9090"
	@start http://localhost:9090 2>/dev/null || open http://localhost:9090 2>/dev/null || true

# ── Status checks ─────────────────────────────────────────────────────────────
health:
	@echo "=== API Gateway ===" && \
	curl -s http://localhost:8000/health | python3 -m json.tool && \
	echo "=== Auth Service ===" && \
	curl -s http://localhost:8004/health | python3 -m json.tool && \
	echo "=== AutoHeal Engine ===" && \
	curl -s http://localhost:8003/health | python3 -m json.tool

# ── Dry run mode ──────────────────────────────────────────────────────────────
dry-run-on:
	HEALING_DRY_RUN=true docker compose up -d --no-recreate

# ── Approvals ─────────────────────────────────────────────────────────────────
pending-approvals:
	@TOKEN=$$(curl -s -X POST http://localhost:8000/auth/login \
	  -H "Content-Type: application/json" \
	  -d '{"username":"admin","password":"admin123"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['token'])"); \
	curl -s http://localhost:8003/approvals \
	  -H "x-user-role: operator" \
	  -H "x-user-id: admin" | python3 -m json.tool

# ── SLO status ────────────────────────────────────────────────────────────────
slo-status:
	@curl -s http://localhost:8003/slo/burn-rates | python3 -m json.tool

audit-log:
	@curl -s "http://localhost:8003/audit-log?limit=20" | python3 -m json.tool
