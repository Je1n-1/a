CREATE TABLE courses (
 id INTEGER PRIMARY KEY, name TEXT NOT NULL, institution TEXT NOT NULL DEFAULT '',
 archived_at TEXT, created_at TEXT NOT NULL
);
CREATE TABLE subjects (
 id INTEGER PRIMARY KEY, course_id INTEGER NOT NULL REFERENCES courses(id),
 name TEXT NOT NULL, name_key TEXT NOT NULL, code TEXT NOT NULL DEFAULT '',
 period TEXT NOT NULL DEFAULT '', workload_minutes INTEGER CHECK(workload_minutes > 0),
 academic_status TEXT NOT NULL DEFAULT 'not_available' CHECK(academic_status IN
 ('not_available','available','in_progress','completed','failed','locked','exempted')),
 notes TEXT NOT NULL DEFAULT '', archived_at TEXT, created_at TEXT NOT NULL,
 UNIQUE(course_id, name_key)
);
CREATE INDEX subjects_course ON subjects(course_id, archived_at);
CREATE TABLE timers (
 id INTEGER PRIMARY KEY, subject_id INTEGER REFERENCES subjects(id),
 title TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('running','paused','completed','cancelled')),
 started_at TEXT NOT NULL, ended_at TEXT, version INTEGER NOT NULL DEFAULT 1,
 operation_key TEXT NOT NULL UNIQUE
);
CREATE UNIQUE INDEX only_one_active_timer ON timers((1)) WHERE status IN ('running','paused');
CREATE TABLE timer_intervals (
 id INTEGER PRIMARY KEY, timer_id INTEGER NOT NULL REFERENCES timers(id),
 kind TEXT NOT NULL CHECK(kind IN ('focus','break')),
 started_at TEXT NOT NULL, ended_at TEXT CHECK(ended_at IS NULL OR ended_at >= started_at)
);
CREATE UNIQUE INDEX one_open_interval ON timer_intervals(timer_id) WHERE ended_at IS NULL;
CREATE INDEX intervals_timer ON timer_intervals(timer_id, started_at);
CREATE TABLE study_sessions (
 id INTEGER PRIMARY KEY, timer_id INTEGER UNIQUE REFERENCES timers(id),
 subject_id INTEGER REFERENCES subjects(id), title TEXT NOT NULL,
 source TEXT NOT NULL CHECK(source IN ('timer','manual')),
 started_at TEXT, ended_at TEXT, local_date TEXT NOT NULL,
 effective_seconds INTEGER NOT NULL CHECK(effective_seconds >= 0),
 break_seconds INTEGER NOT NULL DEFAULT 0 CHECK(break_seconds >= 0),
 note TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL
);
CREATE INDEX sessions_date_subject ON study_sessions(local_date,subject_id);
