-- Ritmo adaptativo, evidências de aprendizagem e pausas reais.
-- Esta migration só acrescenta estruturas: sessões, blocos, metas e vínculos
-- existentes permanecem com os mesmos IDs e significados.

ALTER TABLE materias_estudo ADD COLUMN objective TEXT NOT NULL DEFAULT 'study'
  CHECK(objective IN ('study','review','continuous'));
ALTER TABLE materias_estudo ADD COLUMN mastery_level INTEGER
  CHECK(mastery_level IS NULL OR mastery_level BETWEEN 0 AND 5);
ALTER TABLE materias_estudo ADD COLUMN mastery_is_provisional INTEGER NOT NULL DEFAULT 1
  CHECK(mastery_is_provisional IN (0,1));
ALTER TABLE materias_estudo ADD COLUMN difficulty_is_provisional INTEGER NOT NULL DEFAULT 0
  CHECK(difficulty_is_provisional IN (0,1));
ALTER TABLE materias_estudo ADD COLUMN rhythm_mode TEXT NOT NULL DEFAULT 'suggested'
  CHECK(rhythm_mode IN ('suggested','manual'));
ALTER TABLE materias_estudo ADD COLUMN manual_daily_minutes INTEGER
  CHECK(manual_daily_minutes IS NULL OR manual_daily_minutes > 0);
ALTER TABLE materias_estudo ADD COLUMN habitual_daily_max_minutes INTEGER
  CHECK(habitual_daily_max_minutes IS NULL OR habitual_daily_max_minutes > 0);
ALTER TABLE materias_estudo ADD COLUMN profile_version INTEGER NOT NULL DEFAULT 1
  CHECK(profile_version > 0);
ALTER TABLE materias_estudo ADD COLUMN idempotency_key TEXT;
CREATE UNIQUE INDEX uq_study_idempotency_key
  ON materias_estudo(idempotency_key) WHERE idempotency_key IS NOT NULL;

CREATE TABLE study_plan_baselines (
 id INTEGER PRIMARY KEY,
 study_subject_id INTEGER NOT NULL REFERENCES materias_estudo(id) ON DELETE RESTRICT,
 policy_version TEXT NOT NULL,
 objective TEXT NOT NULL CHECK(objective IN ('study','review','continuous')),
 start_date TEXT NOT NULL CHECK(length(start_date)=10),
 end_date TEXT CHECK(end_date IS NULL OR length(end_date)=10),
 initial_budget_minutes INTEGER NOT NULL CHECK(initial_budget_minutes >= 0),
 current_budget_minutes INTEGER NOT NULL CHECK(current_budget_minutes >= 0),
 source TEXT NOT NULL CHECK(source IN ('explicit_effort','adaptive_estimate','recurring_cycle')),
 active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
 reason TEXT NOT NULL,
 created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
 updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
 CHECK(end_date IS NULL OR end_date >= start_date)
);
CREATE UNIQUE INDEX uq_active_study_baseline
  ON study_plan_baselines(study_subject_id) WHERE active=1;

CREATE TABLE study_observations (
 id INTEGER PRIMARY KEY,
 study_subject_id INTEGER NOT NULL REFERENCES materias_estudo(id) ON DELETE RESTRICT,
 study_session_id INTEGER REFERENCES sessoes_estudo(id) ON DELETE SET NULL,
 observed_at TEXT NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN (
   'mastery','difficulty','fatigue','concentration','new_content','deadline_check'
 )),
 source TEXT NOT NULL CHECK(source IN ('self_report','objective_evaluation','system_check')),
 raw_value TEXT,
 normalized_value REAL,
 notes TEXT,
 idempotency_key TEXT UNIQUE,
 created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX idx_study_observations_subject_date
  ON study_observations(study_subject_id,kind,observed_at DESC);

CREATE TABLE recommendation_snapshots (
 id INTEGER PRIMARY KEY,
 study_subject_id INTEGER NOT NULL REFERENCES materias_estudo(id) ON DELETE RESTRICT,
 baseline_id INTEGER REFERENCES study_plan_baselines(id) ON DELETE SET NULL,
 previous_snapshot_id INTEGER REFERENCES recommendation_snapshots(id) ON DELETE SET NULL,
 policy_version TEXT NOT NULL,
 calculated_at TEXT NOT NULL,
 horizon_start TEXT NOT NULL CHECK(length(horizon_start)=10),
 horizon_end TEXT CHECK(horizon_end IS NULL OR length(horizon_end)=10),
 estimated_need_minutes INTEGER NOT NULL CHECK(estimated_need_minutes >= 0),
 feasible_minutes INTEGER NOT NULL CHECK(feasible_minutes >= 0),
 allocated_minutes INTEGER NOT NULL DEFAULT 0 CHECK(allocated_minutes >= 0),
 deficit_minutes INTEGER NOT NULL DEFAULT 0 CHECK(deficit_minutes >= 0),
 recommended_daily_minutes INTEGER NOT NULL CHECK(recommended_daily_minutes >= 0),
 applied_daily_minutes INTEGER CHECK(applied_daily_minutes IS NULL OR applied_daily_minutes >= 0),
 confidence TEXT NOT NULL CHECK(confidence IN ('initial','low','medium','high')),
 reason TEXT NOT NULL,
 factors_json TEXT NOT NULL DEFAULT '{}',
 created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX idx_recommendation_snapshots_subject_date
  ON recommendation_snapshots(study_subject_id,calculated_at DESC,id DESC);

CREATE TABLE recommendation_decisions (
 id INTEGER PRIMARY KEY,
 recommendation_snapshot_id INTEGER NOT NULL REFERENCES recommendation_snapshots(id) ON DELETE RESTRICT,
 action TEXT NOT NULL CHECK(action IN ('accepted','auto_applied','rejected','undone')),
 previous_daily_minutes INTEGER,
 applied_daily_minutes INTEGER,
 reason TEXT,
 idempotency_key TEXT UNIQUE,
 created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE planning_runs (
 id INTEGER PRIMARY KEY,
 preview_token TEXT NOT NULL UNIQUE,
 idempotency_key TEXT UNIQUE,
 status TEXT NOT NULL DEFAULT 'preview' CHECK(status IN ('preview','applied','expired')),
 policy_version TEXT NOT NULL,
 horizon_start TEXT NOT NULL CHECK(length(horizon_start)=10),
 horizon_end TEXT NOT NULL CHECK(length(horizon_end)=10 AND horizon_end>=horizon_start),
 input_fingerprint TEXT NOT NULL,
 summary_json TEXT NOT NULL DEFAULT '{}',
 created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
 applied_at TEXT
);

ALTER TABLE sessoes_planejadas ADD COLUMN plan_run_id INTEGER
  REFERENCES planning_runs(id) ON DELETE SET NULL;
ALTER TABLE sessoes_planejadas ADD COLUMN intent TEXT NOT NULL DEFAULT 'study'
  CHECK(intent IN ('study','review'));
ALTER TABLE sessoes_planejadas ADD COLUMN is_locked INTEGER NOT NULL DEFAULT 0
  CHECK(is_locked IN (0,1));
ALTER TABLE sessoes_planejadas ADD COLUMN user_modified_at TEXT;
CREATE INDEX idx_planned_run ON sessoes_planejadas(plan_run_id,status);

ALTER TABLE sessoes_estudo ADD COLUMN purpose TEXT NOT NULL DEFAULT 'study'
  CHECK(purpose IN ('study','review'));
ALTER TABLE sessoes_estudo ADD COLUMN pause_seconds INTEGER NOT NULL DEFAULT 0
  CHECK(pause_seconds >= 0);
ALTER TABLE sessoes_estudo ADD COLUMN version INTEGER NOT NULL DEFAULT 1
  CHECK(version > 0);

CREATE TABLE session_breaks (
 id INTEGER PRIMARY KEY,
 focus_session_id INTEGER REFERENCES sessoes_foco(id) ON DELETE RESTRICT,
 study_session_id INTEGER REFERENCES sessoes_estudo(id) ON DELETE RESTRICT,
 started_at TEXT,
 ended_at TEXT,
 duration_seconds INTEGER CHECK(duration_seconds IS NULL OR duration_seconds >= 0),
 reason TEXT CHECK(reason IS NULL OR reason IN (
   'rest','water_food','bathroom','external_interruption','difficulty','other'
  )),
 notes TEXT,
 origin TEXT NOT NULL DEFAULT 'timer' CHECK(origin IN ('timer','retroactive_interval','retroactive_duration')),
 subtracts_from_focus INTEGER NOT NULL DEFAULT 0 CHECK(subtracts_from_focus IN (0,1)),
 version INTEGER NOT NULL DEFAULT 1 CHECK(version > 0),
 idempotency_key TEXT UNIQUE,
 created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
 updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
 CHECK(focus_session_id IS NOT NULL OR study_session_id IS NOT NULL),
 CHECK(
   (started_at IS NULL AND ended_at IS NULL AND duration_seconds IS NOT NULL)
   OR
   (started_at IS NOT NULL AND (ended_at IS NULL OR ended_at >= started_at))
 )
);
CREATE UNIQUE INDEX uq_focus_open_break
  ON session_breaks(focus_session_id)
  WHERE focus_session_id IS NOT NULL AND ended_at IS NULL AND started_at IS NOT NULL;
CREATE INDEX idx_session_breaks_session
  ON session_breaks(study_session_id,started_at,id);

CREATE TABLE study_session_corrections (
 id INTEGER PRIMARY KEY,
 study_session_id INTEGER NOT NULL REFERENCES sessoes_estudo(id) ON DELETE RESTRICT,
 break_id INTEGER REFERENCES session_breaks(id) ON DELETE SET NULL,
 correction_type TEXT NOT NULL CHECK(correction_type IN ('add_break','edit_session')),
 before_json TEXT NOT NULL,
 after_json TEXT NOT NULL,
 reason TEXT,
 idempotency_key TEXT UNIQUE,
 created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX idx_session_corrections_session
  ON study_session_corrections(study_session_id,created_at DESC);

INSERT OR IGNORE INTO configuracoes(key,value) VALUES
 ('timezone','America/Sao_Paulo'),
 ('adaptation_mode','assisted'),
 ('subject_daily_max_minutes','240'),
 ('rhythm_policy_version','adaptive-v1'),
 ('rhythm_difficulty_reference_json','{"1":120,"2":240,"3":360,"4":480,"5":600}'),
 ('rhythm_trend_observations','3'),
 ('rhythm_change_step_minutes','15'),
 ('provisional_cycle_days','28');
