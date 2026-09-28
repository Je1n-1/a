"""Leitura de ocorrências e recursos compartilhados, sempre por IDs originais."""
from database.repositories.core import one, many


def subject(conn, ident):
    return one(conn, """SELECT d.*,f.name formation_name,f.institution,f.modality,
        f.archived_at formation_archived_at FROM disciplinas_grade d
        JOIN formacoes f ON f.id=d.formation_id WHERE d.id=?""", (ident,))


def group(conn, ident):
    link = one(conn, 'SELECT canonical_study_id FROM curriculum_study_links WHERE curriculum_subject_id=?', (ident,))
    if not link:
        # Compatibilidade com vínculos antigos que não registravam a origem.
        link = one(conn, """SELECT l.canonical_study_id FROM curriculum_study_links l
            JOIN materias_estudo s ON s.id=l.canonical_study_id WHERE s.curriculum_subject_id=?
            AND NOT EXISTS(SELECT 1 FROM curriculum_study_link_audit a
                WHERE a.curriculum_subject_id=? AND a.action='unlinked') LIMIT 1""", (ident, ident))
    if not link:
        return None, [subject(conn, ident)]
    canonical = link['canonical_study_id']
    rows = many(conn, """SELECT d.*,f.name formation_name,f.institution,f.modality,
        f.archived_at formation_archived_at FROM disciplinas_grade d
        JOIN formacoes f ON f.id=d.formation_id
        WHERE d.id IN (SELECT curriculum_subject_id FROM curriculum_study_links WHERE canonical_study_id=?)
        ORDER BY d.created_at,d.id""", (canonical,))
    primary = one(conn, '''SELECT s.curriculum_subject_id id FROM materias_estudo s WHERE s.id=?
        AND NOT EXISTS(SELECT 1 FROM curriculum_study_link_audit a
            WHERE a.curriculum_subject_id=s.curriculum_subject_id AND a.action='unlinked')''', (canonical,))
    if primary and primary['id'] not in {r['id'] for r in rows}:
        rows.append(subject(conn, primary['id']))
    if ident not in {r['id'] for r in rows}:
        rows.append(subject(conn, ident))
    return canonical, sorted(rows, key=lambda r: (r['created_at'], r['id']))


def resources(conn, ident, table, access_field):
    _, members = group(conn, ident)
    ids = [r['id'] for r in members]
    marks = ','.join('?' for _ in ids)
    direct = f"r.curriculum_subject_id IN ({marks}) OR " if table == 'topicos' else ''
    params = [*ids] if direct else []
    params.extend([*ids, *ids])
    # All attempts remain addressable; never rewrite the study/session origin.
    rows = many(conn, f"""SELECT DISTINCT r.* FROM {table} r WHERE {direct}
        r.study_subject_id IN (SELECT id FROM materias_estudo WHERE curriculum_subject_id IN ({marks}))
        OR r.id IN (SELECT {access_field} FROM curriculum_retained_access WHERE curriculum_subject_id IN ({marks}))
        ORDER BY r.id""", params)
    if table == 'topicos':
        own_studies = {r['id'] for r in many(conn, f'SELECT id FROM materias_estudo WHERE curriculum_subject_id IN ({marks})', ids)}
        for row in rows:
            row['read_only'] = row['curriculum_subject_id'] not in ids and row['study_subject_id'] not in own_studies
        rows.sort(key=lambda r: (r['sort_order'], r['id']))
    return rows


def assessments(conn, ident):
    _, members = group(conn, ident)
    ids = [r['id'] for r in members]
    marks = ','.join('?' for _ in ids)
    return many(conn, f'''SELECT h.*,d.name origin_subject_name,f.name origin_formation_name
        FROM curriculum_assessment_history h JOIN disciplinas_grade d ON d.id=h.curriculum_subject_id
        JOIN formacoes f ON f.id=d.formation_id
        WHERE h.curriculum_subject_id IN ({marks}) OR h.id IN (
            SELECT assessment_id FROM curriculum_retained_assessments
            WHERE curriculum_subject_id IN ({marks}))
        ORDER BY h.recorded_at DESC,h.id DESC''', [*ids, *ids])


def retain_assessments(conn, curriculum_id, assessment_ids, stamp):
    conn.executemany('''INSERT OR IGNORE INTO curriculum_retained_assessments
        (curriculum_subject_id,assessment_id,retained_at) VALUES (?,?,?)''',
        [(curriculum_id, ident, stamp) for ident in assessment_ids])


def profile(conn, ident):
    row = one(conn, 'SELECT * FROM curriculum_personal_profiles WHERE curriculum_subject_id=?', (ident,))
    if row:
        return {**row, 'legacy': False}
    study = one(conn, """SELECT * FROM materias_estudo WHERE curriculum_subject_id=?
        AND management_only=0 ORDER BY created_at,id LIMIT 1""", (ident,))
    return {
        'curriculum_subject_id': ident,
        'difficulty': study['difficulty'] if study and not study.get('difficulty_is_provisional') else None,
        'mastery': study.get('mastery_level') if study and not study.get('mastery_is_provisional') else None,
        'legacy': bool(study), 'updated_at': study['updated_at'] if study else None,
    }


def profile_owner(conn, ident):
    canonical, members = group(conn, ident)
    if canonical and len(members) > 1:
        ref = one(conn, 'SELECT curriculum_subject_id FROM curriculum_profile_reference WHERE canonical_study_id=?', (canonical,))
        return ref['curriculum_subject_id'] if ref else members[0]['id']
    return ident
