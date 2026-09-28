-- Tópicos tornam-se unidades reais de planejamento. A reconstrução preserva
-- todos os IDs existentes, portanto sessões, blocos, notas, avaliações e
-- revisões continuam apontando para o mesmo conteúdo.
DROP INDEX IF EXISTS idx_topics_subject;
DROP INDEX IF EXISTS idx_topics_curriculum;

CREATE TABLE topicos_focus_new (
 id INTEGER PRIMARY KEY,
 study_subject_id INTEGER REFERENCES materias_estudo(id) ON DELETE RESTRICT,
 curriculum_subject_id INTEGER REFERENCES disciplinas_grade(id) ON DELETE RESTRICT,
 group_id INTEGER REFERENCES grupos_topicos(id) ON DELETE SET NULL,
 name TEXT NOT NULL COLLATE NOCASE CHECK(trim(name) <> ''),
 description TEXT,
 unit TEXT,
 status TEXT NOT NULL DEFAULT 'not_started'
   CHECK(status IN ('not_started','in_progress','completed','paused','for_review')),
 mastery INTEGER NOT NULL DEFAULT 0 CHECK(mastery BETWEEN 0 AND 5),
 manual_mastery INTEGER NOT NULL DEFAULT 0 CHECK(manual_mastery BETWEEN 0 AND 5),
 difficulty INTEGER CHECK(difficulty BETWEEN 1 AND 5),
 estimated_minutes INTEGER CHECK(estimated_minutes IS NULL OR estimated_minutes > 0),
 effort_weight INTEGER NOT NULL DEFAULT 2 CHECK(effort_weight BETWEEN 1 AND 3),
 observations TEXT,
 review_requested INTEGER NOT NULL DEFAULT 0 CHECK(review_requested IN (0,1)),
 sort_order INTEGER NOT NULL DEFAULT 0,
 started_at TEXT,
 completed_at TEXT,
 last_session_date TEXT,
 archived_at TEXT,
 created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
 updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
 CHECK(study_subject_id IS NOT NULL OR curriculum_subject_id IS NOT NULL)
);

INSERT INTO topicos_focus_new(
 id,study_subject_id,curriculum_subject_id,group_id,name,description,unit,status,
 mastery,manual_mastery,difficulty,estimated_minutes,effort_weight,observations,
 review_requested,sort_order,started_at,completed_at,last_session_date,archived_at,
 created_at,updated_at
)
SELECT
 id,study_subject_id,curriculum_subject_id,group_id,name,description,unit,status,
 mastery,manual_mastery,difficulty,estimated_minutes,2,NULL,0,sort_order,
 started_at,completed_at,last_session_date,archived_at,created_at,updated_at
FROM topicos;

DROP TABLE topicos;
ALTER TABLE topicos_focus_new RENAME TO topicos;
CREATE INDEX idx_topics_subject ON topicos(study_subject_id,sort_order);
CREATE INDEX idx_topics_curriculum ON topicos(curriculum_subject_id,unit,sort_order)
    WHERE archived_at IS NULL;

CREATE TABLE topic_dependencies (
 topic_id INTEGER NOT NULL REFERENCES topicos(id) ON DELETE RESTRICT,
 prerequisite_topic_id INTEGER NOT NULL REFERENCES topicos(id) ON DELETE RESTRICT,
 created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
 PRIMARY KEY(topic_id, prerequisite_topic_id),
 CHECK(topic_id <> prerequisite_topic_id)
);
CREATE INDEX idx_topic_dependencies_prerequisite ON topic_dependencies(prerequisite_topic_id);

-- Mantém o motivo do motor no próprio bloco depois de aplicar uma prévia.
ALTER TABLE sessoes_planejadas ADD COLUMN selection_reason TEXT;
ALTER TABLE sessoes_planejadas ADD COLUMN selection_context TEXT;

-- Bases anteriores usavam planning_enabled=0 como valor legado. O opt-out
-- explícito separa esse legado da intenção atual do usuário: disciplinas em
-- andamento entram no planejamento, salvo quando ele as desativa de propósito.
ALTER TABLE disciplinas_grade ADD COLUMN planning_opt_out INTEGER NOT NULL DEFAULT 0
  CHECK(planning_opt_out IN (0,1));

-- A sessão de foco é a fonte oficial enquanto o cronômetro está ativo. O
-- navegador apenas exibe o tempo derivado de timestamps persistidos.
CREATE TABLE sessoes_foco (
 id INTEGER PRIMARY KEY,
 study_subject_id INTEGER NOT NULL REFERENCES materias_estudo(id) ON DELETE RESTRICT,
 topic_id INTEGER REFERENCES topicos(id) ON DELETE SET NULL,
 planned_session_id INTEGER REFERENCES sessoes_planejadas(id) ON DELETE SET NULL,
 planned_duration_minutes INTEGER CHECK(planned_duration_minutes IS NULL OR planned_duration_minutes > 0),
 status TEXT NOT NULL DEFAULT 'running'
   CHECK(status IN ('running','paused','finishing','completed','cancelled','recovery_required')),
 started_at TEXT NOT NULL,
 last_resumed_at TEXT,
 accumulated_seconds INTEGER NOT NULL DEFAULT 0 CHECK(accumulated_seconds >= 0),
 paused_at TEXT,
 ended_at TEXT,
 note_id INTEGER REFERENCES anotacoes_estudo(id) ON DELETE SET NULL,
 completed_study_session_id INTEGER REFERENCES sessoes_estudo(id) ON DELETE SET NULL,
 version INTEGER NOT NULL DEFAULT 1 CHECK(version >= 1),
 recovery_required_at TEXT,
 created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
 updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE UNIQUE INDEX uq_focus_one_active
  ON sessoes_foco((1))
  WHERE status IN ('running','paused','recovery_required');
CREATE INDEX idx_focus_status_updated ON sessoes_foco(status,updated_at DESC);
CREATE INDEX idx_focus_planned_session ON sessoes_foco(planned_session_id);
