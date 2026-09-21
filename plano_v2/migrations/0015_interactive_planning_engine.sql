-- Motor de planejamento interativo: objetivos versionados, rascunhos e
-- resultados diários. A migration é exclusivamente aditiva e não reclassifica
-- sessões históricas sem vínculo confiável.

CREATE TABLE study_objectives (
 id INTEGER PRIMARY KEY,
 study_subject_id INTEGER NOT NULL REFERENCES materias_estudo(id) ON DELETE RESTRICT,
 cycle_number INTEGER NOT NULL DEFAULT 1 CHECK(cycle_number > 0),
 objective_type TEXT NOT NULL DEFAULT 'study'
   CHECK(objective_type IN ('study','review','continuous')),
 status TEXT NOT NULL DEFAULT 'active'
   CHECK(status IN ('active','closed')),
 title TEXT,
 start_date TEXT NOT NULL CHECK(length(start_date)=10),
 deadline_date TEXT CHECK(deadline_date IS NULL OR length(deadline_date)=10),
 budget_minutes INTEGER CHECK(budget_minutes IS NULL OR budget_minutes >= 0),
 budget_origin TEXT NOT NULL
   CHECK(budget_origin IN ('institutional_seed','user','accepted_recommendation','legacy_provisional')),
 budget_is_provisional INTEGER NOT NULL DEFAULT 0 CHECK(budget_is_provisional IN (0,1)),
 residual_seconds INTEGER NOT NULL DEFAULT 0 CHECK(residual_seconds BETWEEN 0 AND 59),
 version INTEGER NOT NULL DEFAULT 1 CHECK(version > 0),
 closed_at TEXT,
 created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
 updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
 CHECK(deadline_date IS NULL OR deadline_date >= start_date),
 UNIQUE(study_subject_id,cycle_number)
);
CREATE UNIQUE INDEX uq_active_study_objective
  ON study_objectives(study_subject_id) WHERE status='active';
CREATE INDEX idx_study_objective_deadline
  ON study_objectives(status,deadline_date,study_subject_id);

-- Adaptação explícita do estado existente. Esforço pessoal confirmado vence a
-- carga acadêmica; na ausência dele, a carga institucional é apenas uma
-- estimativa inicial identificada. O histórico antigo não é ligado ao ciclo.
INSERT INTO study_objectives(
 study_subject_id,cycle_number,objective_type,status,title,start_date,deadline_date,
 budget_minutes,budget_origin,budget_is_provisional
)
SELECT
 s.id,1,COALESCE(s.objective,'study'),'active',COALESCE(d.name,s.personal_name),
 COALESCE(s.start_date,d.start_date,substr(s.created_at,1,10)),
 COALESCE(s.target_date,d.deadline_date,d.end_date),
 CASE
   WHEN s.origin='curriculum' AND d.required_study_minutes IS NOT NULL THEN d.required_study_minutes
   WHEN s.origin='personal' AND s.required_study_minutes IS NOT NULL THEN s.required_study_minutes
   WHEN d.workload_minutes IS NOT NULL THEN d.workload_minutes
   ELSE (SELECT b.current_budget_minutes FROM study_plan_baselines b
         WHERE b.study_subject_id=s.id AND b.active=1 ORDER BY b.id DESC LIMIT 1)
 END,
 CASE
   WHEN (s.origin='curriculum' AND d.required_study_minutes IS NOT NULL)
     OR (s.origin='personal' AND s.required_study_minutes IS NOT NULL) THEN 'user'
   WHEN d.workload_minutes IS NOT NULL THEN 'institutional_seed'
   ELSE 'legacy_provisional'
 END,
 CASE
   WHEN (s.origin='curriculum' AND d.required_study_minutes IS NOT NULL)
     OR (s.origin='personal' AND s.required_study_minutes IS NOT NULL) THEN 0
   ELSE 1
 END
FROM materias_estudo s
LEFT JOIN disciplinas_grade d ON d.id=s.curriculum_subject_id
WHERE s.status='active' AND s.archived_at IS NULL;

CREATE TABLE study_budget_revisions (
 id INTEGER PRIMARY KEY,
 objective_id INTEGER NOT NULL REFERENCES study_objectives(id) ON DELETE RESTRICT,
 previous_budget_minutes INTEGER,
 new_budget_minutes INTEGER CHECK(new_budget_minutes IS NULL OR new_budget_minutes >= 0),
 origin TEXT NOT NULL
   CHECK(origin IN ('institutional_seed','user','accepted_recommendation','legacy_provisional')),
 reason TEXT NOT NULL,
 idempotency_key TEXT UNIQUE,
 created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX idx_budget_revision_objective
  ON study_budget_revisions(objective_id,created_at DESC,id DESC);

INSERT INTO study_budget_revisions(
 objective_id,previous_budget_minutes,new_budget_minutes,origin,reason
)
SELECT id,NULL,budget_minutes,budget_origin,
 CASE budget_origin
   WHEN 'institutional_seed' THEN 'Estimativa inicial baseada na carga institucional; pode ser ajustada.'
   WHEN 'user' THEN 'Esforço pessoal existente preservado na migração.'
   ELSE 'Estimativa legada preservada como provisória para revisão.'
 END
FROM study_objectives WHERE budget_minutes IS NOT NULL;

CREATE TABLE planning_drafts (
 id INTEGER PRIMARY KEY,
 token TEXT NOT NULL UNIQUE,
 status TEXT NOT NULL DEFAULT 'draft'
   CHECK(status IN ('draft','applied','discarded','stale')),
 horizon_start TEXT NOT NULL CHECK(length(horizon_start)=10),
 horizon_end TEXT NOT NULL CHECK(length(horizon_end)=10 AND horizon_end>=horizon_start),
 calculation_end TEXT NOT NULL CHECK(length(calculation_end)=10 AND calculation_end>=horizon_end),
 selected_study_ids_json TEXT NOT NULL DEFAULT '[]',
 intents_json TEXT NOT NULL DEFAULT '[]',
 parameters_json TEXT NOT NULL DEFAULT '{}',
 input_fingerprint TEXT NOT NULL,
 preview_json TEXT NOT NULL DEFAULT '{}',
 version INTEGER NOT NULL DEFAULT 1 CHECK(version > 0),
 created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
 updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
 applied_at TEXT
);
CREATE INDEX idx_planning_drafts_status
  ON planning_drafts(status,updated_at DESC,id DESC);

ALTER TABLE planning_runs ADD COLUMN draft_id INTEGER
  REFERENCES planning_drafts(id) ON DELETE SET NULL;

CREATE TABLE plan_revisions (
 id INTEGER PRIMARY KEY,
 draft_id INTEGER NOT NULL REFERENCES planning_drafts(id) ON DELETE RESTRICT,
 planning_run_id INTEGER REFERENCES planning_runs(id) ON DELETE SET NULL,
 before_json TEXT NOT NULL DEFAULT '[]',
 after_json TEXT NOT NULL DEFAULT '[]',
 reason TEXT NOT NULL,
 created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX idx_plan_revisions_draft ON plan_revisions(draft_id,id DESC);

ALTER TABLE sessoes_planejadas ADD COLUMN objective_id INTEGER
  REFERENCES study_objectives(id) ON DELETE SET NULL;
ALTER TABLE sessoes_estudo ADD COLUMN objective_id INTEGER
  REFERENCES study_objectives(id) ON DELETE SET NULL;
CREATE INDEX idx_planned_objective ON sessoes_planejadas(objective_id,scheduled_date,status);
CREATE INDEX idx_study_session_objective ON sessoes_estudo(objective_id,date,id);

CREATE TABLE daily_study_results (
 id INTEGER PRIMARY KEY,
 date TEXT NOT NULL UNIQUE CHECK(length(date)=10),
 status TEXT NOT NULL CHECK(status IN ('completed','not_completed','dismissed')),
 planned_minutes INTEGER NOT NULL DEFAULT 0 CHECK(planned_minutes >= 0),
 realized_seconds INTEGER NOT NULL DEFAULT 0 CHECK(realized_seconds >= 0),
 comment TEXT,
 version INTEGER NOT NULL DEFAULT 1 CHECK(version > 0),
 created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
 updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE daily_study_result_reasons (
 daily_result_id INTEGER NOT NULL REFERENCES daily_study_results(id) ON DELETE CASCADE,
 reason TEXT NOT NULL CHECK(reason IN (
   'lack_of_time','fatigue','unexpected','difficulty','plan_problem','finished_early','other'
 )),
 PRIMARY KEY(daily_result_id,reason)
);

INSERT OR IGNORE INTO configuracoes(key,value) VALUES
 ('interactive_planning_policy_version','interactive-v1'),
 ('planning_draft_ttl_days','14');
