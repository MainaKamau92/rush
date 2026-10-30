CREATE TABLE review_runs (
    run_id TEXT PRIMARY KEY NOT NULL,
    inputs_json TEXT NOT NULL,
    progress_json TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision >= 0)
);
