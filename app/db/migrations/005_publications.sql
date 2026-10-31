CREATE TABLE publications (
    run_id TEXT NOT NULL,
    item TEXT NOT NULL,
    kind TEXT NOT NULL,
    status TEXT NOT NULL,
    comment_id INTEGER,
    detail TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (run_id, item)
);
