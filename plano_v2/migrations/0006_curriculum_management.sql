-- Gestão curricular: separa situação acadêmica, intenção de revisão e estrutura
-- de grade. Não há saneamento automático de registros antigos nesta migration.
ALTER TABLE disciplinas_grade ADD COLUMN review_status TEXT NOT NULL DEFAULT 'none'
    CHECK(review_status IN ('none','queued','in_progress','reviewed'));
ALTER TABLE disciplinas_grade ADD COLUMN review_priority INTEGER
    CHECK(review_priority IS NULL OR review_priority BETWEEN 1 AND 5);
ALTER TABLE disciplinas_grade ADD COLUMN review_notes TEXT;
ALTER TABLE disciplinas_grade ADD COLUMN item_type TEXT NOT NULL DEFAULT 'subject'
    CHECK(item_type IN ('subject','section'));

-- A proveniência permite restaurar somente estudos que foram arquivados junto
-- com a formação, sem reviver tentativas encerradas por outro motivo.
ALTER TABLE materias_estudo ADD COLUMN archive_reason TEXT
    CHECK(archive_reason IS NULL OR archive_reason IN ('manual','formation','curriculum','removed_current'));
ALTER TABLE materias_estudo ADD COLUMN archived_by_formation_id INTEGER;
ALTER TABLE materias_estudo ADD COLUMN status_before_archive TEXT
    CHECK(status_before_archive IS NULL OR status_before_archive IN ('active','paused','completed'));

CREATE TABLE curriculum_status_history (
 id INTEGER PRIMARY KEY,
 curriculum_subject_id INTEGER NOT NULL REFERENCES disciplinas_grade(id) ON DELETE RESTRICT,
 previous_academic_status TEXT,
 academic_status TEXT,
 previous_review_status TEXT,
 review_status TEXT,
 origin TEXT NOT NULL CHECK(origin IN ('manual','finish_study','new_attempt','review','merge','cleanup','import','remove_current','restore')),
 notes TEXT,
 created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE INDEX idx_curriculum_management_filter
    ON disciplinas_grade(formation_id, archived_at, item_type, academic_status, review_status, period, sort_order);
CREATE INDEX idx_curriculum_review_queue
    ON disciplinas_grade(review_status, review_priority)
    WHERE archived_at IS NULL AND item_type='subject';
CREATE INDEX idx_studies_archived_parent
    ON materias_estudo(archived_by_formation_id, archive_reason, status, archived_at);
CREATE INDEX idx_curriculum_status_history_subject
    ON curriculum_status_history(curriculum_subject_id, created_at DESC);
