"""Equivalências explícitas: associa referências, sem fundir sessões ou notas."""
from __future__ import annotations

import json
from database.repositories import core as repo
from database.repositories import curriculum_workspace as storage
from services import core, canonical_links
from services import curriculum_workspace as workspace


def _pair(left, right):
    if left == right:
        raise core.DomainError('Escolha uma disciplina de outra formação.')
    return tuple(sorted((left, right)))


def candidates(conn, ident):
    source = workspace.require_subject(conn, ident)
    _, group = storage.group(conn, ident)
    linked_ids = {r['id'] for r in group}
    result, separated = [], []
    for candidate in repo.many(conn, '''SELECT d.*,f.name formation_name,f.institution formation_institution
            FROM disciplinas_grade d JOIN formacoes f ON f.id=d.formation_id
            WHERE d.formation_id<>? AND d.item_type='subject' AND d.archived_at IS NULL AND f.archived_at IS NULL''', (source['formation_id'],)):
        if candidate['id'] in linked_ids:
            continue
        pair = _pair(ident, candidate['id'])
        decision = repo.one(conn, 'SELECT * FROM curriculum_equivalence_decisions WHERE left_id=? AND right_id=?', pair)
        score, evidence = canonical_links._candidate_score({**source, 'formation_institution': source['institution']}, candidate)
        candidate.update({'score': score, 'evidence': evidence})
        if decision and decision['decision'] == 'separate':
            separated.append(candidate)
        elif score >= 70:
            result.append(candidate)
    return {'candidates': sorted(result, key=lambda r: (-r['score'],r['id'])), 'separated': separated,
            'linked': [r for r in group if r['id'] != ident]}


def formation_overview(conn, formation_id):
    """Descoberta na grade, sem confirmar equivalências nem alterar conclusões."""
    formation = core._active_formation(conn, formation_id)
    subjects = repo.many(conn, '''SELECT d.*,f.name formation_name FROM disciplinas_grade d
        JOIN formacoes f ON f.id=d.formation_id WHERE d.item_type='subject'
        AND d.archived_at IS NULL AND f.archived_at IS NULL ORDER BY d.name,d.id''')
    local = [r for r in subjects if r['formation_id'] == formation_id]
    pairs = []
    for left in local:
        matches = candidates(conn, left['id'])
        for kind, key in (('suggestion', 'candidates'), ('linked', 'linked'), ('separate', 'separated')):
            for right in matches[key]:
                if right['archived_at'] or right.get('formation_archived_at'):
                    continue
                can_complete = (left['academic_status'] == 'completed') != (right['academic_status'] == 'completed')
                pairs.append({'left': left, 'right': right, 'kind': kind,
                              'can_complete': can_complete, 'evidence': right.get('evidence', [])})
    return {'formation': formation, 'pairs': pairs, 'subjects': local,
            'other_subjects': [r for r in subjects if r['formation_id'] != formation_id],
            'counts': {
                'suggestions': sum(p['kind'] == 'suggestion' for p in pairs),
                'shared_subjects': len({p['left']['id'] for p in pairs if p['kind'] == 'linked'}),
                'completion_subjects': len({p['left']['id'] for p in pairs
                    if p['can_complete'] and p['kind'] != 'separate'}),
            }}


def formation_preview(conn, formation_id, values):
    core._active_formation(conn, formation_id)
    pairs = values.get('pairs')
    if not isinstance(pairs, list) or not 1 <= len(pairs) <= 200:
        raise core.DomainError('Selecione de 1 a 200 correspondências para comparar.')
    previews, seen = [], set()
    for pair in pairs:
        if not isinstance(pair, dict) or any(type(pair.get(k)) is not int for k in ('left_id', 'right_id')):
            raise core.DomainError('Escolha duas disciplinas válidas para cada correspondência.')
        left = workspace.require_subject(conn, pair['left_id'], editable=True)
        if left['formation_id'] != formation_id:
            raise core.DomainError('A disciplina deve pertencer à formação aberta.', 409)
        preview = compare(conn, pair['left_id'], pair['right_id'])
        member_ids = {r['id'] for r in preview['members']}
        if seen & member_ids:
            raise core.DomainError('Uma disciplina ou grupo foi selecionado mais de uma vez. '
                                   'Confirme um vínculo por grupo e depois acrescente o outro curso.', 409)
        seen.update(member_ids)
        previews.append({'left_id': pair['left_id'], 'right_id': pair['right_id'], **preview})
    return {'pairs': previews}


def formation_apply(conn, formation_id, values):
    """Todos os vínculos e destinos escolhidos são gravados na mesma transação."""
    if not core._confirmed(values.get('confirmed')):
        raise core.DomainError('Compare as disciplinas e confirme sua seleção.')
    previews = formation_preview(conn, formation_id, values)['pairs']
    # Confere todas as versões antes da primeira escrita; a rota também faz rollback.
    for pair, preview in zip(values['pairs'], previews):
        if pair.get('version') != preview['version']:
            raise core.DomainError('Os dados mudaram. Volte à lista e compare novamente.', 409)
        targets = pair.get('completion_targets', [])
        valid = {r['id'] for r in preview['members'] if r['academic_status'] != 'completed'}
        if (not isinstance(targets, list) or any(type(i) is not int for i in targets)
                or len(set(targets)) != len(targets) or not set(targets) <= valid
                or (targets and not preview['completed_sources'])):
            raise core.DomainError('Escolha apenas destinos apresentados para aproveitar uma conclusão existente.', 409)
    affected_ids, affected_formations = set(), set()
    links, completions = 0, 0
    for pair, preview in zip(values['pairs'], previews):
        link(conn, pair['left_id'], pair['right_id'], {**pair, 'confirmed': True})
        links += not preview['already_linked']
        targets = pair.get('completion_targets', [])
        if targets:
            source_id = preview['completed_sources'][0]['id']
            validated = workspace.completion_targets(conn, source_id, {'completion_targets': targets})
            workspace.apply_status(conn, source_id, 'completed', validated)
            completions += len(validated)
        affected_ids.update(r['id'] for r in preview['members'])
        affected_formations.update(r['formation_id'] for r in preview['members'])
    return {'linked_pairs': links, 'completed_subjects': completions,
            'affected': {'curriculum_ids': sorted(affected_ids), 'formation_ids': sorted(affected_formations)}}


def decide_separate(conn, ident, other, values):
    left = workspace.require_subject(conn, ident, editable=True)
    right = workspace.require_subject(conn, other, editable=True)
    if left['formation_id'] == right['formation_id']:
        raise core.DomainError('A comparação deve envolver formações diferentes.')
    if other in {r['id'] for r in storage.group(conn, ident)[1]}:
        raise core.DomainError('Estas disciplinas já estão vinculadas. Use Desvincular para separá-las.', 409)
    decision = values.get('decision', 'separate')
    if decision not in {'separate','reconsider'}:
        raise core.DomainError('Decisão inválida.')
    conn.execute('''INSERT INTO curriculum_equivalence_decisions(left_id,right_id,decision,decided_at)
        VALUES (?,?,?,?) ON CONFLICT(left_id,right_id) DO UPDATE SET decision=excluded.decision,decided_at=excluded.decided_at''',
        (*_pair(ident, other), decision, workspace.now()))
    return {'affected': workspace.affected(conn, ident, [right])}


def compare(conn, ident, other):
    left = workspace.require_subject(conn, ident, editable=True)
    right = workspace.require_subject(conn, other, editable=True)
    if left['formation_id'] == right['formation_id']:
        raise core.DomainError('Escolha uma disciplina de outra formação.')
    ca, ga = storage.group(conn, ident)
    cb, gb = storage.group(conn, other)
    members = sorted({r['id']: r for r in [*ga,*gb]}.values(), key=lambda r:(r['created_at'],r['id']))
    for row in members:
        workspace.require_subject(conn, row['id'], editable=True)
    if len({r['formation_id'] for r in members}) != len(members):
        raise core.DomainError('Os grupos possuem mais de uma ocorrência na mesma formação. Revise os vínculos antes de unir.', 409)
    summaries = []
    for row in (left, right):
        data = workspace.detail(conn, row['id'])
        summaries.append({'curriculum': row, 'personal': data['personal'], 'topics': data['contents'],
                          'sessions': data['resources']['sessions'], 'notes': data['resources']['notes'],
                          'assessments': data['assessment_history'],
                          'session_count': data['resources']['session_count'], 'note_count': data['resources']['note_count']})
    conflicts = [key for key in ('difficulty','mastery') if len({s['personal'][key] for s in summaries if s['personal'][key] is not None}) > 1]
    snapshot = {'members': members, 'sides': summaries, 'canonical_ids': [ca,cb]}
    return {**snapshot, 'version': workspace.digest(snapshot), 'conflicts': conflicts,
            'default_reference_id': members[0]['id'], 'already_linked': bool(ca and ca == cb),
            'preserves_all_topics': True, 'completed_sources': [r for r in members if r['academic_status']=='completed']}


def _neutral_study(conn, ident, member_ids):
    marks=','.join('?' for _ in member_ids)
    # Após desvincular, um estudo de origem pode continuar sendo referência de
    # outro grupo. Reutilizá-lo aqui uniria esse grupo sem confirmação.
    study = repo.one(conn, f'''SELECT s.* FROM materias_estudo s WHERE s.curriculum_subject_id=?
        AND NOT EXISTS(SELECT 1 FROM curriculum_study_links l WHERE l.canonical_study_id=s.id
            AND l.curriculum_subject_id NOT IN ({marks})) ORDER BY s.created_at,s.id LIMIT 1''', (ident,*member_ids))
    if study:
        return study['id']
    has_current=repo.one(conn,"SELECT id FROM materias_estudo WHERE curriculum_subject_id=? AND status IN ('active','paused')",(ident,))
    return repo.insert(conn, 'materias_estudo', {'origin':'curriculum','curriculum_subject_id':ident,
        'status':'archived' if has_current else 'paused','management_only':1,
        'difficulty_is_provisional':1, 'mastery_is_provisional':1})


def link(conn, ident, other, values):
    preview = compare(conn, ident, other)
    if not core._confirmed(values.get('confirmed')):
        raise core.DomainError('Compare as disciplinas e confirme o vínculo.')
    if preview['already_linked']:
        return {'linked': True, 'affected':workspace.affected(conn, ident)}
    if values.get('version') != preview['version']:
        raise core.DomainError('Os dados mudaram desde a comparação. Compare novamente.', 409, 'stale_comparison')
    members = preview['members']
    reference = values.get('reference_id', preview['default_reference_id'])
    if type(reference) is not int or reference not in {r['id'] for r in members}:
        raise core.DomainError('Referência inválida.')
    # Só autoavaliações conflitantes exigem decisão. Conteúdos e históricos de
    # ambos os lados permanecem separados por ID, mesmo com títulos iguais.
    choices = values.get('assessment_choices') or {}
    profiles = {s['curriculum']['id']:s['personal'] for s in preview['sides']}
    selected = dict(storage.profile(conn, storage.profile_owner(conn, reference)))
    for key in ('difficulty','mastery'):
        if key in preview['conflicts']:
            choice = choices.get(key)
            if type(choice) is not int or choice not in profiles:
                raise core.DomainError('Escolha qual autoavaliação usar em cada conflito.', 409, 'assessment_conflict')
            selected[key] = profiles[choice][key]
        elif selected[key] is None:
            selected[key] = next((p[key] for p in profiles.values() if p[key] is not None), None)
    canonical = _neutral_study(conn, reference, [r['id'] for r in members])
    # A preferência inicial é a ocorrência mais antiga. A escolha de valores
    # pessoais não move nenhuma sessão, nota, avaliação ou tópico.
    workspace.record_profile(conn, reference, selected, origin='equivalence')
    for member in members:
        previous = repo.one(conn, 'SELECT canonical_study_id FROM curriculum_study_links WHERE curriculum_subject_id=?', (member['id'],))
        conn.execute('''INSERT INTO curriculum_study_links(curriculum_subject_id,canonical_study_id,link_note)
            VALUES (?,?,?) ON CONFLICT(curriculum_subject_id) DO UPDATE SET canonical_study_id=excluded.canonical_study_id,
            link_note=excluded.link_note,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')''',
            (member['id'], canonical, 'Equivalência confirmada; registros preservados na origem.'))
        if not previous or previous['canonical_study_id'] != canonical:
            repo.insert(conn, 'curriculum_study_link_audit', {'action':'linked','curriculum_subject_id':member['id'],
                'canonical_study_id':canonical,'details':json.dumps({'reference_id':reference,'previous':previous,
                    'preserved_origin':True,'assessment_choices':choices},ensure_ascii=False)})
    conn.execute('''INSERT INTO curriculum_profile_reference(canonical_study_id,curriculum_subject_id) VALUES (?,?)
        ON CONFLICT(canonical_study_id) DO UPDATE SET curriculum_subject_id=excluded.curriculum_subject_id''', (canonical,reference))
    return {'linked':True, 'affected':workspace.affected(conn,ident),
            'completion_offer':workspace.completion_preview(conn,preview['completed_sources'][0]['id']) if preview['completed_sources'] else None}


def unlink_preview(conn, ident):
    workspace.require_subject(conn,ident,editable=True)
    canonical,members = storage.group(conn,ident)
    resources = {key:storage.resources(conn,ident,table,field) for key,table,field in (
        ('topics','topicos','topic_id'),('sessions','sessoes_estudo','session_id'),('notes','anotacoes_estudo','note_id'))}
    resources['assessments'] = storage.assessments(conn, ident)
    snapshot = {'canonical_study_id':canonical,'members':members,
                'resources':{key:[r['id'] for r in rows] for key,rows in resources.items()}}
    return {**snapshot,'version':workspace.digest(snapshot),'counts':{k:len(v) for k,v in resources.items()},
            'message':'Os tópicos, sessões, notas e avaliações existentes continuam acessíveis por referência, com a origem preservada. Novos registros deixam de ser compartilhados. Conteúdos da outra formação ficam somente para consulta.'}


def unlink(conn, ident, values):
    preview = unlink_preview(conn,ident)
    if not core._confirmed(values.get('confirmed')):
        raise core.DomainError('Confira os dados que continuarão acessíveis e confirme.')
    if not preview['canonical_study_id']:
        return {'unlinked':True, 'affected':workspace.affected(conn,ident)}
    if values.get('version') != preview['version']:
        raise core.DomainError('Os vínculos mudaram. Reabra a prévia.',409)
    profile = storage.profile(conn,storage.profile_owner(conn,ident))
    canonical = preview['canonical_study_id']
    members = preview['members']
    for member in members:
        storage.retain_assessments(conn, member['id'], preview['resources']['assessments'], workspace.now())
        # Uma única referência para cada registro, nunca cópias das sessões.
        for kind,field in [('topics','topic_id'),('sessions','session_id'),('notes','note_id')]:
            for record_id in preview['resources'][kind]:
                conn.execute(f'INSERT OR IGNORE INTO curriculum_retained_access(curriculum_subject_id,{field},retained_at) VALUES (?,?,?)',
                             (member['id'],record_id,workspace.now()))
    conn.execute('DELETE FROM curriculum_study_links WHERE curriculum_subject_id=?',(ident,))
    workspace.record_profile(conn,ident,profile,origin='unlink')
    remaining = [r for r in members if r['id'] != ident]
    if remaining:
        next_owner = remaining[0]['id']
        workspace.record_profile(conn,next_owner,profile,origin='unlink')
        conn.execute('UPDATE curriculum_profile_reference SET curriculum_subject_id=? WHERE canonical_study_id=?',(next_owner,canonical))
    repo.insert(conn,'curriculum_study_link_audit',{'action':'unlinked','curriculum_subject_id':ident,
        'canonical_study_id':canonical,'details':json.dumps({'retained':preview['resources']},ensure_ascii=False)})
    return {'unlinked':True,'affected':workspace.affected(conn,ident,members)}
