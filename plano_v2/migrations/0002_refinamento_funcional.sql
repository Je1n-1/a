-- Disponibilidade datada: complementa a recorrência semanal sem duplicar agendas.
CREATE TABLE excecoes_disponibilidade (
 id INTEGER PRIMARY KEY,
 date TEXT NOT NULL CHECK(length(date)=10),
 start_time TEXT NOT NULL CHECK(length(start_time)=5),
 end_time TEXT NOT NULL CHECK(length(end_time)=5),
 kind TEXT NOT NULL CHECK(kind IN ('available','unavailable')),
 created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
 updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
 CHECK(start_time < end_time)
);
CREATE INDEX idx_availability_exceptions_date ON excecoes_disponibilidade(date,start_time,end_time);
