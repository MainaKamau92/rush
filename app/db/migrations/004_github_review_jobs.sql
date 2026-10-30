CREATE TABLE github_deliveries (
    delivery_id TEXT PRIMARY KEY NOT NULL,
    payload_sha256 TEXT NOT NULL UNIQUE,
    event TEXT NOT NULL,
    outcome TEXT NOT NULL,
    job_id TEXT,
    received_at TEXT NOT NULL
);

CREATE TABLE review_jobs (
    job_id TEXT PRIMARY KEY NOT NULL,
    repository TEXT NOT NULL,
    pull_request INTEGER NOT NULL CHECK (pull_request > 0),
    installation_id INTEGER NOT NULL CHECK (installation_id > 0),
    head_sha TEXT,
    trigger TEXT NOT NULL,
    requested_by TEXT NOT NULL,
    status TEXT NOT NULL,
    reason TEXT NOT NULL,
    run_id TEXT,
    attempts INTEGER NOT NULL CHECK (attempts >= 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX review_jobs_by_status ON review_jobs (status, created_at);
CREATE INDEX review_jobs_by_pull_request ON review_jobs (repository, pull_request, status);
