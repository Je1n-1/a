-- Anotações independentes das sessões, para rascunhos recuperáveis e exportação.
CREATE TABLE anotacoes_estudo (
 id INTEGER PRIMARY KEY,
 study_subject_id INTEGER NOT NULL REFERENCES materias_estudo(id) ON DELETE RESTRICT,
 topic_id INTEGER REFERENCES topicos(id) ON DELETE SET NULL,
 study_session_id INTEGER REFERENCES sessoes_estudo(id) ON DELETE SET NULL,
 planned_session_id INTEGER REFERENCES sessoes_planejadas(id) ON DELETE SET NULL,
 title TEXT NOT NULL CHECK(trim(title) <> ''),
 content_markdown TEXT NOT NULL DEFAULT '',
 tags TEXT NOT NULL DEFAULT '',
 status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','final')),
 created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
 updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE INDEX idx_notes_subject_updated ON anotacoes_estudo(study_subject_id, updated_at DESC);
CREATE INDEX idx_notes_topic_updated ON anotacoes_estudo(topic_id, updated_at DESC);
CREATE INDEX idx_notes_created_at ON anotacoes_estudo(created_at DESC);
CREATE INDEX idx_notes_session ON anotacoes_estudo(study_session_id);
