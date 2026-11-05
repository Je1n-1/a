CREATE TABLE objectives (
 id INTEGER PRIMARY KEY, title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL, archived_at TEXT,
 version INTEGER NOT NULL DEFAULT 1,
 operation_key TEXT NOT NULL UNIQUE, request_signature TEXT NOT NULL
);
CREATE TABLE objective_stages (
 id INTEGER PRIMARY KEY, objective_id INTEGER NOT NULL REFERENCES objectives(id) ON DELETE CASCADE,
 stage_key TEXT NOT NULL, title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '', position INTEGER NOT NULL,
 UNIQUE(objective_id,stage_key)
);
CREATE TABLE objective_tasks (
 id INTEGER PRIMARY KEY, objective_id INTEGER NOT NULL REFERENCES objectives(id) ON DELETE CASCADE,
 stage_id INTEGER NOT NULL REFERENCES objective_stages(id) ON DELETE CASCADE,
 task_key TEXT NOT NULL, title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '', position INTEGER NOT NULL,
 planned_minutes INTEGER NOT NULL CHECK(planned_minutes BETWEEN 1 AND 600000),
 status TEXT NOT NULL DEFAULT 'not_started' CHECK(status IN ('not_started','in_progress','completed')),
 needs_review INTEGER NOT NULL DEFAULT 0 CHECK(needs_review IN (0,1)),
 subject_id INTEGER REFERENCES subjects(id), topic_id INTEGER REFERENCES topics(id),
 project_id INTEGER REFERENCES projects(id), step_id INTEGER REFERENCES project_steps(id),
 CHECK((subject_id IS NOT NULL)+(topic_id IS NOT NULL)+(project_id IS NOT NULL)+(step_id IS NOT NULL)<=1),
 UNIQUE(objective_id,task_key)
);
CREATE TABLE objective_dependencies (
 task_id INTEGER NOT NULL REFERENCES objective_tasks(id) ON DELETE CASCADE,
 prerequisite_id INTEGER NOT NULL REFERENCES objective_tasks(id) ON DELETE CASCADE,
 PRIMARY KEY(task_id,prerequisite_id), CHECK(task_id!=prerequisite_id)
);
CREATE INDEX objective_tasks_parent ON objective_tasks(objective_id,stage_id,position);
CREATE INDEX objective_stages_parent ON objective_stages(objective_id,position);
