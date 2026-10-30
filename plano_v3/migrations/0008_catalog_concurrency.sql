ALTER TABLE courses ADD COLUMN version INTEGER NOT NULL DEFAULT 1 CHECK(version >= 1);
ALTER TABLE subjects ADD COLUMN version INTEGER NOT NULL DEFAULT 1 CHECK(version >= 1);
ALTER TABLE study_sessions ADD COLUMN request_signature TEXT;
ALTER TABLE session_corrections ADD COLUMN request_signature TEXT;
