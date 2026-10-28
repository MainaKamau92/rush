-- Setup metadata only. Review records are introduced by TCR-005.
CREATE TABLE app_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
INSERT INTO app_metadata (key, value) VALUES ('application', 'rush');
