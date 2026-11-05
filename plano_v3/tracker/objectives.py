"""Objectives own a path; optional links read existing study records without copying them."""
import hashlib
import json
import re
from .domain import DomainError, clean, get, now
from . import topics

KINDS = {'subject': ('subjects', 'subject_id'), 'topic': ('topics', 'topic_id'),
         'project': ('projects', 'project_id'), 'step': ('project_steps', 'step_id')}
STATUSES = ('not_started', 'in_progress', 'completed')


def catalog(conn):
    result = []
    queries = {
        'subject': "SELECT s.id,s.name,s.course_id,s.academic_status state,s.version,s.archived_at,c.name parent,c.archived_at parent_archived FROM subjects s JOIN courses c ON c.id=s.course_id",
        'topic': "SELECT t.id,t.name,t.subject_id,s.course_id,c.name course,t.completed,t.needs_review,t.version,s.name parent,COALESCE(s.archived_at,c.archived_at) archived_at,EXISTS(SELECT 1 FROM study_sessions x WHERE x.topic_id=t.id) has_sessions FROM topics t JOIN subjects s ON s.id=t.subject_id JOIN courses c ON c.id=s.course_id",
        'project': "SELECT id,name,status state,version,archived_at,'' parent FROM projects",
        'step': "SELECT st.id,st.name,st.project_id,st.completed,st.version,p.name parent,p.archived_at,EXISTS(SELECT 1 FROM study_sessions x WHERE x.step_id=st.id) has_sessions FROM project_steps st JOIN projects p ON p.id=st.project_id",
    }
    for kind, query in queries.items():
        for record in conn.execute(query):
            row = dict(record)
            state = row.get('state')
            completed = bool(row.get('completed')) or state in ('completed', 'exempted')
            if kind in ('subject', 'topic'):
                subject_id = row['id'] if kind == 'subject' else row['subject_id']
                url = f"/subjects?course={row['course_id']}&subject={subject_id}"
                if kind == 'topic':
                    url += f"&topic={row['id']}"
            else:
                url = f"/projects?project={row['id'] if kind == 'project' else row['project_id']}"
                if kind == 'step':
                    url += f"#step-{row['id']}"
            if row.get('archived_at') or row.get('parent_archived'):
                url = url.replace('?', '?archived=1&', 1)
            result.append({'kind': kind, 'id': row['id'], 'name': row['name'], 'parent': row['parent'],
                           'course': row.get('course', ''), 'url': url,
                           'status': 'completed' if completed else 'in_progress' if state == 'in_progress' or row.get('has_sessions') else 'not_started',
                           'needs_review': bool(row.get('needs_review')), 'version': row['version'],
                           'archived': bool(row.get('archived_at') or row.get('parent_archived'))})
    return result


def source_map(conn):
    return {(s['kind'], s['id']): s for s in catalog(conn)}


def key(value, label):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,60}', value):
        raise DomainError(label + ': use uma chave única com letras, números, hífen ou sublinhado.')
    return value


def validate(conn, document):
    if not isinstance(document, dict) or type(document.get('schema_version')) is not int or document['schema_version'] != 1:
        raise DomainError('Use o formato de objetivos com schema_version 1.')
    obj = document.get('objective')
    if not isinstance(obj, dict):
        raise DomainError('O arquivo deve conter o objeto objective.')
    output = {'schema_version': 1, 'objective': {
        'title': clean(obj.get('title'), 'Objetivo', 200, True),
        'description': clean(obj.get('description'), 'Descrição', 5000), 'stages': []}}
    stages = obj.get('stages')
    if not isinstance(stages, list) or not 1 <= len(stages) <= 30:
        raise DomainError('Inclua de 1 a 30 etapas.')
    sources, stage_keys, tasks, used_sources = source_map(conn), set(), {}, set()
    for raw in stages:
        if not isinstance(raw, dict):
            raise DomainError('Cada etapa deve ser um objeto.')
        stage_key = key(raw.get('key'), 'Etapa')
        if stage_key in stage_keys:
            raise DomainError('As chaves das etapas devem ser diferentes.')
        stage_keys.add(stage_key)
        stage = {'key': stage_key, 'title': clean(raw.get('title'), 'Etapa', 200, True),
                 'description': clean(raw.get('description'), 'Descrição da etapa', 2000), 'tasks': []}
        rows = raw.get('tasks')
        if not isinstance(rows, list) or not rows:
            raise DomainError('Cada etapa precisa ter pelo menos um afazer.')
        for row in rows:
            if not isinstance(row, dict):
                raise DomainError('Cada afazer deve ser um objeto.')
            ident = key(row.get('key'), 'Afazer')
            if ident in tasks:
                raise DomainError('As chaves dos afazeres devem ser diferentes em todo o objetivo.')
            minutes = row.get('planned_minutes')
            if type(minutes) is not int or not 1 <= minutes <= 600000:
                raise DomainError('Horas previstas: use planned_minutes inteiro entre 1 e 600000.')
            source = row.get('source')
            if source is not None:
                if not isinstance(source, dict) or not isinstance(source.get('kind'), str) or source['kind'] not in KINDS or type(source.get('id')) is not int:
                    raise DomainError('Vínculo inválido. Use kind e id do contexto, ou null.')
                ref = (source['kind'], source['id'])
                if ref not in sources:
                    raise DomainError('Um vínculo não existe mais. Corrija a proposta antes de importar.')
                if ref in used_sources:
                    raise DomainError('O mesmo registro não pode aparecer em dois afazeres do objetivo. Vincule conteúdos específicos.')
                used_sources.add(ref)
                source = {'kind': ref[0], 'id': ref[1]}
            requires = row.get('requires', [])
            if not isinstance(requires, list) or len(requires) > 200:
                raise DomainError('Os requisitos devem ser uma lista de chaves.')
            requires = [key(v, 'Requisito') for v in requires]
            if len(requires) != len(set(requires)):
                raise DomainError('Remova requisitos repetidos.')
            task = {'key': ident, 'title': clean(row.get('title'), 'Afazer', 200, True),
                    'description': clean(row.get('description'), 'Descrição do afazer', 5000),
                    'planned_minutes': minutes, 'source': source, 'requires': requires}
            tasks[ident] = task
            stage['tasks'].append(task)
            if len(tasks) > 200:
                raise DomainError('Use no máximo 200 afazeres por objetivo.')
        output['objective']['stages'].append(stage)
    visiting, done = set(), set()

    def visit(ident):
        if ident not in tasks:
            raise DomainError('Há um requisito que não corresponde a nenhum afazer.')
        if ident in visiting:
            raise DomainError('Os requisitos formam um ciclo. Um afazer não pode depender de si, direta ou indiretamente.')
        if ident in done:
            return
        visiting.add(ident)
        for dependency in tasks[ident]['requires']:
            visit(dependency)
        visiting.remove(ident)
        done.add(ident)

    for ident in tasks:
        visit(ident)
    return output


def _signature(document):
    return hashlib.sha256(json.dumps(document, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def _check_version(old, values):
    if type(values.get('version')) is not int or values['version'] != old['version']:
        raise DomainError('Este objetivo mudou em outra aba. Atualize antes de salvar.', 409)


def _write_path(conn, ident, document, previous=None):
    previous = previous or {}
    ids, dependencies = {}, []
    for pos, stage in enumerate(document['objective']['stages']):
        sid = conn.execute('INSERT INTO objective_stages(objective_id,stage_key,title,description,position) VALUES (?,?,?,?,?)',
                           (ident, stage['key'], stage['title'], stage['description'], pos)).lastrowid
        for index, task in enumerate(stage['tasks']):
            source = task['source']
            refs = dict.fromkeys(['subject_id', 'topic_id', 'project_id', 'step_id'])
            if source:
                refs[KINDS[source['kind']][1]] = source['id']
            old = previous.get(task['key'], {})
            # Preserve manual state only while the same task retains the same source.
            same = all(old.get(column) == value for column, value in refs.items())
            status = old.get('status', 'not_started') if same else 'not_started'
            review = old.get('needs_review', 0) if same else 0
            ids[task['key']] = conn.execute('''INSERT INTO objective_tasks
                (objective_id,stage_id,task_key,title,description,position,planned_minutes,status,needs_review,subject_id,topic_id,project_id,step_id)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''', (ident, sid, task['key'], task['title'], task['description'], index,
                task['planned_minutes'], status, review, *refs.values())).lastrowid
            dependencies.extend((task['key'], dep) for dep in task['requires'])
    conn.executemany('INSERT INTO objective_dependencies VALUES (?,?)', [(ids[a], ids[b]) for a, b in dependencies])


def create(conn, values):
    document = validate(conn, values.get('document'))
    token = clean(values.get('operation_key'), 'Identificação da operação', 120, True)
    signature = _signature(document)
    old = conn.execute('SELECT * FROM objectives WHERE operation_key=?', (token,)).fetchone()
    if old:
        if old['request_signature'] != signature:
            raise DomainError('Esta operação já foi usada com outro conteúdo.', 409)
        return detail(conn, old['id'])
    stamp = now()
    obj = document['objective']
    ident = conn.execute('INSERT INTO objectives(title,description,created_at,updated_at,operation_key,request_signature) VALUES (?,?,?,?,?,?)',
                         (obj['title'], obj['description'], stamp, stamp, token, signature)).lastrowid
    _write_path(conn, ident, document)
    return detail(conn, ident)


def revise(conn, ident, values):
    old = get(conn, 'objectives', ident)
    _check_version(old, values)
    if old['archived_at']:
        raise DomainError('Restaure o objetivo antes de revisar o caminho.', 409)
    document = validate(conn, values.get('document'))
    previous = {r['task_key']: dict(r) for r in conn.execute('SELECT * FROM objective_tasks WHERE objective_id=?', (ident,))}
    conn.execute('DELETE FROM objective_tasks WHERE objective_id=?', (ident,))
    conn.execute('DELETE FROM objective_stages WHERE objective_id=?', (ident,))
    _write_path(conn, ident, document, previous)
    obj = document['objective']
    conn.execute('UPDATE objectives SET title=?,description=?,updated_at=?,version=version+1 WHERE id=?', (obj['title'], obj['description'], now(), ident))
    return detail(conn, ident)


def edit(conn, ident, values):
    old = get(conn, 'objectives', ident)
    _check_version(old, values)
    title = clean(values.get('title', old['title']), 'Objetivo', 200, True)
    description = clean(values.get('description', old['description']), 'Descrição', 5000)
    archived = old['archived_at']
    if 'archived' in values:
        if type(values['archived']) is not bool:
            raise DomainError('Informe arquivar ou restaurar.')
        archived = (archived or now()) if values['archived'] else None
    conn.execute('UPDATE objectives SET title=?,description=?,archived_at=?,updated_at=?,version=version+1 WHERE id=?',
                 (title, description, archived, now(), ident))
    return detail(conn, ident)


def edit_task(conn, ident, task_id, values):
    obj, task = get(conn, 'objectives', ident), get(conn, 'objective_tasks', task_id)
    _check_version(obj, values)
    if task['objective_id'] != ident or obj['archived_at']:
        raise DomainError('O afazer não está disponível neste objetivo.', 409)
    linked = any(task[column] is not None for _, column in KINDS.values())
    if 'status' in values:
        if linked:
            raise DomainError('O estado deste afazer vem do registro vinculado. Altere-o na origem.')
        if values['status'] not in STATUSES:
            raise DomainError('Escolha um estado válido.')
        conn.execute('UPDATE objective_tasks SET status=? WHERE id=?', (values['status'], task_id))
    if 'needs_review' in values:
        if type(values['needs_review']) is not bool:
            raise DomainError('Informe se o afazer precisa de revisão.')
        if task['topic_id'] is not None:
            topics.update(conn, task['topic_id'], {'version': values.get('source_version'), 'needs_review': values['needs_review']})
        else:
            conn.execute('UPDATE objective_tasks SET needs_review=? WHERE id=?', (int(values['needs_review']), task_id))
    conn.execute('UPDATE objectives SET updated_at=?,version=version+1 WHERE id=?', (now(), ident))
    return detail(conn, ident)


def detail(conn, ident, sources=None):
    obj = get(conn, 'objectives', ident)
    sources = sources if sources is not None else source_map(conn)
    stages = [dict(r) for r in conn.execute('SELECT * FROM objective_stages WHERE objective_id=? ORDER BY position,id', (ident,))]
    tasks = [dict(r) for r in conn.execute('SELECT * FROM objective_tasks WHERE objective_id=? ORDER BY stage_id,position,id', (ident,))]
    by_id = {t['id']: t for t in tasks}
    for task in tasks:
        task['requires'] = []
        task['source'] = None
        task['needs_review'] = bool(task['needs_review'])
        for kind, (_, column) in KINDS.items():
            if task[column] is not None:
                source = sources[(kind, task[column])]
                task['source'] = source
                task['status'] = source['status']
                if kind == 'topic':
                    task['needs_review'] = source['needs_review']
                break
    for row in conn.execute('''SELECT d.task_id,d.prerequisite_id FROM objective_dependencies d
            JOIN objective_tasks t ON t.id=d.task_id WHERE t.objective_id=?''', (ident,)):
        by_id[row['task_id']]['requires'].append(by_id[row['prerequisite_id']]['task_key'])
    conditions, args = [], []
    for task in tasks:
        if task['source']:
            column = KINDS[task['source']['kind']][1]
            conditions.append(column + '=?')
            args.append(task['source']['id'])
    records = [dict(r) for r in conn.execute('SELECT * FROM study_sessions WHERE ' + ' OR '.join(conditions) + ' ORDER BY local_date DESC,id DESC', args)] if conditions else []
    # OR selects each study_sessions row once, including parent/child overlapping links.
    for task in tasks:
        source = task['source']
        matched = [s for s in records if source and s[KINDS[source['kind']][1]] == source['id']]
        task['effective_seconds'] = sum(s['effective_seconds'] for s in matched)
        if source and task['status'] == 'not_started' and matched and source['kind'] in ('topic', 'step'):
            task['status'] = 'in_progress'
    by_key = {t['task_key']: t for t in tasks}
    for task in tasks:
        task['pending_requires'] = [k for k in task['requires'] if by_key[k]['status'] != 'completed' or by_key[k]['needs_review']]
    for stage in stages:
        stage['tasks'] = [t for t in tasks if t['stage_id'] == stage['id']]
        stage['completed'] = sum(t['status'] == 'completed' for t in stage['tasks'])
        stage['planned_minutes'] = sum(t['planned_minutes'] for t in stage['tasks'])
        stage['effective_seconds'] = sum(s['effective_seconds'] for s in records if any(t['source'] and s[KINDS[t['source']['kind']][1]] == t['source']['id'] for t in stage['tasks']))
    obj.update(stages=stages, task_count=len(tasks), completed=sum(t['status'] == 'completed' for t in tasks),
               planned_minutes=sum(t['planned_minutes'] for t in tasks), effective_seconds=sum(s['effective_seconds'] for s in records),
               review_count=sum(t['needs_review'] for t in tasks), recent=records[:5])
    obj['progress'] = round(100 * obj['completed'] / len(tasks)) if tasks else 0
    available = [t for t in tasks if not t['pending_requires'] and (t['status'] != 'completed' or t['needs_review'])]
    obj['next_task'] = (next((t for t in available if t['needs_review']), None)
                        or next((t for t in available if t['status'] == 'in_progress'), None)
                        or next(iter(available), None))
    obj['blocked_count'] = sum(t['status'] != 'completed' and bool(t['pending_requires']) for t in tasks)
    return obj


def listing(conn, archived=False):
    sources = source_map(conn)
    result = []
    for row in conn.execute('SELECT id FROM objectives WHERE archived_at IS ' + ('NOT NULL' if archived else 'NULL') + ' ORDER BY id DESC'):
        obj = detail(conn, row['id'], sources)
        obj.pop('stages')
        obj.pop('recent')
        result.append(obj)
    return result


def document(conn, ident):
    obj = detail(conn, ident)
    return {'schema_version': 1, 'objective': {'title': obj['title'], 'description': obj['description'],
        'stages': [{'key': s['stage_key'], 'title': s['title'], 'description': s['description'],
        'tasks': [{'key': t['task_key'], 'title': t['title'], 'description': t['description'], 'planned_minutes': t['planned_minutes'],
                   'source': {k: t['source'][k] for k in ('kind', 'id')} if t['source'] else None, 'requires': t['requires']} for t in s['tasks']]} for s in obj['stages']]}}
