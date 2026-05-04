# AutoHeal AI — Self-Healing Microservices System

> **SRE portfolio platform** that demonstrates anomaly detection, recovery actions, and SLO tracking across a distributed microservices architecture.

---

## Architecture

```mermaid
graph TB
    subgraph Traffic
        LT[Locust / Users]
    end

    subgraph Gateway
        GW[API Gateway<br/>FastAPI :8000<br/>JWT Auth / Proxy]
    end

    subgraph Core Services
        AS[auth-service<br/>FastAPI :8004]
        US[user-service<br/>FastAPI :8001]
        TS[task-service<br/>FastAPI :8002]
    end

    subgraph Persistence
        SB[(Supabase PostgreSQL<br/>pgBouncer :6543)]
        RD[(Redis :6379<br/>Cooldowns / Limits)]
    end

    subgraph AutoHeal
        AH[AutoHeal Engine<br/>FastAPI :8003<br/>Policy Engine]
    end

    subgraph Observability
        PR[Prometheus :9090]
        AM[Alertmanager :9093]
        GR[Grafana :3000]
        JA[Jaeger :16686<br/>Distributed Tracing]
    end

    subgraph Frontend
        FE[React + Vite<br/>:5174<br/>SSE live updates]
    end

    LT --> FE
    LT --> GW
    FE -- SSE / REST --> GW
    
    GW --> AS
    GW --> US
    GW --> TS
    GW --> AH
    
    AS --> RD
    AH --> RD
    GW --> RD
    
    US --> SB
    TS --> SB
    AH --> SB
    AS --> SB
    
    PR -- scrape /metrics --> GW
    PR -- scrape /metrics --> US
    PR -- scrape /metrics --> TS
    PR -- scrape /metrics --> AS
    PR -- scrape /metrics --> AH
    
    PR --> AM
    AM -- webhooks --> AH
    GR --> PR
    
    AH -- Docker API --> GW
    AH -- Docker API --> US
    AH -- Docker API --> TS
    AH -- Docker API --> AS
    
    GW -- OTLP gRPC --> JA
    US -- OTLP gRPC --> JA
    TS -- OTLP gRPC --> JA
    AS -- OTLP gRPC --> JA
    AH -- OTLP gRPC --> JA

    style GW fill:#1A1D2E,stroke:#00D4AA,color:#fff
    style AH fill:#1A1D2E,stroke:#EF4444,color:#fff
    style FE fill:#1A1D2E,stroke:#818CF8,color:#fff
    style SB fill:#1A1D2E,stroke:#00D4AA,color:#fff
    style RD fill:#1A1D2E,stroke:#EF4444,color:#fff
```

---

## Non-Negotiable Guarantees

| Guarantee | Implementation |
|-----------|----------------|
| Secrets in `.env` only | `.gitignore` excludes `.env`; `.env.example` committed |
| SIGTERM graceful shutdown | `signal.signal(SIGTERM, handler)` in all services |
| `X-Request-ID` on every response | `RequestIDMiddleware` on all FastAPI apps |
| Parameterized DB queries | asyncpg `$1, $2, ...` syntax only |
| pgBouncer transaction mode | Port 6543, connection pooling |
| SSE not polling | `EventSource` in React, keep-alive every 15s |
| Rate limiting | `slowapi` 200 req/min per IP on gateway |
| CORS configured | `CORSMiddleware` with env-var origins |
| UTC timestamps | All `datetime.now(timezone.utc).isoformat()` |

---

## Prerequisites

- **Docker** 24+ and **Docker Compose** v2
- **Node.js** 20+ (for local frontend development only)
- **Supabase** account (free tier is sufficient)

---

## Supabase Setup

### 1. Create a Supabase project

Go to [supabase.com](https://supabase.com) → New Project → note the **Project Reference ID**.

### 2. Run the database migration

In your Supabase dashboard → **SQL Editor** → run:

```sql
-- Add deleted_at column for soft deletes
ALTER TABLE IF EXISTS users ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT NOT NULL,
  email TEXT UNIQUE NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  deleted_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS tasks (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending','in_progress','done','failed')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS incidents (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  service TEXT NOT NULL,
  issue_type TEXT NOT NULL,
  severity TEXT NOT NULL CHECK (severity IN ('low','medium','high','critical')),
  details JSONB NOT NULL DEFAULT '{}',
  action_taken TEXT,
  resolved BOOLEAN NOT NULL DEFAULT FALSE,
  detected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  resolved_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS metrics_snapshots (
  id BIGSERIAL PRIMARY KEY,
  service TEXT NOT NULL,
  error_rate NUMERIC(5,2),
  latency_p99_ms NUMERIC(10,2),
  request_count BIGINT,
  snapshot_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX ON incidents(service, detected_at DESC);
CREATE INDEX ON metrics_snapshots(service, snapshot_at DESC);
```

### 3. Get your pgBouncer connection string

Go to **Project Settings → Database → Connection string → Connection pooling**.  
Select **Transaction mode**, copy the URL (port **6543**).

Format:
```
postgresql://postgres.[ref]:[password]@aws-0-[region].pooler.supabase.com:6543/postgres
```

For asyncpg, prefix with `postgresql+asyncpg://`.

---

## Quick Start

```bash
# 1. Clone and enter the project
cd autoheal-ai

# 2. Copy and fill in environment variables
cp .env.example .env
# Edit .env: set SUPABASE_DB_URL and SUPABASE_DB_URL_REPLICA

# 3. Build and start all services
docker compose up --build -d

# 4. Wait for all services to be healthy (30-60s)
docker compose ps

# 5. Verify
curl localhost:8000/health
# → {"status":"ok","service":"api-gateway","ts":"..."}
```

---

## Service URLs

| Service | URL | Description |
|---------|-----|-------------|
| **Frontend Dashboard** | http://localhost:5174 | React SPA — main UI |
| **API Gateway** | http://localhost:8000 | REST API + SSE stream |
| **API Docs** | http://localhost:8000/docs | FastAPI Swagger UI |
| **Auth Service** | http://localhost:8004 | JWT auth and RBAC |
| **User Service** | http://localhost:8001 | Direct user CRUD |
| **Task Service** | http://localhost:8002 | Direct task CRUD |
| **AutoHeal Engine** | http://localhost:8003 | Engine health/metrics |
| **Prometheus** | http://localhost:9090 | Metrics scraping UI |
| **Alertmanager** | http://localhost:9093 | Alerts routing |
| **Grafana** | http://localhost:3000 | Dashboards (admin/admin) |
| **Jaeger UI** | http://localhost:16686 | Distributed traces |
| **Locust UI** | http://localhost:8089 | Load test runner |

---

## Ports Reference

| Service | Internal Port | Exposed Port |
|---------|---------------|--------------|
| Frontend | 80 | 5174 |
| API Gateway | 8000 | 8000 |
| Auth Service | 8004 | 8004 |
| User Service | 8001 | 8001 |
| Task Service | 8002 | 8002 |
| AutoHeal Engine | 8003 | 8003 |
| Prometheus | 9090 | 9090 |
| Alertmanager | 9093 | 9093 |
| Grafana | 3000 | 3000 |
| Jaeger | 16686/4317 | 16686/14317 |
| Redis | 6379 | 6379 |
| Postgres | 5432/6543 | 5432/6543 |

---

## Demo Walkthrough (Interviewer Guide)

### Step 1 — Verify normal operation
```bash
curl localhost:8000/health          # Gateway healthy
curl localhost:8001/health          # User service connected
curl localhost:8002/health          # Task service connected
```
Open http://localhost:5174 → Dashboard shows all services green.

### Step 2 — Simulate DB failure
```bash
curl -X POST localhost:8000/simulate/db-down \
  -H "Authorization: Bearer <admin_token>"
```
→ user-service and task-service return 503  
→ AutoHeal Engine detects within 5s → creates `critical` incident  
→ Dashboard Incidents tab shows new incident (real-time via SSE)

### Step 3 — Watch AutoHeal restore
```bash
curl -X POST localhost:8000/simulate/db-restore \
  -H "Authorization: Bearer <admin_token>"
```
→ AutoHeal marks incident as resolved  
→ Dashboard shows incident resolved with timestamp

### Step 4 — Inject latency
```bash
curl -X POST localhost:8000/simulate/slow \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer <admin_token>" \
  -d '{"service":"user-service","delay_ms":800}'
```
→ AutoHeal detects P99 > 500ms  
→ Executes THROTTLE_TRAFFIC action  
→ Monitors recovery and auto-restores after 60s

### Step 5 — Run load test
Open http://localhost:8089  
Set users=100, spawn rate=10, host=http://api-gateway:8000 → Start  
Watch Grafana dashboard: http://localhost:3000  
Watch traces in Jaeger: http://localhost:16686

### Step 6 — Simulate service restart
```bash
curl -X POST localhost:8000/simulate/service-down \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer <admin_token>" \
  -d '{"service":"user-service"}'
```
→ AutoHeal detects 3 consecutive health failures  
→ Calls Docker API to restart container  
→ Polls /health every 5s until recovery (max 30s)

---

## Load Testing

| Scenario | Command |
|----------|---------|
| Low (10 users) | `docker compose exec locust locust -u 10 -r 2 --headless -t 60s --host http://api-gateway:8000 -f /mnt/locust/locustfile.py` |
| Medium (100 users) | `docker compose exec locust locust -u 100 -r 10 --headless -t 60s --host http://api-gateway:8000 -f /mnt/locust/locustfile.py` |
| High (500 users) | `docker compose exec locust locust -u 500 -r 50 --headless -t 60s --host http://api-gateway:8000 -f /mnt/locust/locustfile.py` |

Or use the **Locust Web UI** at http://localhost:8089.

---

## Running Tests

The test suite is integration-oriented and expects the Docker Compose stack to be running.

```bash
cd tests
pip install -r requirements.txt
pytest -v
# Windows launcher alternative:
py -m pytest -v
```

---

## SLO Definitions

| SLO | Target | Metric |
|-----|--------|--------|
| **Latency** | P95 < 200ms | `histogram_quantile(0.95, rate(request_latency_seconds_bucket[5m]))` |
| **Availability** | 99% uptime / 24h | Health check success rate |
| **Error Rate** | < 1% over 5m rolling | `rate(5xx) / rate(all)` |

---

## AutoHeal Detection Rules

| Rule | Threshold | Action |
|------|-----------|--------|
| Error Rate | > 5% over 1m | `RESTART_SERVICE` |
| P99 Latency | > 500ms | `THROTTLE_TRAFFIC` |
| Health Check | 3 consecutive failures | `RESTART_SERVICE` |
| DB Connectivity | Timeout > 5s | `DB_FAILOVER` |
| SLO Violation | P95 > 200ms | `LOG_INCIDENT` |

---

## Monitoring

- **Grafana** at :3000 — auto-provisioned dashboard with 7 panels (request rate, error rate, P99 latency, service UP/DOWN, DB pool, incidents, SLO gauge)
- **Prometheus** at :9090 — 5s scrape interval, 7-day retention
- **Jaeger** at :16686 — full distributed traces with OTLP gRPC
- **Alertmanager** at :9093 — routing critical alerts

---

## Troubleshooting

### DB connection errors on startup
```bash
pool_creation_failed: could not connect to server
```
**Cause**: Invalid Supabase URL or wrong port  
**Fix**: Ensure `SUPABASE_DB_URL` uses port **6543** (pgBouncer) not 5432  
The URL must be prefixed with `postgresql+asyncpg://`

### Docker socket permission errors
```
docker.errors.DockerException: Error while fetching server API version
```
**Fix** (Linux/Mac):
```bash
sudo chmod 666 /var/run/docker.sock
```
On Windows: Ensure Docker Desktop is running and socket is exposed.

### SSE shows "Disconnected"
The frontend SSE connects to `VITE_SSE_URL` (default: `http://localhost:8000/stream/events`).  
Check: `curl -N localhost:8000/stream/events`

### Services not healthy after startup
Allow 30-60 seconds for initial startup. Watch logs:
```bash
docker compose logs -f api-gateway
docker compose logs -f autoheal-engine
```

### Grafana shows no data
Prometheus may not have scraped yet. Wait 15-30s then refresh.  
Check Prometheus targets: http://localhost:9090/targets

---

## Project Structure

```text
autoheal-ai/
├── .env                          # Real credentials (gitignored)
├── .env.example                  # Template (committed)
├── .gitignore
├── docker-compose.yml            # Production compose
├── docker-compose.override.yml   # Dev hot-reload overrides
├── README.md
├── services/
│   ├── api-gateway/              # FastAPI :8000 — proxy, SSE, circuit breaker
│   ├── auth-service/             # FastAPI :8004 — JWT auth, RBAC
│   ├── user-service/             # FastAPI :8001 — user CRUD
│   ├── task-service/             # FastAPI :8002 — task CRUD
│   └── autoheal-engine/          # FastAPI :8003 — detection + healing daemon
├── monitoring/
│   ├── prometheus/prometheus.yml # Scrape config
│   ├── alertmanager/             # Alert routing
│   └── grafana/                  # Auto-provisioned datasource + dashboard
├── load-testing/
│   └── locustfile.py             # NormalUser + HeavyUser scenarios
└── frontend/                     # React 18 + Vite + Tailwind + Chart.js
  └── src/
    ├── pages/                # Dashboard, Incidents, Controls, SLO
    ├── components/           # ServiceStatusCard, MetricsChart, etc.
    ├── hooks/                # useSSE (auto-reconnect), useMetrics
    └── store/                # Zustand dashboard store
```

---

## Final Positioning

This platform demonstrates production SRE patterns in a reproducible local environment. It implements real observability (Prometheus metrics, Grafana dashboards, Jaeger distributed tracing), automated health checks, chaos simulation, incident logging, and a self-healing engine. It is designed as a portfolio demonstration of SRE principles rather than a hardened production deployment.

## Known Limitations & Future Work

- Healing actions use Docker socket access, which is not available in managed Kubernetes without privileged pods.
- DB failover requires pre-configured read replicas in production.
- Tests are integration tests requiring running services; unit tests with mocks are a future addition.
- Alertmanager webhook is local; production would route to PagerDuty/OpsGenie.

---

## License

MIT — Built for SRE portfolio demonstration.
