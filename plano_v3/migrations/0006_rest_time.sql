ALTER TABLE timer_intervals ADD COLUMN is_rest INTEGER NOT NULL DEFAULT 0 CHECK(is_rest IN (0,1) AND (is_rest=0 OR kind='break'));
ALTER TABLE study_sessions ADD COLUMN rest_seconds INTEGER NOT NULL DEFAULT 0 CHECK(rest_seconds>=0);
ALTER TABLE session_days ADD COLUMN rest_seconds INTEGER NOT NULL DEFAULT 0 CHECK(rest_seconds>=0);

-- Um prazo ativo identifica o descanso ainda aberto. Sessões encerradas
-- permanecem como foram registradas, pois não guardavam essa distinção.
UPDATE timer_intervals SET is_rest=1
WHERE kind='break' AND ended_at IS NULL
AND timer_id IN (SELECT id FROM timers WHERE status='paused' AND break_until IS NOT NULL);
