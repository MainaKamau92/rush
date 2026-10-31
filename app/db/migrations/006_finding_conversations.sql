ALTER TABLE review_jobs ADD COLUMN comment_id INTEGER;
ALTER TABLE review_jobs ADD COLUMN request TEXT;

CREATE TABLE finding_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    repository TEXT NOT NULL,
    pull_request INTEGER NOT NULL,
    identity TEXT NOT NULL,
    run_id TEXT NOT NULL,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    reason TEXT,
    detail_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX finding_events_by_identity ON finding_events (repository, pull_request, identity);
