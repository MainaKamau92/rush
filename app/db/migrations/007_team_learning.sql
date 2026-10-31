CREATE TABLE learning_proposals (
    proposal_id TEXT PRIMARY KEY NOT NULL,
    rule_id TEXT NOT NULL UNIQUE,
    revision INTEGER NOT NULL CHECK (revision > 0),
    content_sha256 TEXT NOT NULL,
    status TEXT NOT NULL,
    proposal_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE learning_revisions (
    entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
    proposal_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    content_sha256 TEXT NOT NULL,
    proposal_json TEXT NOT NULL
);

CREATE TABLE learned_rules (
    rule_id TEXT NOT NULL,
    version TEXT NOT NULL,
    proposal_id TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    rule_json TEXT NOT NULL,
    approved_at TEXT NOT NULL,
    PRIMARY KEY (rule_id, version)
);
