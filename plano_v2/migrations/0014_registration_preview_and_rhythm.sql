-- Completa o contrato do ritmo adaptativo sem reescrever dados anteriores.
-- O bloco e a frequência passam a fazer parte de cada recomendação imutável.

ALTER TABLE recommendation_snapshots ADD COLUMN recommended_block_minutes INTEGER
  CHECK(recommended_block_minutes IS NULL OR recommended_block_minutes > 0);
ALTER TABLE recommendation_snapshots ADD COLUMN applied_block_minutes INTEGER
  CHECK(applied_block_minutes IS NULL OR applied_block_minutes > 0);
ALTER TABLE recommendation_snapshots ADD COLUMN recommended_days_per_week INTEGER
  CHECK(recommended_days_per_week IS NULL OR recommended_days_per_week BETWEEN 0 AND 7);

ALTER TABLE recommendation_decisions ADD COLUMN previous_block_minutes INTEGER
  CHECK(previous_block_minutes IS NULL OR previous_block_minutes > 0);
ALTER TABLE recommendation_decisions ADD COLUMN applied_block_minutes INTEGER
  CHECK(applied_block_minutes IS NULL OR applied_block_minutes > 0);

CREATE INDEX idx_observations_deadline_check
  ON study_observations(study_subject_id,observed_at DESC)
  WHERE kind='deadline_check';
