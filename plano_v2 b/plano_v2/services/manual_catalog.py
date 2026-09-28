"""Um estudo pessoal por grupo; contexto acadêmico separado por formação."""
from database.repositories import core as repo, curriculum_workspace as curricular, manual_workspace as storage
from services.canonical_links import _normal


def catalog(conn, filters=None, include_archived=False):
    filters = filters or {}
    result, seen = [], set()
    for row in storage.curricula(conn):
        if row['id'] in seen:
            continue
        canonical, members = curricular.group(conn, row['id'])
        seen.update(r['id'] for r in members)
        contexts = [r for r in members if include_archived or not (r['archived_at'] or r['formation_archived_at'])]
        if not contexts:
            continue
        preferred = contexts[0]
        study_ids = [r['id'] for r in repo.many(conn,
            'SELECT id FROM materias_estudo WHERE curriculum_subject_id IN ('+','.join('?' for _ in members)+')',
            [r['id'] for r in members])]
        result.append({'key':f'curriculum:{min(r["id"] for r in members)}',
                       'curriculum_id':preferred['id'], 'name':preferred['name'],
                       'canonical_study_id':canonical, 'study_ids':study_ids, 'contexts':contexts,
                       'shared':len(members)>1, 'personal':curricular.profile(conn,curricular.profile_owner(conn,row['id']))})
    for row in storage.personal_studies(conn):
        if not include_archived and row['archived_at']:
            continue
        result.append({'key':f'study:{row["id"]}', 'study_id':row['id'], 'name':row['personal_name'],
                       'curriculum_id':None, 'canonical_study_id':None, 'study_ids':[row['id']],
                       'contexts':[], 'shared':False, 'personal':{
                           'difficulty':None if row['difficulty_is_provisional'] else row['difficulty'],
                           'mastery':None if row['mastery_is_provisional'] else row['mastery_level']}})
    filtered=[]
    for item in result:
        matching=[c for c in item['contexts'] if
            (not filters.get('formation_id') or str(c['formation_id'])==str(filters['formation_id'])) and
            (not filters.get('status') or c['academic_status']==filters['status'])]
        if (filters.get('formation_id') or filters.get('status')) and not matching:
            continue
        if matching:
            item['curriculum_id']=matching[0]['id']
        names=' '.join([item['name'],*[c['name']+' '+c['formation_name']+' '+(c.get('code') or '') for c in item['contexts']]])
        if _normal(filters.get('q')) not in _normal(names):
            continue
        item['color']=f'hsl({(sum(ord(c) for c in item["key"])*137)%360} 68% 66%)'
        filtered.append(item)
    return sorted(filtered,key=lambda r:_normal(r['name']))


