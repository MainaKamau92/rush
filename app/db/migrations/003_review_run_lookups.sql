ALTER TABLE review_runs ADD COLUMN repository TEXT NOT NULL DEFAULT '';
ALTER TABLE review_runs ADD COLUMN pull_request INTEGER;
ALTER TABLE review_runs ADD COLUMN head_sha TEXT NOT NULL DEFAULT '';
ALTER TABLE review_runs ADD COLUMN status TEXT NOT NULL DEFAULT 'queued';
ALTER TABLE review_runs ADD COLUMN created_at TEXT NOT NULL DEFAULT '';
ALTER TABLE review_runs ADD COLUMN updated_at TEXT NOT NULL DEFAULT '';

UPDATE review_runs SET
    repository = json_extract(inputs_json, '$.repository'),
    pull_request = json_extract(inputs_json, '$.pull_request'),
    head_sha = json_extract(inputs_json, '$.head_sha'),
    status = json_extract(progress_json, '$.events[#-1].status'),
    created_at = strftime('%Y-%m-%dT%H:%M:%fZ', json_extract(progress_json, '$.events[0].at')),
    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', json_extract(progress_json, '$.events[#-1].at'));

CREATE INDEX review_runs_by_pull_request ON review_runs (repository, pull_request);
