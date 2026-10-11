ALTER TABLE study_sessions ADD COLUMN correction_version INTEGER NOT NULL DEFAULT 1;
ALTER TABLE study_sessions ADD COLUMN allocation_mode TEXT NOT NULL DEFAULT 'original'
 CHECK(allocation_mode IN ('original','duration','times'));
CREATE TABLE session_days (
 session_id INTEGER NOT NULL REFERENCES study_sessions(id),
 local_date TEXT NOT NULL,
 effective_seconds INTEGER NOT NULL CHECK(effective_seconds>=0),
 break_seconds INTEGER NOT NULL CHECK(break_seconds>=0),
 PRIMARY KEY(session_id,local_date)
);
CREATE INDEX session_days_date ON session_days(local_date,session_id);
CREATE INDEX sessions_subject ON study_sessions(subject_id,id);
CREATE TABLE session_corrections (
 id INTEGER PRIMARY KEY,
 session_id INTEGER NOT NULL REFERENCES study_sessions(id),
 version INTEGER NOT NULL,
 operation_key TEXT NOT NULL UNIQUE,
 reason TEXT NOT NULL,
 old_values TEXT NOT NULL,
 new_values TEXT NOT NULL,
 created_at TEXT NOT NULL,
 UNIQUE(session_id,version)
);
