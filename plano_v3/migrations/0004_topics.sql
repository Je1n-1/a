CREATE TABLE topics (
 id INTEGER PRIMARY KEY,
 subject_id INTEGER NOT NULL REFERENCES subjects(id),
 name TEXT NOT NULL,
 name_key TEXT NOT NULL,
 completed INTEGER NOT NULL DEFAULT 0 CHECK(completed IN (0,1)),
 needs_review INTEGER NOT NULL DEFAULT 0 CHECK(needs_review IN (0,1)),
 version INTEGER NOT NULL DEFAULT 1,
 created_at TEXT NOT NULL,
 UNIQUE(subject_id,name_key)
);
ALTER TABLE timers ADD COLUMN topic_id INTEGER REFERENCES topics(id);
ALTER TABLE timers ADD COLUMN topic_name TEXT;
ALTER TABLE timers ADD COLUMN session_kind TEXT CHECK(session_kind IN ('study','review'));
ALTER TABLE study_sessions ADD COLUMN topic_id INTEGER REFERENCES topics(id);
ALTER TABLE study_sessions ADD COLUMN topic_name TEXT;
ALTER TABLE study_sessions ADD COLUMN session_kind TEXT CHECK(session_kind IN ('study','review'));
CREATE INDEX sessions_topic ON study_sessions(topic_id,id);
CREATE INDEX topics_review ON topics(needs_review,subject_id);
