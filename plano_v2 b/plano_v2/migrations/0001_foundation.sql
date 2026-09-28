CREATE TABLE formacoes (
 id INTEGER PRIMARY KEY, name TEXT NOT NULL COLLATE NOCASE CHECK(trim(name) <> ''), institution TEXT, modality TEXT,
 start_date TEXT, expected_end_date TEXT, status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','paused','completed','cancelled','archived')),
 focus_priority INTEGER NOT NULL DEFAULT 3 CHECK(focus_priority BETWEEN 1 AND 5), archived_at TEXT,
 created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')), updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
 CHECK(start_date IS NULL OR expected_end_date IS NULL OR start_date <= expected_end_date)
);
CREATE TABLE disciplinas_grade (
 id INTEGER PRIMARY KEY, formation_id INTEGER NOT NULL REFERENCES formacoes(id) ON DELETE RESTRICT,
 name TEXT NOT NULL COLLATE NOCASE CHECK(trim(name) <> ''), code TEXT, period TEXT, workload_minutes INTEGER CHECK(workload_minutes IS NULL OR workload_minutes > 0),
 academic_status TEXT NOT NULL DEFAULT 'not_available' CHECK(academic_status IN ('not_available','available','in_progress','completed','failed','locked','exempted')),
 sort_order INTEGER NOT NULL DEFAULT 0 CHECK(sort_order >= 0), archived_at TEXT,
 created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')), updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
 UNIQUE(formation_id, name)
);
CREATE TABLE materias_estudo (
 id INTEGER PRIMARY KEY, origin TEXT NOT NULL CHECK(origin IN ('curriculum','personal')), curriculum_subject_id INTEGER REFERENCES disciplinas_grade(id) ON DELETE RESTRICT,
 related_formation_id INTEGER REFERENCES formacoes(id) ON DELETE RESTRICT, personal_name TEXT COLLATE NOCASE, favorite INTEGER NOT NULL DEFAULT 0 CHECK(favorite IN(0,1)),
 priority INTEGER NOT NULL DEFAULT 3 CHECK(priority BETWEEN 1 AND 5), difficulty INTEGER NOT NULL DEFAULT 3 CHECK(difficulty BETWEEN 1 AND 5), weekly_goal_minutes INTEGER CHECK(weekly_goal_minutes IS NULL OR weekly_goal_minutes > 0),
 start_date TEXT, target_date TEXT, status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','paused','completed','archived')), academic_period TEXT, attempt_number INTEGER NOT NULL DEFAULT 1 CHECK(attempt_number > 0), completed_at TEXT, final_score REAL, result TEXT NOT NULL DEFAULT 'none' CHECK(result IN ('none','approved','failed','withdrawn','exempted')), archived_at TEXT,
 created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')), updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
 CHECK((origin='curriculum' AND curriculum_subject_id IS NOT NULL AND personal_name IS NULL) OR (origin='personal' AND curriculum_subject_id IS NULL AND personal_name IS NOT NULL AND trim(personal_name) <> '')),
 CHECK(origin='curriculum' OR result='none')
);
CREATE UNIQUE INDEX uq_current_curriculum_study ON materias_estudo(curriculum_subject_id) WHERE status IN ('active','paused');
CREATE TABLE grupos_topicos (
 id INTEGER PRIMARY KEY, study_subject_id INTEGER NOT NULL REFERENCES materias_estudo(id) ON DELETE RESTRICT, name TEXT NOT NULL COLLATE NOCASE CHECK(trim(name) <> ''), sort_order INTEGER NOT NULL DEFAULT 0, archived_at TEXT,
 created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')), updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')), UNIQUE(id, study_subject_id)
);
CREATE TABLE topicos (
 id INTEGER PRIMARY KEY, study_subject_id INTEGER NOT NULL REFERENCES materias_estudo(id) ON DELETE RESTRICT, group_id INTEGER, name TEXT NOT NULL COLLATE NOCASE CHECK(trim(name) <> ''), description TEXT,
 status TEXT NOT NULL DEFAULT 'not_started' CHECK(status IN ('not_started','in_progress','completed')), mastery INTEGER NOT NULL DEFAULT 0 CHECK(mastery BETWEEN 0 AND 5), difficulty INTEGER CHECK(difficulty BETWEEN 1 AND 5), sort_order INTEGER NOT NULL DEFAULT 0, completed_at TEXT, archived_at TEXT,
 created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')), updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
 FOREIGN KEY(group_id) REFERENCES grupos_topicos(id) ON DELETE SET NULL
);
CREATE TABLE sessoes_planejadas (
 id INTEGER PRIMARY KEY, study_subject_id INTEGER NOT NULL REFERENCES materias_estudo(id) ON DELETE RESTRICT, topic_id INTEGER REFERENCES topicos(id) ON DELETE SET NULL, scheduled_date TEXT NOT NULL, start_time TEXT, planned_duration_minutes INTEGER NOT NULL CHECK(planned_duration_minutes > 0),
 status TEXT NOT NULL DEFAULT 'planned' CHECK(status IN ('planned','completed','skipped','rescheduled','cancelled')), source TEXT NOT NULL DEFAULT 'manual' CHECK(source IN ('manual','automatic')), rescheduled_to_id INTEGER REFERENCES sessoes_planejadas(id) ON DELETE SET NULL,
 created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')), updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE TABLE sessoes_estudo (
 id INTEGER PRIMARY KEY, study_subject_id INTEGER NOT NULL REFERENCES materias_estudo(id) ON DELETE RESTRICT, topic_id INTEGER REFERENCES topicos(id) ON DELETE SET NULL, planned_session_id INTEGER REFERENCES sessoes_planejadas(id) ON DELETE SET NULL,
 date TEXT NOT NULL, started_at TEXT, ended_at TEXT, duration_seconds INTEGER NOT NULL CHECK(duration_seconds > 0), entry_method TEXT NOT NULL CHECK(entry_method IN ('timer','manual','review')), mastery_before INTEGER CHECK(mastery_before BETWEEN 0 AND 5), mastery_after INTEGER CHECK(mastery_after BETWEEN 0 AND 5), progress_level TEXT CHECK(progress_level IN ('little','normal','much')), notes TEXT,
 created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')), updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE TABLE avaliacoes (
 id INTEGER PRIMARY KEY, study_subject_id INTEGER NOT NULL REFERENCES materias_estudo(id) ON DELETE RESTRICT, title TEXT NOT NULL CHECK(trim(title) <> ''), type TEXT NOT NULL CHECK(type IN ('exam','assignment','activity','project','exercise_list','recovery','other')), date TEXT NOT NULL, weight REAL, max_score REAL, score REAL,
 status TEXT NOT NULL DEFAULT 'scheduled' CHECK(status IN ('scheduled','completed','cancelled')), notes TEXT, created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')), updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE TABLE avaliacao_topicos (evaluation_id INTEGER NOT NULL REFERENCES avaliacoes(id) ON DELETE CASCADE, topic_id INTEGER NOT NULL REFERENCES topicos(id) ON DELETE RESTRICT, PRIMARY KEY(evaluation_id, topic_id));
CREATE TABLE disponibilidades_semanais (id INTEGER PRIMARY KEY, weekday INTEGER NOT NULL CHECK(weekday BETWEEN 0 AND 6), start_time TEXT NOT NULL, end_time TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN(0,1)), created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')), updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')), CHECK(start_time < end_time));
CREATE TRIGGER availability_overlap_insert BEFORE INSERT ON disponibilidades_semanais WHEN NEW.enabled=1 AND EXISTS(SELECT 1 FROM disponibilidades_semanais d WHERE d.weekday=NEW.weekday AND d.enabled=1 AND NEW.start_time<d.end_time AND NEW.end_time>d.start_time) BEGIN SELECT RAISE(ABORT,'availability_overlap'); END;
CREATE TRIGGER availability_overlap_update BEFORE UPDATE ON disponibilidades_semanais WHEN NEW.enabled=1 AND EXISTS(SELECT 1 FROM disponibilidades_semanais d WHERE d.weekday=NEW.weekday AND d.enabled=1 AND d.id<>NEW.id AND NEW.start_time<d.end_time AND NEW.end_time>d.start_time) BEGIN SELECT RAISE(ABORT,'availability_overlap'); END;
CREATE TABLE revisoes (id INTEGER PRIMARY KEY, topic_id INTEGER NOT NULL REFERENCES topicos(id) ON DELETE RESTRICT, study_session_id INTEGER REFERENCES sessoes_estudo(id) ON DELETE SET NULL, due_date TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','completed','skipped','cancelled')), review_stage TEXT NOT NULL CHECK(review_stage IN ('d1','d7','d30')), completed_at TEXT, rating TEXT CHECK(rating IN ('wrong','hard','good','easy')), created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')), updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')), UNIQUE(study_session_id, review_stage));
CREATE TABLE configuracoes (key TEXT PRIMARY KEY, value TEXT, updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')));
CREATE TABLE projetos (id INTEGER PRIMARY KEY, name TEXT NOT NULL CHECK(trim(name)<>''), description TEXT, objective TEXT, start_date TEXT, target_date TEXT, status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','paused','completed','archived')), estimated_minutes INTEGER, notes TEXT, archived_at TEXT, created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')), updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')));
CREATE TABLE projeto_tarefas (id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES projetos(id) ON DELETE CASCADE, name TEXT NOT NULL CHECK(trim(name)<>''), status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','completed','archived')), sort_order INTEGER NOT NULL DEFAULT 0, completed_at TEXT, created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')), updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')));
CREATE INDEX idx_sessions_date ON sessoes_estudo(date DESC); CREATE INDEX idx_planned_date ON sessoes_planejadas(scheduled_date,start_time); CREATE INDEX idx_reviews_due ON revisoes(status,due_date); CREATE INDEX idx_curriculum_formation ON disciplinas_grade(formation_id,sort_order); CREATE INDEX idx_topics_subject ON topicos(study_subject_id,sort_order);
