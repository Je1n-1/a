-- Execução manual: metadados aditivos, sem reescrever sessões antigas.
ALTER TABLE sessoes_foco ADD COLUMN manual_mode INTEGER NOT NULL DEFAULT 0 CHECK(manual_mode IN (0,1));
ALTER TABLE sessoes_foco ADD COLUMN curriculum_context_id INTEGER REFERENCES disciplinas_grade(id) ON DELETE RESTRICT;
ALTER TABLE sessoes_foco ADD COLUMN subject_key TEXT;
ALTER TABLE sessoes_foco ADD COLUMN target_seconds INTEGER CHECK(target_seconds IS NULL OR target_seconds > 0);
ALTER TABLE sessoes_foco ADD COLUMN purpose TEXT NOT NULL DEFAULT 'study' CHECK(purpose IN ('study','review'));
ALTER TABLE sessoes_foco ADD COLUMN note_revision INTEGER NOT NULL DEFAULT 0 CHECK(note_revision >= 0);
ALTER TABLE sessoes_estudo ADD COLUMN curriculum_context_id INTEGER REFERENCES disciplinas_grade(id) ON DELETE RESTRICT;
ALTER TABLE sessoes_estudo ADD COLUMN subject_key TEXT;
CREATE UNIQUE INDEX uq_focus_manual_inflight ON sessoes_foco((1))
 WHERE status IN ('running','paused','recovery_required','finishing');

-- Intervalos efetivos para preservar a linha temporal, inclusive virada de dia.
CREATE TABLE manual_session_intervals (
 id INTEGER PRIMARY KEY,
 study_session_id INTEGER NOT NULL REFERENCES sessoes_estudo(id) ON DELETE RESTRICT,
 kind TEXT NOT NULL CHECK(kind IN ('focus','pause')),
 started_at TEXT NOT NULL,
 ended_at TEXT NOT NULL,
 duration_seconds INTEGER NOT NULL CHECK(duration_seconds > 0),
 CHECK(julianday(ended_at) > julianday(started_at)),
 UNIQUE(study_session_id,kind,started_at,ended_at)
);
CREATE INDEX idx_manual_intervals_session ON manual_session_intervals(study_session_id);
