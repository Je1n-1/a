-- Planejamento por prazo e esforço pessoal. As migrations anteriores são
-- imutáveis; esta evolução preserva registros e IDs existentes.

-- Configurações próprias da disciplina curricular. workload_minutes continua
-- significando apenas a carga informada pela instituição.
ALTER TABLE disciplinas_grade ADD COLUMN deadline_date TEXT;
ALTER TABLE disciplinas_grade ADD COLUMN required_study_minutes INTEGER
    CHECK(required_study_minutes IS NULL OR required_study_minutes > 0);
ALTER TABLE disciplinas_grade ADD COLUMN priority_base INTEGER NOT NULL DEFAULT 3
    CHECK(priority_base BETWEEN 1 AND 5);
ALTER TABLE disciplinas_grade ADD COLUMN preferred_block_minutes INTEGER
    CHECK(preferred_block_minutes IS NULL OR preferred_block_minutes > 0);
ALTER TABLE disciplinas_grade ADD COLUMN allowed_weekdays TEXT;
ALTER TABLE disciplinas_grade ADD COLUMN minimum_grade REAL;
ALTER TABLE disciplinas_grade ADD COLUMN planning_enabled INTEGER NOT NULL DEFAULT 0
    CHECK(planning_enabled IN (0,1));

-- Estudos paralelos podem ter esforço total, mínimo semanal e a mesma
-- preferência de blocos sem confundir meta semanal com horas já realizadas.
ALTER TABLE materias_estudo ADD COLUMN required_study_minutes INTEGER
    CHECK(required_study_minutes IS NULL OR required_study_minutes > 0);
ALTER TABLE materias_estudo ADD COLUMN minimum_weekly_minutes INTEGER
    CHECK(minimum_weekly_minutes IS NULL OR minimum_weekly_minutes > 0);
ALTER TABLE materias_estudo ADD COLUMN preferred_block_minutes INTEGER
    CHECK(preferred_block_minutes IS NULL OR preferred_block_minutes > 0);
ALTER TABLE materias_estudo ADD COLUMN allowed_weekdays TEXT;

-- Topicos antes exigiam um estudo atual. A tabela é reconstruída com a mesma
-- chave primária para que sessões, blocos, notas, revisões e avaliações
-- existentes continuem apontando ao mesmo conteúdo. curriculum_subject_id
-- permite cadastrar conteúdo antes de ativar o estudo; study_subject_id segue
-- preenchido nos conteúdos legados para compatibilidade com o histórico.
DROP INDEX IF EXISTS idx_topics_subject;
CREATE TABLE topicos_smart_new (
 id INTEGER PRIMARY KEY,
 study_subject_id INTEGER REFERENCES materias_estudo(id) ON DELETE RESTRICT,
 curriculum_subject_id INTEGER REFERENCES disciplinas_grade(id) ON DELETE RESTRICT,
 group_id INTEGER REFERENCES grupos_topicos(id) ON DELETE SET NULL,
 name TEXT NOT NULL COLLATE NOCASE CHECK(trim(name) <> ''),
 description TEXT,
 unit TEXT,
 status TEXT NOT NULL DEFAULT 'not_started' CHECK(status IN ('not_started','in_progress','completed')),
 mastery INTEGER NOT NULL DEFAULT 0 CHECK(mastery BETWEEN 0 AND 5),
 manual_mastery INTEGER NOT NULL DEFAULT 0 CHECK(manual_mastery BETWEEN 0 AND 5),
 difficulty INTEGER CHECK(difficulty BETWEEN 1 AND 5),
 estimated_minutes INTEGER CHECK(estimated_minutes IS NULL OR estimated_minutes > 0),
 sort_order INTEGER NOT NULL DEFAULT 0,
 started_at TEXT,
 completed_at TEXT,
 last_session_date TEXT,
 archived_at TEXT,
 created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
 updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
 CHECK(study_subject_id IS NOT NULL OR curriculum_subject_id IS NOT NULL)
);
INSERT INTO topicos_smart_new(
 id,study_subject_id,curriculum_subject_id,group_id,name,description,unit,status,
 mastery,manual_mastery,difficulty,sort_order,started_at,completed_at,last_session_date,
 archived_at,created_at,updated_at
)
SELECT t.id,t.study_subject_id,s.curriculum_subject_id,t.group_id,t.name,t.description,
       g.name,t.status,t.mastery,t.manual_mastery,t.difficulty,t.sort_order,
       CASE WHEN t.status IN ('in_progress','completed') THEN t.created_at END,
       t.completed_at,
       (SELECT MAX(x.date) FROM sessoes_estudo x WHERE x.topic_id=t.id),
       t.archived_at,t.created_at,t.updated_at
FROM topicos t
JOIN materias_estudo s ON s.id=t.study_subject_id
LEFT JOIN grupos_topicos g ON g.id=t.group_id;
DROP TABLE topicos;
ALTER TABLE topicos_smart_new RENAME TO topicos;
CREATE INDEX idx_topics_subject ON topicos(study_subject_id,sort_order);
CREATE INDEX idx_topics_curriculum ON topicos(curriculum_subject_id,unit,sort_order)
    WHERE archived_at IS NULL;

-- Avaliações também passam a aceitar uma disciplina curricular sem estudo
-- atual. O campo date continua sendo a data prevista, para não quebrar APIs
-- existentes; delivery_date diferencia entrega quando aplicável.
CREATE TABLE avaliacoes_smart_new (
 id INTEGER PRIMARY KEY,
 study_subject_id INTEGER REFERENCES materias_estudo(id) ON DELETE RESTRICT,
 curriculum_subject_id INTEGER REFERENCES disciplinas_grade(id) ON DELETE RESTRICT,
 title TEXT NOT NULL CHECK(trim(title) <> ''),
 type TEXT NOT NULL CHECK(type IN ('exam','assignment','activity','project','exercise_list','recovery','other')),
 date TEXT NOT NULL,
 delivery_date TEXT,
 weight REAL,
 max_score REAL,
 score REAL,
 status TEXT NOT NULL DEFAULT 'scheduled' CHECK(status IN ('scheduled','delivered','corrected','cancelled')),
 notes TEXT,
 created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
 updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
 CHECK(study_subject_id IS NOT NULL OR curriculum_subject_id IS NOT NULL),
 CHECK(delivery_date IS NULL OR delivery_date >= date)
);
INSERT INTO avaliacoes_smart_new(
 id,study_subject_id,curriculum_subject_id,title,type,date,delivery_date,weight,max_score,score,status,notes,created_at,updated_at
)
SELECT e.id,e.study_subject_id,s.curriculum_subject_id,e.title,e.type,e.date,NULL,e.weight,e.max_score,e.score,
       CASE e.status WHEN 'completed' THEN 'corrected' ELSE e.status END,e.notes,e.created_at,e.updated_at
FROM avaliacoes e
JOIN materias_estudo s ON s.id=e.study_subject_id;
DROP TABLE avaliacoes;
ALTER TABLE avaliacoes_smart_new RENAME TO avaliacoes;
CREATE INDEX idx_evaluations_curriculum_date ON avaliacoes(curriculum_subject_id,date)
    WHERE status <> 'cancelled';
CREATE INDEX idx_evaluations_study_date ON avaliacoes(study_subject_id,date)
    WHERE status <> 'cancelled';

-- Linha do tempo leve para alterações de prazo e esforço que não aparecem em
-- sessões ou no histórico acadêmico já existente.
CREATE TABLE curriculum_timeline_events (
 id INTEGER PRIMARY KEY,
 curriculum_subject_id INTEGER NOT NULL REFERENCES disciplinas_grade(id) ON DELETE RESTRICT,
 event_type TEXT NOT NULL CHECK(event_type IN ('schedule_settings','content','evaluation','planning')),
 title TEXT NOT NULL,
 details TEXT,
 created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX idx_curriculum_timeline_subject ON curriculum_timeline_events(curriculum_subject_id,created_at DESC);
CREATE INDEX idx_planned_source_date ON sessoes_planejadas(source,status,scheduled_date,start_time);
CREATE INDEX idx_sessions_study_date ON sessoes_estudo(study_subject_id,date);
