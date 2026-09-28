-- Metadados opcionais da grade para importação fiel de planilhas institucionais.
ALTER TABLE disciplinas_grade ADD COLUMN start_date TEXT;
ALTER TABLE disciplinas_grade ADD COLUMN end_date TEXT;
ALTER TABLE disciplinas_grade ADD COLUMN notes TEXT;
