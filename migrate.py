import asyncio
import asyncpg
import os

from dotenv import load_dotenv

load_dotenv()

async def run_migration():
    dsn = os.getenv("SUPABASE_DB_URL")
    if not dsn:
        print("Missing SUPABASE_DB_URL")
        return

    # Clean the SQLAlchemy prefix if any
    dsn = dsn.replace("postgresql+asyncpg://", "postgresql://")
    print(f"Connecting to database...")

    try:
        conn = await asyncpg.connect(dsn)
        print("Connected successfully. Running migration...")

        await conn.execute("""
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

        CREATE INDEX IF NOT EXISTS incidents_service_detected_at_idx ON incidents(service, detected_at DESC);
        CREATE INDEX IF NOT EXISTS metrics_snapshots_service_snapshot_at_idx ON metrics_snapshots(service, snapshot_at DESC);
        """)

        print("Migration complete!")
        await conn.close()
    except Exception as e:
        print(f"Migration failed: {e}")

if __name__ == "__main__":
    asyncio.run(run_migration())
