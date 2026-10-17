CREATE TABLE projects (
 id INTEGER PRIMARY KEY, name TEXT NOT NULL, objective TEXT NOT NULL DEFAULT '',
 course_id INTEGER REFERENCES courses(id),
 status TEXT NOT NULL DEFAULT 'not_started' CHECK(status IN ('not_started','in_progress','completed')),
 archived_at TEXT, created_at TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE project_steps (
 id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES projects(id),
 name TEXT NOT NULL, completed INTEGER NOT NULL DEFAULT 0 CHECK(completed IN (0,1)),
 created_at TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX project_steps_project ON project_steps(project_id,id);
ALTER TABLE timers ADD COLUMN project_id INTEGER REFERENCES projects(id) CHECK(project_id IS NULL OR (subject_id IS NULL AND topic_id IS NULL));
ALTER TABLE timers ADD COLUMN project_name TEXT;
ALTER TABLE timers ADD COLUMN step_id INTEGER REFERENCES project_steps(id);
ALTER TABLE timers ADD COLUMN step_name TEXT;
ALTER TABLE timers ADD COLUMN project_course_id INTEGER REFERENCES courses(id);
ALTER TABLE study_sessions ADD COLUMN project_id INTEGER REFERENCES projects(id) CHECK(project_id IS NULL OR (subject_id IS NULL AND topic_id IS NULL));
ALTER TABLE study_sessions ADD COLUMN project_name TEXT;
ALTER TABLE study_sessions ADD COLUMN step_id INTEGER REFERENCES project_steps(id);
ALTER TABLE study_sessions ADD COLUMN step_name TEXT;
ALTER TABLE study_sessions ADD COLUMN project_course_id INTEGER REFERENCES courses(id);
CREATE INDEX sessions_project_step ON study_sessions(project_id,step_id);
