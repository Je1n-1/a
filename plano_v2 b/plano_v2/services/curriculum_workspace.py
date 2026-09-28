"""Gestão curricular da nova interface. Nenhuma operação aciona planejamento."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime

from config import LOCAL_TIMEZONE
from database.repositories import core as repo
from database.repositories import curriculum_workspace as storage
from services import core


def now():
    return datetime.now(LOCAL_TIMEZONE).isoformat(timespec='microseconds')


def require_subject(conn, ident, editable=False):
    row = storage.subject(conn, ident)
    if not row or row['item_type'] != 'subject':
        raise core.DomainError('Disciplina não encontrada.', 404)
    if editable and (row['archived_at'] or row['formation_archived_at']):
        raise core.DomainError('Restaure a disciplina e sua formação antes de editar.', 409)
    return row


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def repeatable(conn, scope, values, operation):
    """A rota já mantém BEGIN IMMEDIATE até commit; replay devolve o resultado."""
    key = values.get('operation_key')
    fingerprint = digest({'scope': scope, 'values': values})
    if key:
        if not isinstance(key, str) or len(key) > 160:
            raise core.DomainError('Identificador da operação inválido.')
        previous = repo.one(conn, 'SELECT * FROM curriculum_workspace_operations WHERE operation_key=?', (key,))
        if previous:
            if previous['request_hash'] != fingerprint:
                raise core.DomainError('Esta confirmação já foi usada. Atualize a prévia.', 409)
            return json.loads(previous['response_json'])
    result = operation()
    if key:
        repo.insert(conn, 'curriculum_workspace_operations', {
            'operation_key': key, 'request_hash': fingerprint,
            'response_json': json.dumps(result, ensure_ascii=False), 'created_at': now(),
        })
    return result


def affected(conn, ident, extra=()):
    _, members = storage.group(conn, ident)
    rows = {r['id']: r for r in [*members, *extra]}
    return {'curriculum_ids': sorted(rows), 'formation_ids': sorted({r['formation_id'] for r in rows.values()})}


def assessment_value(value, name, previous=None):
    if value in (None, ''):
        return None
    if isinstance(value, bool) or str(value) not in {'0', '1', '2', '3', '4', '5'}:
        raise core.DomainError(f'{name} deve ser um número inteiro de 1 a 5 ou Não informado.')
    number = int(value)
    if number == 0 and previous != 0:
        raise core.DomainError(f'{name} usa a escala de 1 a 5. O valor 0 só pode ser mantido de um registro antigo.')
    return number


def record_profile(conn, owner, values, origin='manual'):
    old = storage.profile(conn, owner)
    new = {k: assessment_value(values.get(k, old[k]), k,
            0 if k == 'mastery' and origin in {'equivalence', 'unlink'} and values.get(k) == 0 else old[k])
           for k in ('difficulty', 'mastery')}
    stamp = now()
    for key in new:
        if old[key] != new[key]:
            repo.insert(conn, 'curriculum_assessment_history', {
                'curriculum_subject_id': owner, 'kind': key, 'previous_value': old[key],
                'value': new[key], 'origin': origin, 'recorded_at': stamp,
            })
    conn.execute('''INSERT INTO curriculum_personal_profiles(curriculum_subject_id,difficulty,mastery,updated_at)
        VALUES (?,?,?,?) ON CONFLICT(curriculum_subject_id) DO UPDATE SET difficulty=excluded.difficulty,
        mastery=excluded.mastery,updated_at=excluded.updated_at''', (owner, new['difficulty'], new['mastery'], stamp))


def completion_preview(conn, ident):
    row = require_subject(conn, ident)
    _, group = storage.group(conn, ident)
    return {'source': row, 'destinations': [r for r in group if r['id'] != ident],
            'requires_choice': len(group) > 1,
            'version': digest([(r['id'], r['academic_status'], r['updated_at']) for r in group])}


def completion_targets(conn, ident, values):
    preview = completion_preview(conn, ident)
    targets = values.get('completion_targets')
    if preview['requires_choice'] and targets is None:
        raise core.DomainError('Escolha onde aproveitar a conclusão antes de salvar.', 409,
                               'completion_choice_required', details=preview)
    if targets is None:
        return []
    if not isinstance(targets, list) or any(type(i) is not int for i in targets):
        raise core.DomainError('Selecione as formações em que deseja concluir.')
    valid = {r['id'] for r in preview['destinations']}
    if len(set(targets)) != len(targets) or not set(targets) <= valid:
        raise core.DomainError('Um dos destinos não pertence ao vínculo atual. Reabra a confirmação.', 409)
    if values.get('completion_version') and values['completion_version'] != preview['version']:
        raise core.DomainError('A situação ou os vínculos mudaram. Reabra a confirmação.', 409)
    for target in targets:
        require_subject(conn, target, editable=True)
    return targets


def apply_status(conn, ident, status, targets=()):
    """Mesma regra para grade e detalhe; histórico somente quando há mudança."""
    source = require_subject(conn, ident, editable=True)
    for target in [ident, *targets]:
        current = require_subject(conn, target, editable=True)
        if current['academic_status'] == status:
            continue
        notes = ('Conclusão escolhida pelo usuário; origem: '
                 f"{source['name']} ({source['formation_name']}, disciplina {ident}). "
                 'Não representa reconhecimento institucional.') if target != ident else None
        core.change_curriculum_status(conn, target, {'academic_status': status}, 'manual', notes,
                                      completion_authorized=True)


def save(conn, ident, values):
    current = require_subject(conn, ident, editable=True)
    if values.get('expected_updated_at') and values['expected_updated_at'] != current['updated_at']:
        raise core.DomainError('Esta disciplina mudou em outra aba. Recarregue antes de salvar.', 409)
    status = values.get('academic_status', current['academic_status'])
    targets = completion_targets(conn, ident, values) if values.get('academic_status') == 'completed' else []
    if values.get('completion_targets') and status != 'completed':
        raise core.DomainError('O aproveitamento só se aplica à conclusão.')
    allowed = {'name', 'code', 'period', 'workload_minutes', 'start_date', 'end_date', 'notes', 'sort_order', 'academic_status'}
    payload = {k: v for k, v in values.items() if k in allowed}
    # Datas acadêmicas independentes do antigo prazo do planejador.
    validation = {**current, 'deadline_date': None}
    clean = core._curriculum_data(payload, validation)
    clean.pop('academic_status', None)
    previous_formation = current['formation_id']
    if 'formation_id' in values:
        try:
            formation_id = int(values['formation_id'])
        except (ValueError, TypeError):
            raise core.DomainError('Escolha uma formação válida.')
        core._active_formation(conn, formation_id)
        _, members = storage.group(conn, ident)
        if any(r['id'] != ident and r['formation_id'] == formation_id for r in members):
            raise core.DomainError('Já existe uma ocorrência vinculada nessa formação. Mantenha cursos distintos.', 409)
        clean['formation_id'] = formation_id
    try:
        if clean:
            repo.update(conn, 'disciplinas_grade', ident, clean)
    except sqlite3.IntegrityError as error:
        raise core.DomainError('Já existe uma disciplina com esse nome nessa formação.', 409) from error
    if 'academic_status' in values:
        apply_status(conn, ident, status, targets)
    if any(k in values for k in ('difficulty', 'mastery')):
        owner = storage.profile_owner(conn, ident)
        if 'expected_personal_updated_at' in values and values['expected_personal_updated_at'] != storage.profile(conn, owner)['updated_at']:
            raise core.DomainError('A autoavaliação mudou em outra aba. Feche e reabra para conferir os valores atuais.', 409)
        record_profile(conn, owner, values)
    event = affected(conn, ident)
    event['formation_ids'] = sorted(set([previous_formation, *event['formation_ids']]))
    return {'curriculum': require_subject(conn, ident), 'affected': event}


def contents_version(topics):
    """Detecta mudanças na lista, inclusive em outro curso do mesmo vínculo."""
    return digest([(t['id'], t['sort_order'], t['archived_at'], t['read_only']) for t in topics])


def detail(conn, ident):
    row = require_subject(conn, ident)
    canonical, members = storage.group(conn, ident)
    topics = storage.resources(conn, ident, 'topicos', 'topic_id')
    for topic in topics:
        topic['assessment_mastery'] = topic['personal_mastery'] if topic['personal_mastery_set'] else topic['manual_mastery']
        topic['legacy_mastery'] = not bool(topic['personal_mastery_set'])
        origin_id = topic['curriculum_subject_id']
        if not origin_id and topic['study_subject_id']:
            study = core._get(conn, 'materias_estudo', topic['study_subject_id'])
            origin_id = study['curriculum_subject_id']
        topic['origin_curriculum_id'] = origin_id
        origin = storage.subject(conn, origin_id) if origin_id else None
        topic['origin_name'] = origin['formation_name'] if origin else 'Histórico de estudo'
    active = [t for t in topics if not t['archived_at']]
    done = sum(t['status'] == 'completed' for t in active)
    owner = storage.profile_owner(conn, ident)
    sessions = storage.resources(conn, ident, 'sessoes_estudo', 'session_id')
    notes = storage.resources(conn, ident, 'anotacoes_estudo', 'note_id')
    return {'curriculum': row, 'personal': storage.profile(conn, owner), 'contents': topics,
        'contents_version': contents_version(topics),
        'content_progress': {'total': len(active), 'completed': done,
                             'percent': round(done * 100 / len(active)) if active else None},
        'linked_subjects': [r for r in members if r['id'] != ident], 'canonical_study_id': canonical,
        'history': core.curriculum_status_history(conn, ident),
        'assessment_history': storage.assessments(conn, ident),
        'resources': {'sessions': sessions, 'notes': notes, 'session_count': len(sessions), 'note_count': len(notes)},
        'affected': affected(conn, ident)}


def topic_for_edit(conn, ident, topic_id):
    require_subject(conn, ident, editable=True)
    topic = next((r for r in storage.resources(conn, ident, 'topicos', 'topic_id') if r['id'] == topic_id), None)
    if not topic:
        raise core.DomainError('Tópico não pertence a esta disciplina.', 404)
    if topic['read_only']:
        raise core.DomainError('Este conteúdo é uma referência preservada. Edite-o na formação de origem.', 409)
    return topic


def save_topic(conn, ident, values, topic_id=None):
    require_subject(conn, ident, editable=True)
    old = topic_for_edit(conn, ident, topic_id) if topic_id else None
    payload = {k: v for k, v in values.items() if k in {'name', 'description', 'sort_order', 'status'}}
    if 'sort_order' in payload:
        order = payload['sort_order']
        if isinstance(order, bool) or not str(order).isdigit():
            raise core.DomainError('A ordem deve ser um número inteiro não negativo.')
    elif not old:
        # Novos conteúdos entram ao final, também em listas compartilhadas.
        topics = storage.resources(conn, ident, 'topicos', 'topic_id')
        payload['sort_order'] = 1 + max((t['sort_order'] for t in topics if not t['archived_at']), default=-1)
    clean = core._content_data(payload)
    if 'name' in clean or not old:
        clean['name'] = core._need(clean.get('name'), 'Nome do tópico')
    if clean.get('sort_order', 0) < 0:
        raise core.DomainError('A ordem não pode ser negativa.')
    previous_mastery = (old['personal_mastery'] if old['personal_mastery_set'] else old['manual_mastery']) if old else None
    mastery = assessment_value(values.get('mastery', previous_mastery), 'Domínio', previous_mastery)
    if old:
        if old['archived_at']:
            raise core.DomainError('Restaure este tópico antes de editar.', 409)
        if values.get('expected_updated_at') and old['updated_at'] != values['expected_updated_at']:
            raise core.DomainError('O tópico mudou. Recarregue antes de salvar.', 409)
        if 'status' in clean and clean['status'] != old['status']:
            if clean['status'] in {'in_progress', 'completed'} and not old['started_at']:
                clean['started_at'] = now()
            clean['completed_at'] = now() if clean['status'] == 'completed' else None
        repo.update(conn, 'topicos', topic_id, clean)
    else:
        # O criador existente aceita conteúdos sem esforço e não chama o motor.
        topic_id = core.create_content(conn, ident, clean, enforce_effort=False)['id']
    if mastery != 0 and ('mastery' in values or not old):
        repo.update(conn, 'topicos', topic_id, {'personal_mastery': mastery, 'personal_mastery_set': 1})
    if previous_mastery != mastery:
        repo.insert(conn, 'curriculum_assessment_history', {'curriculum_subject_id': ident,
            'topic_id': topic_id, 'kind': 'mastery', 'previous_value': previous_mastery,
            'value': mastery, 'origin': 'manual', 'recorded_at': now()})
    return {'topic': core._get(conn, 'topicos', topic_id), 'affected': affected(conn, ident)}


def reorder(conn, ident, values):
    require_subject(conn, ident, editable=True)
    all_topics = storage.resources(conn, ident, 'topicos', 'topic_id')
    if 'expected_version' in values and values['expected_version'] != contents_version(all_topics):
        raise core.DomainError('A ordem dos tópicos mudou em outra aba. Atualize a lista antes de reordenar.', 409)
    topics = [r for r in all_topics if not r['archived_at'] and not r['read_only']]
    ids = values.get('topic_ids')
    if not isinstance(ids, list) or any(type(i) is not int for i in ids) or len(ids) != len(set(ids)) or set(ids) != {t['id'] for t in topics}:
        raise core.DomainError('A ordem deve conter cada tópico editável uma única vez. Atualize a lista.')
    for order, topic_id in enumerate(ids):
        repo.update(conn, 'topicos', topic_id, {'sort_order': order})
    return {'affected': affected(conn, ident)}


def topic_removal_preview(conn, ident, topic_id):
    topic = topic_for_edit(conn, ident, topic_id)
    references = 0
    for table, column in [('sessoes_estudo','topic_id'),('sessoes_planejadas','topic_id'),
            ('sessoes_foco','topic_id'),('anotacoes_estudo','topic_id'),('revisoes','topic_id'),
            ('avaliacao_topicos','topic_id'),('curriculum_retained_access','topic_id'),
            ('curriculum_assessment_history','topic_id'),('topic_dependencies','topic_id'),('topic_dependencies','prerequisite_topic_id')]:
        references += conn.execute(f'SELECT COUNT(*) FROM {table} WHERE {column}=?', (topic_id,)).fetchone()[0]
    return {'topic': topic, 'action': 'archive' if references else 'delete', 'references': references}


def remove_topic(conn, ident, topic_id, values):
    preview = topic_removal_preview(conn, ident, topic_id)
    if not core._confirmed(values.get('confirmed')):
        raise core.DomainError('Confira a consequência antes de remover o tópico.')
    if values.get('action') != preview['action']:
        raise core.DomainError('As referências mudaram. Confira novamente a remoção.', 409)
    if preview['action'] == 'archive':
        repo.update(conn, 'topicos', topic_id, {'archived_at': now()})
    else:
        repo.delete(conn, 'topicos', topic_id)
    return {'action': preview['action'], 'affected': affected(conn, ident)}


def restore_topic(conn, ident, topic_id):
    topic_for_edit(conn, ident, topic_id)
    repo.update(conn, 'topicos', topic_id, {'archived_at': None})
    return {'affected': affected(conn, ident)}
