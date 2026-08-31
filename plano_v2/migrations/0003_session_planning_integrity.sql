-- Valor-base de domínio e rastreabilidade de toda uma cadeia de revisões.
ALTER TABLE topicos ADD COLUMN manual_mastery INTEGER NOT NULL DEFAULT 0 CHECK(manual_mastery BETWEEN 0 AND 5);
UPDATE topicos SET manual_mastery = mastery;
ALTER TABLE revisoes ADD COLUMN root_session_id INTEGER REFERENCES sessoes_estudo(id) ON DELETE SET NULL;
UPDATE revisoes SET root_session_id = study_session_id WHERE root_session_id IS NULL;
CREATE INDEX idx_reviews_root_session ON revisoes(root_session_id);
UPDATE revisoes SET status = 'cancelled'
WHERE status = 'pending' AND id NOT IN (
  SELECT MIN(id) FROM revisoes WHERE status = 'pending' GROUP BY topic_id, review_stage
);
CREATE UNIQUE INDEX uq_pending_review_topic_stage ON revisoes(topic_id, review_stage) WHERE status='pending';
