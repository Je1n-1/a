-- Vínculos explícitos entre ocorrências curriculares que compartilham o mesmo
-- estudo pessoal. A equivalência nunca é inferida e aplicada automaticamente:
-- cada formação continua dona de seu estado acadêmico, nota, período e prazo.
CREATE TABLE curriculum_study_links (
 id INTEGER PRIMARY KEY,
 curriculum_subject_id INTEGER NOT NULL UNIQUE REFERENCES disciplinas_grade(id) ON DELETE RESTRICT,
 canonical_study_id INTEGER NOT NULL REFERENCES materias_estudo(id) ON DELETE RESTRICT,
 link_note TEXT,
 linked_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
 updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX idx_curriculum_study_links_canonical
  ON curriculum_study_links(canonical_study_id,curriculum_subject_id);

-- O histórico de uma decisão de compartilhamento não é descartado ao
-- desvincular. Isso permite auditoria e explica por que sessões antigas podem
-- pertencer ao estudo canônico após uma reconciliação explicitamente aceita.
CREATE TABLE curriculum_study_link_audit (
 id INTEGER PRIMARY KEY,
 action TEXT NOT NULL CHECK(action IN ('linked','merged_existing_study','unlinked')),
 curriculum_subject_id INTEGER NOT NULL REFERENCES disciplinas_grade(id) ON DELETE RESTRICT,
 canonical_study_id INTEGER NOT NULL REFERENCES materias_estudo(id) ON DELETE RESTRICT,
 previous_study_id INTEGER REFERENCES materias_estudo(id) ON DELETE SET NULL,
 details TEXT,
 created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX idx_curriculum_study_link_audit_subject
  ON curriculum_study_link_audit(curriculum_subject_id,created_at DESC);
