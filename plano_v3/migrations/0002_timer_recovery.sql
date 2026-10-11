ALTER TABLE study_sessions ADD COLUMN request_key TEXT;
CREATE UNIQUE INDEX sessions_request_key ON study_sessions(request_key) WHERE request_key IS NOT NULL;
CREATE TABLE timer_recoveries (
 id INTEGER PRIMARY KEY,
 timer_id INTEGER NOT NULL REFERENCES timers(id),
 operation_key TEXT NOT NULL UNIQUE,
 choice TEXT NOT NULL CHECK(choice IN ('full','cutoff')),
 cutoff_at TEXT,
 previous_effective_seconds INTEGER NOT NULL,
 accepted_effective_seconds INTEGER NOT NULL,
 confirmed_at TEXT NOT NULL
);
CREATE INDEX recoveries_timer ON timer_recoveries(timer_id, id);
