"""Consultas do estudo manual nas tabelas existentes; sem planejamento."""
from database.repositories.core import many, one


def curricula(conn):
    return many(conn, '''SELECT d.*,f.name formation_name,f.archived_at formation_archived_at
        FROM disciplinas_grade d JOIN formacoes f ON f.id=d.formation_id
        WHERE d.item_type='subject' ORDER BY d.created_at,d.id''')


def personal_studies(conn):
    return many(conn, "SELECT * FROM materias_estudo WHERE origin='personal' ORDER BY id")


def active_focus(conn):
    return one(conn, "SELECT id FROM sessoes_foco WHERE status IN ('running','paused','recovery_required','finishing') ORDER BY id LIMIT 1")


def focus(conn, ident):
    return one(conn, '''SELECT fs.*,COALESCE(d.name,s.personal_name) subject_name,t.name topic_name,
        COALESCE(fs.curriculum_context_id,s.curriculum_subject_id) context_id
        FROM sessoes_foco fs JOIN materias_estudo s ON s.id=fs.study_subject_id
        LEFT JOIN disciplinas_grade d ON d.id=COALESCE(fs.curriculum_context_id,s.curriculum_subject_id)
        LEFT JOIN topicos t ON t.id=fs.topic_id WHERE fs.id=?''', (ident,))


def session(conn, ident):
    return one(conn, '''SELECT x.*,COALESCE(d.name,s.personal_name) subject_name,t.name topic_name,
        COALESCE(x.curriculum_context_id,s.curriculum_subject_id) context_id,
        f.name formation_name,fs.id focus_id
        FROM sessoes_estudo x JOIN materias_estudo s ON s.id=x.study_subject_id
        LEFT JOIN disciplinas_grade d ON d.id=COALESCE(x.curriculum_context_id,s.curriculum_subject_id)
        LEFT JOIN formacoes f ON f.id=d.formation_id LEFT JOIN topicos t ON t.id=x.topic_id
        LEFT JOIN sessoes_foco fs ON fs.completed_study_session_id=x.id WHERE x.id=?''', (ident,))


def day_sessions(conn, day, start, end):
    return many(conn, '''SELECT id FROM sessoes_estudo WHERE date=? OR
        (julianday(started_at)<julianday(?) AND julianday(ended_at)>julianday(?))
        ORDER BY date DESC,id DESC''', (day,end,start))


def intervals(conn, ident):
    return many(conn, 'SELECT * FROM manual_session_intervals WHERE study_session_id=? ORDER BY started_at,id', (ident,))


