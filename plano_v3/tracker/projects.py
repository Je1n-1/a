"""Projetos e etapas compartilham o relógio, sessões e rateio das disciplinas."""
from .domain import DomainError, clean, get, now
from . import catalog

FIELDS = ('project_id', 'project_name', 'step_id', 'step_name', 'project_course_id')


def listing(conn, archived=False, ident=None):
    return [dict(r) for r in conn.execute("""SELECT p.*,c.name course_name,
        COALESCE(t.total,0) step_count,COALESCE(t.done,0) completed_steps,
        COALESCE(x.seconds,0) effective_seconds,COALESCE(x.total,0) session_count
        FROM projects p LEFT JOIN courses c ON c.id=p.course_id
        LEFT JOIN (SELECT project_id,COUNT(*) total,SUM(completed) done FROM project_steps GROUP BY project_id) t ON t.project_id=p.id
        LEFT JOIN (SELECT project_id,COUNT(*) total,SUM(effective_seconds) seconds FROM study_sessions GROUP BY project_id) x ON x.project_id=p.id
        """ + ('WHERE p.id=? ' if ident is not None else '' if archived else 'WHERE p.archived_at IS NULL ') + 'ORDER BY p.id DESC', (ident,) if ident is not None else ())]


def detail(conn, ident):
    project = next(iter(listing(conn, True, ident)), None)
    if project is None:
        raise DomainError('Projeto não encontrado.', 404)
    project['steps'] = [dict(r) for r in conn.execute("""SELECT t.*,COALESCE(x.seconds,0) effective_seconds
        FROM project_steps t LEFT JOIN (SELECT step_id,SUM(effective_seconds) seconds FROM study_sessions GROUP BY step_id) x ON x.step_id=t.id
        WHERE t.project_id=? ORDER BY t.id""", (ident,))]
    project['recent'] = [dict(r) for r in conn.execute('SELECT * FROM study_sessions WHERE project_id=? ORDER BY local_date DESC,id DESC LIMIT 20', (ident,))]
    return project


def check_version(old, values):
    if type(values.get('version')) is not int or old['version'] != values['version']:
        raise DomainError('Este registro mudou em outra aba. Atualize antes de salvar.', 409)


def save(conn, values, ident=None):
    old = get(conn, 'projects', ident) if ident else {}
    if ident:
        check_version(old, values)
    name = clean(values.get('name', old.get('name')), 'Nome do projeto', required=True)
    objective = clean(values.get('objective', old.get('objective')), 'Objetivo', 5000)
    status = values.get('status', old.get('status', 'not_started'))
    if status not in ('not_started','in_progress','completed'):
        raise DomainError('Escolha uma situação válida para o projeto.')
    course = values.get('course_id', old.get('course_id'))
    if course is not None:
        if type(course) is not int:
            raise DomainError('Escolha um curso válido.')
        if course != old.get('course_id'):
            catalog.active_course(conn, course)
    archived = old.get('archived_at')
    if 'archived' in values:
        if type(values['archived']) is not bool:
            raise DomainError('Informe arquivar ou restaurar.')
        archived = (archived or now()) if values['archived'] else None
    if ident:
        conn.execute('UPDATE projects SET name=?,objective=?,course_id=?,status=?,archived_at=?,version=version+1 WHERE id=?', (name,objective,course,status,archived,ident))
    else:
        ident = conn.execute('INSERT INTO projects(name,objective,course_id,status,created_at) VALUES (?,?,?,?,?)', (name,objective,course,status,now())).lastrowid
    return detail(conn, ident)


def save_step(conn, project_id, values, ident=None):
    project = get(conn, 'projects', project_id)
    if project['archived_at']:
        raise DomainError('Restaure o projeto antes de alterar suas etapas.', 409)
    old = get(conn, 'project_steps', ident) if ident else {}
    if ident:
        if old['project_id'] != project_id:
            raise DomainError('A etapa pertence a outro projeto.')
        check_version(old, values)
    name = clean(values.get('name', old.get('name')), 'Nome da etapa', required=True)
    completed = values.get('completed', bool(old.get('completed', False)))
    if type(completed) is not bool:
        raise DomainError('Informe se a etapa foi concluída.')
    if ident:
        conn.execute('UPDATE project_steps SET name=?,completed=?,version=version+1 WHERE id=?', (name,int(completed),ident))
    else:
        ident = conn.execute('INSERT INTO project_steps(project_id,name,completed,created_at) VALUES (?,?,?,?)', (project_id,name,int(completed),now())).lastrowid
    return get(conn, 'project_steps', ident)


def link(conn, values, *, active=True):
    ident, step_id = values.get('project_id'), values.get('step_id')
    if ident is None:
        if step_id is not None:
            raise DomainError('Escolha um projeto para a etapa.')
        return dict.fromkeys(FIELDS)
    if type(ident) is not int or (step_id is not None and type(step_id) is not int):
        raise DomainError('Escolha projeto e etapa válidos.')
    if any(values.get(k) is not None for k in ('subject_id','topic_id')) or values.get('new_topic_name') or values.get('session_kind') == 'review':
        raise DomainError('Escolha um projeto ou uma disciplina para esta sessão.')
    project = get(conn, 'projects', ident)
    if active:
        if project['archived_at']:
            raise DomainError('Restaure o projeto antes de trabalhar nele.',409)
        if project['course_id'] is not None:
            catalog.active_course(conn, project['course_id'])
    step = get(conn, 'project_steps', step_id) if step_id is not None else None
    if step and step['project_id'] != ident:
        raise DomainError('A etapa pertence a outro projeto.')
    return dict(zip(FIELDS, (ident,project['name'],step_id,step['name'] if step else None,project['course_id'])))


def attach(conn, table, ident, values):
    assert table in ('timers','study_sessions')
    conn.execute(f'UPDATE {table} SET '+','.join(f'{k}=?' for k in FIELDS)+' WHERE id=?', (*[values[k] for k in FIELDS],ident))
