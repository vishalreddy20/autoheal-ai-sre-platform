CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ── Auth users ────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS auth_users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  username TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'viewer' CHECK (role IN ('viewer', 'operator')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Default users are seeded programmatically by auth-service on startup
-- using bcrypt.hashpw() to guarantee hash correctness.
-- Placeholder rows below ensure the table structure is validated.
-- The auth-service _seed_default_users() function runs after pool init
-- and inserts admin/operator and viewer/viewer with ON CONFLICT DO NOTHING.

-- ── Users ─────────────────────────────────────────────────────────────────────
ALTER TABLE IF EXISTS users ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT NOT NULL,
  email TEXT UNIQUE NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  deleted_at TIMESTAMPTZ
);

-- ── Tasks ─────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS tasks (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending','in_progress','done','failed')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── Incidents (enhanced lifecycle schema) ─────────────────────────────────────
CREATE TABLE IF NOT EXISTS incidents (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  title TEXT,
  description TEXT,
  severity TEXT NOT NULL CHECK (severity IN ('low','medium','high','critical')),
  status TEXT NOT NULL DEFAULT 'open'
    CHECK (status IN ('open','acknowledged','investigating','mitigating','resolved')),
  service TEXT NOT NULL,
  issue_type TEXT,
  condition TEXT,
  healing_action TEXT,
  action_taken TEXT,
  assigned_to TEXT,
  resolved BOOLEAN NOT NULL DEFAULT FALSE,
  opened_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  detected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  acknowledged_at TIMESTAMPTZ,
  resolved_at TIMESTAMPTZ,
  root_cause TEXT,
  postmortem TEXT,
  linked_trace_id TEXT,
  metrics_snapshot JSONB DEFAULT '{}',
  timeline JSONB DEFAULT '[]',
  details JSONB NOT NULL DEFAULT '{}'
);

-- ── Metrics snapshots ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS metrics_snapshots (
  id BIGSERIAL PRIMARY KEY,
  service TEXT NOT NULL,
  error_rate NUMERIC(5,2),
  latency_p99_ms NUMERIC(10,2),
  request_count BIGINT,
  snapshot_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── Audit log ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS audit_log (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  service TEXT NOT NULL,
  action TEXT NOT NULL,
  result TEXT NOT NULL CHECK (result IN ('executed','dry_run','skipped','failed','cooldown','circuit_open','blast_radius')),
  triggered_by TEXT NOT NULL DEFAULT 'system',
  reason TEXT
);

-- ── Pending approvals ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS pending_approvals (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  service TEXT NOT NULL,
  action TEXT NOT NULL,
  condition TEXT NOT NULL,
  requested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  requested_by TEXT NOT NULL DEFAULT 'system',
  status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','approved','rejected')),
  resolved_at TIMESTAMPTZ,
  resolved_by TEXT
);

-- ── Indexes ───────────────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS incidents_service_detected_at_idx ON incidents(service, detected_at DESC);
CREATE INDEX IF NOT EXISTS incidents_status_idx ON incidents(status);
CREATE INDEX IF NOT EXISTS incidents_severity_idx ON incidents(severity);
CREATE INDEX IF NOT EXISTS metrics_snapshots_service_snapshot_at_idx ON metrics_snapshots(service, snapshot_at DESC);
CREATE INDEX IF NOT EXISTS audit_log_timestamp_idx ON audit_log(timestamp DESC);
CREATE INDEX IF NOT EXISTS audit_log_service_idx ON audit_log(service);
CREATE INDEX IF NOT EXISTS pending_approvals_status_idx ON pending_approvals(status);
