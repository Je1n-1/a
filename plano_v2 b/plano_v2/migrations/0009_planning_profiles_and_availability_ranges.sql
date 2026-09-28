-- Perfis de planejamento explícitos. Os valores provisórios permitem iniciar
-- uma disciplina sem esconder a pendência de refinamento para o usuário.
ALTER TABLE disciplinas_grade ADD COLUMN effort_is_provisional INTEGER NOT NULL DEFAULT 0
  CHECK(effort_is_provisional IN (0,1));
ALTER TABLE disciplinas_grade ADD COLUMN deadline_is_provisional INTEGER NOT NULL DEFAULT 0
  CHECK(deadline_is_provisional IN (0,1));
ALTER TABLE disciplinas_grade ADD COLUMN planning_profile_configured_at TEXT;

-- A recorrência semanal continua sendo a base. Esta tabela acrescenta uma
-- camada por intervalo: `replace` troca a recorrência dentro do período,
-- `available` soma uma faixa e `unavailable` remove uma faixa (ou o dia todo).
-- Várias linhas podem coexistir para representar mais de uma faixa por dia.
CREATE TABLE disponibilidades_intervalos (
 id INTEGER PRIMARY KEY,
 start_date TEXT NOT NULL CHECK(length(start_date)=10),
 end_date TEXT NOT NULL CHECK(length(end_date)=10 AND end_date>=start_date),
 start_time TEXT,
 end_time TEXT,
 kind TEXT NOT NULL CHECK(kind IN ('available','unavailable','replace')),
 all_day INTEGER NOT NULL DEFAULT 0 CHECK(all_day IN (0,1)),
 created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
 updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
 CHECK(
   (all_day=1 AND kind='unavailable' AND start_time IS NULL AND end_time IS NULL)
   OR
   (all_day=0 AND start_time IS NOT NULL AND end_time IS NOT NULL
    AND length(start_time)=5 AND length(end_time)=5 AND start_time<end_time)
 )
);
CREATE INDEX idx_availability_ranges_dates
  ON disponibilidades_intervalos(start_date,end_date,kind);
