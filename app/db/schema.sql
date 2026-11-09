-- File metadata. Composite PK starts with customer_id so every lookup is tenant-scoped
-- and index-only for the hot path.
CREATE TABLE IF NOT EXISTS files (
    customer_id   TEXT        NOT NULL,
    file_id       TEXT        NOT NULL,
    object_key    TEXT        NOT NULL,
    filename      TEXT        NOT NULL,
    content_type  TEXT        NOT NULL,
    size_bytes    BIGINT      NOT NULL CHECK (size_bytes >= 0),
    status        TEXT        NOT NULL DEFAULT 'available'  -- 'pending_scan' used once upload scanning is added
                  CHECK (status IN ('pending_scan', 'available', 'quarantined', 'deleted')),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (customer_id, file_id)
);

CREATE INDEX IF NOT EXISTS files_customer_recent
    ON files (customer_id, created_at DESC) WHERE status = 'available';

-- Accounts are provisioned by an administrator; there is no public signup endpoint.
CREATE TABLE IF NOT EXISTS users (
    username      TEXT        PRIMARY KEY,
    customer_id   TEXT        NOT NULL,
    password_hash TEXT        NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Only SHA-256 hashes of random, unguessable session tokens are stored.
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT        PRIMARY KEY,
    username   TEXT        NOT NULL REFERENCES users (username) ON DELETE CASCADE,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS sessions_expiry ON sessions (expires_at);

-- Least-privilege role for the service. It can read file metadata and accounts and manage
-- sessions, nothing else. Give it to the app's login user once per environment, e.g. the
-- Cloud SQL IAM user from `terraform output db_iam_user`:
--   GRANT file_service_app TO "fs-dev-files@<project>.iam";
DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'file_service_app') THEN
    CREATE ROLE file_service_app NOLOGIN;
  END IF;
END
$$;
GRANT SELECT ON files, users TO file_service_app;
GRANT SELECT, INSERT, DELETE ON sessions TO file_service_app;

-- Optional hardening: row-level security so even a buggy query can't cross tenants.
-- ALTER TABLE files ENABLE ROW LEVEL SECURITY;
-- CREATE POLICY tenant_isolation ON files USING (customer_id = current_setting('app.customer_id'));
