CREATE TABLE model_config_versions (
    id uuid PRIMARY KEY,
    profile text NOT NULL,
    fingerprint text NOT NULL UNIQUE,
    ciphertext bytea,
    created_at timestamptz NOT NULL DEFAULT now(),
    revoked_at timestamptz,
    CHECK ((ciphertext IS NULL) = (revoked_at IS NOT NULL))
);

CREATE TABLE task_runner (
    singleton boolean PRIMARY KEY DEFAULT TRUE CHECK (singleton),
    run_id uuid NOT NULL
);

CREATE TABLE analysis_tasks (
    id text PRIMARY KEY,
    owner_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    config_version_id uuid NOT NULL REFERENCES model_config_versions(id),
    idempotency_key text,
    query text NOT NULL,
    status text NOT NULL CHECK (status IN ('pending', 'running', 'completed', 'degraded', 'error', 'interrupted')),
    snapshot jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    deleted_at timestamptz,
    cleanup_pending boolean NOT NULL DEFAULT FALSE CHECK (NOT cleanup_pending OR deleted_at IS NOT NULL),
    UNIQUE (owner_id, idempotency_key),
    UNIQUE (id, owner_id)
);

CREATE INDEX analysis_tasks_history_idx ON analysis_tasks (owner_id, created_at DESC, id DESC) WHERE deleted_at IS NULL;
CREATE INDEX analysis_tasks_active_idx ON analysis_tasks (owner_id) WHERE status IN ('pending', 'running') AND deleted_at IS NULL;

CREATE TABLE report_documents (
    task_id text PRIMARY KEY,
    owner_id uuid NOT NULL,
    document_id uuid NOT NULL UNIQUE,
    stock_code text NOT NULL,
    report_date date,
    markdown_path text NOT NULL,
    pdf_path text NOT NULL,
    pdf_status text NOT NULL CHECK (pdf_status IN ('ready', 'pending', 'failed', 'unavailable')),
    content_version integer NOT NULL DEFAULT 1,
    FOREIGN KEY (task_id, owner_id) REFERENCES analysis_tasks(id, owner_id) ON DELETE CASCADE
);
