"""Execução manual. Não chama início/conclusão do planejador nem cria revisões."""
from datetime import datetime, timedelta, time, date
import json

from config import LOCAL_TIMEZONE
from database.repositories import core as repo, manual_workspace as storage, curriculum_workspace as curricular
from services import core, focus_tracking as pauses, manual_catalog, curriculum_workspace as workspace


def now():
    return datetime.now(LOCAL_TIMEZONE).replace(microsecond=0)


def stamp(value):
    return value.astimezone(LOCAL_TIMEZONE).isoformat(timespec='seconds')


def seconds(value, label, optional=False, maximum=86400):
    if optional and value in (None, ''):
        return None
    if isinstance(value, bool) or not str(value).isdigit() or not 1 <= int(value) <= maximum:
        raise core.DomainError(f'{label} deve ficar entre 1 segundo e {maximum//3600} horas.')
    return int(value)


def color(key):
    return f'hsl({(sum(ord(c) for c in key)*137)%360} 68% 66%)'


def focus_row(conn, ident):
    row = storage.focus(conn, ident)
    if not row:
        raise core.DomainError('Sessão de foco não encontrada.',404)
    return row


def active(conn):
    row = storage.active_focus(conn)
    return snapshot(conn, row['id']) if row else None


def snapshot(conn, ident):
    row = focus_row(conn, ident)
    current = now()
    elapsed = core._focus_elapsed_seconds(row, current)
    totals = pauses.pause_totals(conn, focus_id=ident, now=stamp(current))
    end = core._timestamp(row['ended_at']) if row['ended_at'] else current
    wall = max(0,int((end-core._timestamp(row['started_at'])).total_seconds()))
    note = repo.one(conn,'SELECT * FROM anotacoes_estudo WHERE id=?',(row['note_id'],)) if row['note_id'] else None
    key = row['subject_key'] or f'curriculum:{row["context_id"]}' if row['context_id'] else f'study:{row["study_subject_id"]}'
    return {**row, 'server_now':stamp(current), 'elapsed_seconds':elapsed,
        'pause_seconds':totals['pause_seconds'], 'wall_seconds':wall, 'breaks':totals['breaks'],
        'review_required':row['status']=='recovery_required' or (not row['ended_at'] and wall>=8*3600),
        'note':note, 'color':color(key), 'subject_key':key,
        'result':session_detail(conn,row['completed_study_session_id']) if row['completed_study_session_id'] else None}


def choices(conn, values, create_study=False):
    """Resolve IDs curriculares explicitamente; estado acadêmico não impede estudo."""
    curriculum_id = values.get('curriculum_id')
    study_id = values.get('study_id')
    if bool(curriculum_id) == bool(study_id):
        raise core.DomainError('Escolha uma disciplina.')
    if curriculum_id:
        curriculum_id = int(curriculum_id)
        subject = workspace.require_subject(conn,curriculum_id,editable=True)
        canonical,members = curricular.group(conn,curriculum_id)
        key = f'curriculum:{min(r["id"] for r in members)}'
        topics = curricular.resources(conn,curriculum_id,'topicos','topic_id')
        study_id = canonical
        if not study_id:
            current = repo.one(conn,'''SELECT id FROM materias_estudo WHERE curriculum_subject_id=?
                AND archived_at IS NULL AND status IN ('active','paused') ORDER BY created_at,id LIMIT 1''',(curriculum_id,))
            study_id = current['id'] if current else None
        if not study_id and create_study:
            study_id = repo.insert(conn,'materias_estudo',{'origin':'curriculum','curriculum_subject_id':curriculum_id,
                'status':'paused','management_only':1,'difficulty_is_provisional':1,'mastery_is_provisional':1})
        review = subject['academic_status'] in ('completed','exempted')
        name = subject['name']
    else:
        study_id = int(study_id)
        study = core._get(conn,'materias_estudo',study_id)
        if study['origin']!='personal' or study['archived_at'] or study['status']=='archived':
            raise core.DomainError('Escolha uma disciplina disponível na lista.',409)
        key,name,review = f'study:{study_id}',study['personal_name'],study['status']=='completed'
        topics = repo.many(conn,'SELECT * FROM topicos WHERE study_subject_id=? ORDER BY sort_order,id',(study_id,))
    topics = [t for t in topics if not t['archived_at']]
    topic_id = values.get('topic_id')
    if topic_id not in (None,''):
        topic_id = int(topic_id)
        if topic_id not in {t['id'] for t in topics}:
            raise core.DomainError('O tópico não pertence a esta matéria ou está arquivado.')
    else:
        topic_id = None  # Não seleciona conteúdo implicitamente.
    purpose = values.get('purpose') or ('review' if review else 'study')
    if purpose not in ('study','review'):
        raise core.DomainError('Finalidade de estudo inválida.')
    return {'study_id':study_id,'curriculum_id':curriculum_id,'topic_id':topic_id,
        'subject_key':key,'name':name,'topics':topics,'purpose':purpose}


def start(conn, values):
    if storage.active_focus(conn):
        raise core.DomainError('Já existe uma sessão ativa. Retome ou encerre antes de começar outra.',409)
    chosen = choices(conn, values, create_study=True)
    target = seconds(values.get('target_seconds'),'Duração desejada',optional=True)
    current = stamp(now())
    ident = repo.insert(conn,'sessoes_foco',{'study_subject_id':chosen['study_id'],
        'curriculum_context_id':chosen['curriculum_id'],'subject_key':chosen['subject_key'],
        'topic_id':chosen['topic_id'],'target_seconds':target,'purpose':chosen['purpose'],
        'manual_mode':1,'status':'running','started_at':current,'last_resumed_at':current})
    return snapshot(conn,ident)


def change_state(conn, ident, values, action):
    row = focus_row(conn,ident)
    desired = 'paused' if action=='pause' else 'running'
    if row['status']==desired:
        return snapshot(conn,ident)
    core._focus_assert_version(row,values)
    if row['status'] not in ('running','paused'):
        raise core.DomainError('Esta sessão não permite esta ação. Confira o estado atual.',409)
    current = stamp(now())
    if action=='pause':
        pauses.start_break(conn,ident,{'reason':values.get('reason'),'started_at':current})
        conn.execute('''UPDATE sessoes_foco SET status='paused',accumulated_seconds=?,
            paused_at=?,last_resumed_at=NULL,version=version+1 WHERE id=?''',
            (core._focus_elapsed_seconds(row,current),current,ident))
    else:
        pauses.finish_open_break(conn,ident,ended_at=current)
        conn.execute("UPDATE sessoes_foco SET status='running',paused_at=NULL,last_resumed_at=?,version=version+1 WHERE id=?",(current,ident))
    return snapshot(conn,ident)


def save_note(conn, ident, values):
    row = focus_row(conn,ident)
    if row['status']=='cancelled':
        raise core.DomainError('Esta sessão foi cancelada.',409)
    text = values.get('text','')
    if not isinstance(text,str) or len(text)>200000:
        raise core.DomainError('A anotação deve ser texto com até 200 mil caracteres.')
    note = repo.one(conn,'SELECT * FROM anotacoes_estudo WHERE id=?',(row['note_id'],)) if row['note_id'] else None
    if note and note['content_markdown']==text:
        return {'note':note,'revision':row['note_revision']}
    if values.get('revision') != row['note_revision']:
        raise core.DomainError('A anotação mudou em outra aba. Seu rascunho foi mantido para comparação.',409)
    if note:
        repo.update(conn,'anotacoes_estudo',note['id'],{'content_markdown':text})
        note_id=note['id']
    else:
        note_id=repo.insert(conn,'anotacoes_estudo',{'study_subject_id':row['study_subject_id'],
            'topic_id':row['topic_id'],'study_session_id':row['completed_study_session_id'],
            'title':f'Anotações de {row["subject_name"]}','content_markdown':text,
            'status':'final' if row['status']=='completed' else 'draft'})
    conn.execute('UPDATE sessoes_foco SET note_id=?,note_revision=note_revision+1 WHERE id=?',(note_id,ident))
    return {'note':repo.one(conn,'SELECT * FROM anotacoes_estudo WHERE id=?',(note_id,)), 'revision':row['note_revision']+1}


def timeline(start, end, breaks):
    """Intervalos disjuntos; um recorte escolhido nunca reescreve os eventos brutos."""
    result=[]
    cursor=start
    for row in breaks:
        if not row['started_at']:
            continue
        left=max(start,core._timestamp(row['started_at']))
        right=min(end,core._timestamp(row['ended_at']) if row['ended_at'] else end)
        if left>=right:
            continue
        left=max(cursor,left)
        if cursor<left:
            result.append(('focus',cursor,left))
        if right>left:
            result.append(('pause',left,right))
        cursor=max(cursor,right)
    if cursor<end:
        result.append(('focus',cursor,end))
    return result


def store_intervals(conn, session_id, intervals):
    for kind,left,right in intervals:
        duration=int((right-left).total_seconds())
        if duration>0:
            repo.insert(conn,'manual_session_intervals',{'study_session_id':session_id,'kind':kind,
                'started_at':stamp(left),'ended_at':stamp(right),'duration_seconds':duration})


def finish(conn, ident, values):
    row=focus_row(conn,ident)
    if row['status']=='completed':
        return snapshot(conn,ident)
    core._focus_assert_version(row,values)
    if row['status'] not in ('running','paused','recovery_required'):
        raise core.DomainError('Esta sessão não pode ser encerrada.',409)
    state=snapshot(conn,ident)
    if state['review_required'] and not core._confirmed(values.get('review_confirmed')):
        raise core.DomainError('A sessão está aberta há muitas horas. Confira os horários antes de salvar.',409)
    current=now()
    start_at=core._timestamp(row['started_at'])
    end_at=core._timestamp(values['reviewed_end_at']) if values.get('reviewed_end_at') else current
    if not start_at<end_at<=current:
        raise core.DomainError('O encerramento deve ficar depois do início e não pode estar no futuro.')
    intervals=timeline(start_at,end_at,state['breaks'])
    duration=sum(int((b-a).total_seconds()) for kind,a,b in intervals if kind=='focus')
    pause_seconds=sum(int((b-a).total_seconds()) for kind,a,b in intervals if kind=='pause')
    if not row['manual_mode']:
        # O legado pode não ter intervalos completos. Não inventa uma distribuição.
        duration=seconds(values.get('actual_seconds',state['elapsed_seconds']),'Duração efetiva',maximum=max(86400,state['wall_seconds']))
        if duration>int((end_at-start_at).total_seconds()):
            raise core.DomainError('A duração efetiva excede o período informado.')
        intervals=[]
    if duration<1:
        raise core.DomainError('A sessão precisa ter ao menos um segundo efetivo de estudo.')
    pauses.finish_open_break(conn,ident,ended_at=stamp(current))
    session_id=repo.insert(conn,'sessoes_estudo',{'study_subject_id':row['study_subject_id'],
        'curriculum_context_id':row['context_id'],'subject_key':state['subject_key'],'topic_id':row['topic_id'],
        'date':start_at.date().isoformat(),'started_at':stamp(start_at),'ended_at':stamp(end_at),
        'duration_seconds':duration,'pause_seconds':pause_seconds,'entry_method':'timer','purpose':row['purpose']})
    store_intervals(conn,session_id,intervals)
    conn.execute('UPDATE session_breaks SET study_session_id=? WHERE focus_session_id=?',(session_id,ident))
    if row['note_id']:
        repo.update(conn,'anotacoes_estudo',row['note_id'],{'study_session_id':session_id,'status':'final'})
    conn.execute('''UPDATE sessoes_foco SET status='completed',ended_at=?,accumulated_seconds=?,
        last_resumed_at=NULL,completed_study_session_id=?,version=version+1 WHERE id=?''',
        (stamp(current),state['elapsed_seconds'],session_id,ident))
    if end_at!=current or values.get('actual_seconds'):
        repo.insert(conn,'study_session_corrections',{'study_session_id':session_id,'correction_type':'edit_session',
            'before_json':json.dumps({'focus':row,'breaks':state['breaks']},ensure_ascii=False),
            'after_json':json.dumps(core._get(conn,'sessoes_estudo',session_id),ensure_ascii=False),
            'reason':'Horário/duração revisado explicitamente ao encerrar a sessão'})
    return snapshot(conn,ident)


def session_detail(conn, ident):
    row=storage.session(conn,ident)
    if not row:
        raise core.DomainError('Sessão não encontrada.',404)
    key=row['subject_key'] or (f'curriculum:{row["context_id"]}' if row['context_id'] else f'study:{row["study_subject_id"]}')
    return {**row,'color':color(key),'intervals':storage.intervals(conn,ident),
        'breaks':pauses.breaks_for_session(conn,ident),
        'annotations':repo.many(conn,'SELECT * FROM anotacoes_estudo WHERE study_session_id=? ORDER BY id',(ident,))}


def day_part(conn, row, start, end):
    intervals=storage.intervals(conn,row['id'])
    if intervals:
        totals={'focus':0,'pause':0}
        for item in intervals:
            left=max(start,core._timestamp(item['started_at']))
            right=min(end,core._timestamp(item['ended_at']))
            totals[item['kind']]+=max(0,int((right-left).total_seconds()))
        return totals
    # Sem horários confiáveis: atribui à data declarada, sem inventar intervalos.
    return {'focus':row['duration_seconds'] if row['date']==start.date().isoformat() else 0,
            'pause':row['pause_seconds'] if row['date']==start.date().isoformat() else 0}


def today(conn):
    current=now()
    start=datetime.combine(current.date(),time(),tzinfo=LOCAL_TIMEZONE)
    end=start+timedelta(days=1)
    rows=[]
    for item in storage.day_sessions(conn,start.date().isoformat(),stamp(start),stamp(end)):
        row=session_detail(conn,item['id'])
        part=day_part(conn,row,start,end)
        rows.append({**row,'today_focus_seconds':part['focus'],'today_pause_seconds':part['pause']})
    return {'date':current.date().isoformat(),'server_now':stamp(current),'active':active(conn),'sessions':rows,
        'total_seconds':sum(r['today_focus_seconds'] for r in rows),'pause_seconds':sum(r['today_pause_seconds'] for r in rows)}


def manual_entry(conn, values):
    chosen=choices(conn,values,create_study=True)
    try:
        day=date.fromisoformat(values.get('date',''))
    except (ValueError,TypeError) as error:
        raise core.DomainError('Informe uma data válida.') from error
    current=now()
    if day>current.date():
        raise core.DomainError('Um registro realizado não pode estar no futuro.')
    duration=seconds(values.get('duration_seconds'),'Duração efetiva')
    raw=values.get('pauses',[])
    if not isinstance(raw,list) or len(raw)>100:
        raise core.DomainError('Informe uma lista de até 100 pausas.')
    clean=[]
    for item in raw:
        if not isinstance(item,dict):
            raise core.DomainError('Pausa inválida.')
        clean.append({'duration_seconds':seconds(item.get('duration_seconds'),'Duração da pausa'),
            'reason':pauses._reason(item.get('reason'))})
    pause_seconds=sum(r['duration_seconds'] for r in clean)
    beginning=datetime.combine(day,time(),tzinfo=LOCAL_TIMEZONE)
    available=min(86400,max(0,int((current-beginning).total_seconds())))
    booked=sum(sum(day_part(conn,session_detail(conn,r['id']),beginning,beginning+timedelta(days=1)).values())
        for r in storage.day_sessions(conn,day.isoformat(),stamp(beginning),stamp(beginning+timedelta(days=1))))
    running=active(conn)
    if running:
        overlap=max(0,int((min(current,beginning+timedelta(days=1))-max(beginning,core._timestamp(running['started_at']))).total_seconds()))
        booked+=min(available,overlap)
    if duration+pause_seconds+booked>available:
        raise core.DomainError('A soma dos registros e pausas excede o tempo disponível nesse dia. Confira a duração.')
    if values.get('notes') is not None and not isinstance(values['notes'],str):
        raise core.DomainError('O comentário deve ser texto.')
    ident=repo.insert(conn,'sessoes_estudo',{'study_subject_id':chosen['study_id'],
        'curriculum_context_id':chosen['curriculum_id'],'subject_key':chosen['subject_key'],
        'topic_id':chosen['topic_id'],'date':day.isoformat(),'duration_seconds':duration,
        'pause_seconds':pause_seconds,'entry_method':'manual','purpose':chosen['purpose'],
        'notes':values.get('notes') or None})
    for item in clean:
        repo.insert(conn,'session_breaks',{'study_session_id':ident,**item,'origin':'retroactive_duration','subtracts_from_focus':0})
    return session_detail(conn,ident)


def feedback(conn, ident, values):
    row=session_detail(conn,ident)
    if values.get('version')!=row['version']:
        raise core.DomainError('O registro mudou em outra aba. Reabra antes de editar.',409)
    comment=values.get('notes')
    if comment is not None:
        if not isinstance(comment,str) or len(comment)>200000:
            raise core.DomainError('Comentário inválido.')
        repo.update(conn,'sessoes_estudo',ident,{'notes':comment})
    if values.get('topic_status') or 'topic_mastery' in values:
        if not row['topic_id'] or not row['context_id']:
            raise core.DomainError('Este registro não permite editar um tópico curricular.')
        payload={}
        if values.get('topic_status'):
            if values['topic_status'] not in ('not_started','in_progress','completed'):
                raise core.DomainError('Situação do tópico inválida.')
            payload['status']=values['topic_status']
        if 'topic_mastery' in values:
            payload['mastery']=values['topic_mastery']
        workspace.save_topic(conn,row['context_id'],payload,row['topic_id'])
    if 'mastery' in values:
        if not row['context_id']:
            raise core.DomainError('Use a avaliação da disciplina curricular para informar domínio.')
        workspace.save(conn,row['context_id'],{'mastery':values['mastery']})
    conn.execute('UPDATE sessoes_estudo SET version=version+1 WHERE id=?',(ident,))
    return session_detail(conn,ident)
