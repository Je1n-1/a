-- Preserva acesso às avaliações já compartilhadas, sem copiá-las ou mudar a origem.
CREATE TABLE curriculum_retained_assessments (
 curriculum_subject_id INTEGER NOT NULL REFERENCES disciplinas_grade(id) ON DELETE RESTRICT,
 assessment_id INTEGER NOT NULL REFERENCES curriculum_assessment_history(id) ON DELETE RESTRICT,
 retained_at TEXT NOT NULL,
 PRIMARY KEY(curriculum_subject_id,assessment_id)
);
CREATE INDEX idx_retained_assessment ON curriculum_retained_assessments(assessment_id);
