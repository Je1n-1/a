-- Metas diárias coexistem com a meta semanal legada durante a migração de UX.
-- Nenhum valor existente é convertido automaticamente: a origem continua
-- identificável até a pessoa confirmar uma nova configuração.
ALTER TABLE materias_estudo ADD COLUMN daily_goal_minutes INTEGER
  CHECK(daily_goal_minutes IS NULL OR daily_goal_minutes > 0);
ALTER TABLE materias_estudo ADD COLUMN daily_goal_mode TEXT NOT NULL DEFAULT 'legacy_weekly'
  CHECK(daily_goal_mode IN ('legacy_weekly','per_selected_day','campaign_total','deadline_paced'));
ALTER TABLE materias_estudo ADD COLUMN daily_goal_is_provisional INTEGER NOT NULL DEFAULT 0
  CHECK(daily_goal_is_provisional IN (0,1));

-- Campanhas são objetivos explícitos. Os itens usam chaves estrangeiras para
-- preservar o vínculo com a grade e o estudo canônico sem listas JSON frágeis.
CREATE TABLE review_campaigns (
 id INTEGER PRIMARY KEY,
 name TEXT NOT NULL COLLATE NOCASE CHECK(trim(name)<>''),
 purpose TEXT,
 start_date TEXT NOT NULL CHECK(length(start_date)=10),
 end_date TEXT NOT NULL CHECK(length(end_date)=10 AND end_date>=start_date),
 daily_goal_minutes INTEGER NOT NULL CHECK(daily_goal_minutes>0),
 preferred_block_minutes INTEGER CHECK(preferred_block_minutes IS NULL OR preferred_block_minutes BETWEEN 15 AND 240),
 allowed_weekdays TEXT NOT NULL DEFAULT '[0,1,2,3,4,5,6]',
 goal_scope TEXT NOT NULL DEFAULT 'campaign_total'
  CHECK(goal_scope IN ('campaign_total','per_item')),
 status TEXT NOT NULL DEFAULT 'active'
  CHECK(status IN ('draft','active','paused','completed','cancelled')),
 idempotency_key TEXT UNIQUE,
 created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
 updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX idx_review_campaigns_status_dates
  ON review_campaigns(status,start_date,end_date);

CREATE TABLE review_campaign_items (
 id INTEGER PRIMARY KEY,
 campaign_id INTEGER NOT NULL REFERENCES review_campaigns(id) ON DELETE RESTRICT,
 curriculum_subject_id INTEGER REFERENCES disciplinas_grade(id) ON DELETE RESTRICT,
 study_id INTEGER NOT NULL REFERENCES materias_estudo(id) ON DELETE RESTRICT,
 weight REAL NOT NULL DEFAULT 1 CHECK(weight>0),
 item_status TEXT NOT NULL DEFAULT 'active'
  CHECK(item_status IN ('active','paused','completed','removed')),
 created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
 updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
 UNIQUE(campaign_id,study_id)
);
CREATE INDEX idx_review_campaign_items_study
  ON review_campaign_items(study_id,item_status,campaign_id);

-- Mantém a proveniência da agenda e do tempo real quando a revisão vem de uma
-- campanha. Nulos preservam integralmente os registros anteriores.
ALTER TABLE sessoes_planejadas ADD COLUMN review_campaign_id INTEGER
  REFERENCES review_campaigns(id) ON DELETE SET NULL;
ALTER TABLE sessoes_estudo ADD COLUMN review_campaign_id INTEGER
  REFERENCES review_campaigns(id) ON DELETE SET NULL;
CREATE INDEX idx_planned_review_campaign
  ON sessoes_planejadas(review_campaign_id,scheduled_date);
CREATE INDEX idx_sessions_review_campaign
  ON sessoes_estudo(review_campaign_id,date);
