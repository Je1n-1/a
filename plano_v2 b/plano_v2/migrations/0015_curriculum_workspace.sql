-- Etapa 2: dados pessoais opcionais e vínculos sem movimentar o histórico.
ALTER TABLE materias_estudo ADD COLUMN management_only INTEGER NOT NULL DEFAULT 0 CHECK(management_only IN (0,1));
ALTER TABLE topicos ADD COLUMN personal_mastery INTEGER CHECK(personal_mastery BETWEEN 1 AND 5);
ALTER TABLE topicos ADD COLUMN personal_mastery_set INTEGER NOT NULL DEFAULT 0 CHECK(personal_mastery_set IN (0,1));

CREATE TABLE curriculum_personal_profiles (
 curriculum_subject_id INTEGER PRIMARY KEY REFERENCES disciplinas_grade(id) ON DELETE RESTRICT,
 difficulty INTEGER CHECK(difficulty BETWEEN 1 AND 5),
 mastery INTEGER CHECK(mastery BETWEEN 0 AND 5),
 updated_at TEXT NOT NULL
);
CREATE TABLE curriculum_assessment_history (
 id INTEGER PRIMARY KEY,
 curriculum_subject_id INTEGER NOT NULL REFERENCES disciplinas_grade(id) ON DELETE RESTRICT,
 topic_id INTEGER REFERENCES topicos(id) ON DELETE RESTRICT,
 kind TEXT NOT NULL CHECK(kind IN ('difficulty','mastery')),
 previous_value INTEGER CHECK(previous_value BETWEEN 0 AND 5),
 value INTEGER CHECK(value BETWEEN 0 AND 5),
 origin TEXT NOT NULL,
 recorded_at TEXT NOT NULL
);
CREATE TABLE curriculum_profile_reference (
 canonical_study_id INTEGER PRIMARY KEY REFERENCES materias_estudo(id) ON DELETE RESTRICT,
 curriculum_subject_id INTEGER NOT NULL REFERENCES disciplinas_grade(id) ON DELETE RESTRICT
);
CREATE TABLE curriculum_equivalence_decisions (
 left_id INTEGER NOT NULL REFERENCES disciplinas_grade(id) ON DELETE RESTRICT,
 right_id INTEGER NOT NULL REFERENCES disciplinas_grade(id) ON DELETE RESTRICT,
 decision TEXT NOT NULL CHECK(decision IN ('separate','reconsider')),
 decided_at TEXT NOT NULL,
 PRIMARY KEY(left_id,right_id), CHECK(left_id < right_id)
);
-- Referências individuais preservam acesso após desvincular sem copiar dados,
-- sem alterar a origem e sem compartilhar registros criados futuramente.
CREATE TABLE curriculum_retained_access (
 id INTEGER PRIMARY KEY,
 curriculum_subject_id INTEGER NOT NULL REFERENCES disciplinas_grade(id) ON DELETE RESTRICT,
 topic_id INTEGER REFERENCES topicos(id) ON DELETE RESTRICT,
 session_id INTEGER REFERENCES sessoes_estudo(id) ON DELETE RESTRICT,
 note_id INTEGER REFERENCES anotacoes_estudo(id) ON DELETE RESTRICT,
 retained_at TEXT NOT NULL,
 CHECK((topic_id IS NOT NULL)+(session_id IS NOT NULL)+(note_id IS NOT NULL)=1),
 UNIQUE(curriculum_subject_id,topic_id), UNIQUE(curriculum_subject_id,session_id), UNIQUE(curriculum_subject_id,note_id)
);
CREATE TABLE curriculum_workspace_operations (
 operation_key TEXT PRIMARY KEY,
 request_hash TEXT NOT NULL,
 response_json TEXT NOT NULL,
 created_at TEXT NOT NULL
);
CREATE INDEX idx_curriculum_assessment_history ON curriculum_assessment_history(curriculum_subject_id,recorded_at,id);
