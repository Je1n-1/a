"""Etapa 2: fixtures isoladas, sem gravar no banco pessoal."""
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo
from unittest.mock import patch
from tests import test_formations_redesign as base
from routes.curriculum_workspace import curriculum_workspace
from database import connection
from database.repositories import core as repo
from services import core


class CurriculumWorkspaceTest(base.FormationsRedesignTest):
    def setUp(self):
        super().setUp()
        self.client.application.register_blueprint(curriculum_workspace)
        self.clock = patch('services.curriculum_workspace.now', return_value='2026-09-28T10:00:00-03:00')
        self.clock.start()
        fixed=patch('services.core._local_now', return_value=datetime(2026,9,28,10,tzinfo=ZoneInfo('America/Sao_Paulo')))
        fixed.start()
        self.addCleanup(fixed.stop)
        self.ids=[]
        for course in ('Elétrica','Computação','Tecnologia'):
            payload=self.payload()
            payload['formation']['name']=course
            payload['items']=[{'name':'Circuitos I','period':'1','workload_hours':45,'include':True}]
            result=self.client.post('/api/formation-import/confirm',json=payload)
            self.assertEqual(result.status_code,200,result.json)
            self.ids.append(result.json['inserted'][0]['id'])

    def tearDown(self):
        try:
            with connection.connect() as conn:
                self.assertEqual(conn.execute('PRAGMA integrity_check').fetchone()[0],'ok')
                self.assertEqual(conn.execute('PRAGMA foreign_key_check').fetchall(),[])
                self.assertEqual(conn.execute('SELECT COUNT(*) FROM sessoes_planejadas').fetchone()[0],0)
                self.assertEqual(conn.execute('SELECT COUNT(*) FROM study_plan_baselines').fetchone()[0],0)
        finally:
            self.clock.stop()
            super().tearDown()

    def path(self,i=0,suffix=''):
        return f'/api/curriculum-workspace/{self.ids[i]}{suffix}'

    def detail(self,i=0):
        response=self.client.get(self.path(i))
        self.assertEqual(response.status_code,200,response.json)
        return response.json

    def link(self,left=0,right=1,**extra):
        path=self.path(left,f'/equivalences/{self.ids[right]}')
        preview=self.client.get(path)
        self.assertEqual(preview.status_code,200,preview.json)
        response=self.client.post(path,json={'confirmed':True,'version':preview.json['version'],**extra})
        self.assertEqual(response.status_code,200,response.json)
        return response.json

    def topic(self,i=0,**extra):
        response=self.client.post(self.path(i,'/contents'),json={'name':'Lei de Ohm',**extra})
        self.assertEqual(response.status_code,200,response.json)
        return response.json['topic']['id']

    # The inherited import tests have empty-database assumptions; run them in
    # their own existing class, not again with this three-course fixture.
    test_shell_has_no_global_pdf_account_or_planning = None
    test_preview_does_not_create_formation = None
    test_atomic_import_and_confirmation_repeat = None
    test_invalid_row_rolls_back_formation_and_subjects = None
    test_confirmation_and_selected_rows_required = None
    test_academic_status_progress_and_edit_without_planner = None
    test_reimport_skips_duplicates_and_preserves_completion = None

    def test_formation_equivalence_batch_and_explicit_completion(self):
        local = self.detail()['curriculum']['formation_id']
        self.client.patch(self.path(1), json={'academic_status':'completed'})
        topic_id = self.topic(1)
        route = f'/api/curriculum-workspace/formations/{local}/equivalences'
        overview = self.client.get(route)
        self.assertEqual(overview.status_code, 200, overview.json)
        self.assertEqual(overview.json['counts']['completion_subjects'], 1)
        pairs = [{'left_id':self.ids[0], 'right_id':self.ids[1]}]
        preview = self.client.post(route+'/preview', json={'pairs':pairs}).json
        # Conferir/cancelar não cria vínculo nem altera situações.
        self.assertEqual(self.detail()['linked_subjects'], [])
        self.assertEqual(self.detail()['curriculum']['academic_status'], 'not_available')
        payload = {'confirmed':True, 'operation_key':'formation-link',
                   'pairs':[{**pairs[0], 'version':preview['pairs'][0]['version'], 'completion_targets':[]}]}
        response = self.client.post(route+'/confirm', json=payload)
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(self.detail()['contents'][0]['id'], topic_id)
        self.assertEqual(self.detail()['curriculum']['academic_status'], 'not_available')
        self.assertEqual(self.client.post(route+'/confirm', json=payload).json, response.json)
        # Um vínculo existente continua oferecendo aproveitamento, sem recriá-lo.
        preview = self.client.post(route+'/preview', json={'pairs':pairs}).json
        payload = {'confirmed':True, 'operation_key':'formation-completion',
                   'pairs':[{**pairs[0], 'version':preview['pairs'][0]['version'], 'completion_targets':[self.ids[0]]}]}
        response = self.client.post(route+'/confirm', json=payload)
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(response.json['completed_subjects'], 1)
        self.assertEqual(response.json['linked_pairs'], 0)
        self.assertEqual(self.detail()['curriculum']['academic_status'], 'completed')
        self.assertEqual(self.detail(2)['curriculum']['academic_status'], 'not_available')
        self.assertEqual(self.client.post(route+'/confirm', json=payload).json, response.json)
        overview = self.client.get(route).json
        self.assertEqual(overview['counts']['shared_subjects'], 1)

    def test_formation_batch_rolls_back_all_pairs_on_conflict(self):
        local = self.detail()['curriculum']['formation_id']
        other = self.detail(1)['curriculum']['formation_id']
        with connection.connect() as conn:
            left = core.create_curriculum(conn, local, {'name':'Matemática'})['id']
            right = core.create_curriculum(conn, other, {'name':'Matemática equivalente'})['id']
        # O segundo par tem um conflito de domínio que exige decisão explícita.
        self.client.patch(f'/api/curriculum-workspace/{left}', json={'mastery':2})
        self.client.patch(f'/api/curriculum-workspace/{right}', json={'mastery':4})
        route = f'/api/curriculum-workspace/formations/{local}/equivalences'
        pairs = [{'left_id':self.ids[0], 'right_id':self.ids[1]}, {'left_id':left,'right_id':right}]
        preview = self.client.post(route+'/preview', json={'pairs':pairs})
        self.assertEqual(preview.status_code, 200, preview.json)
        payload = {'confirmed':True, 'operation_key':'atomic-formation', 'pairs':[
            {**pair, 'version':p['version'], 'completion_targets':[]}
            for pair,p in zip(pairs,preview.json['pairs'])]}
        response = self.client.post(route+'/confirm', json=payload)
        self.assertEqual(response.status_code, 409, response.json)
        self.assertEqual(self.detail()['linked_subjects'], [])
        with connection.connect() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM curriculum_study_links').fetchone()[0], 0)
        payload['pairs'][1]['assessment_choices'] = {'mastery':left}
        response = self.client.post(route+'/confirm', json=payload)
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(response.json['linked_pairs'], 2)

    def test_optional_fields_and_no_planning(self):
        response=self.client.patch(self.path(),json={'start_date':'','end_date':'','difficulty':None,'mastery':None})
        self.assertEqual(response.status_code,200,response.json)
        data=self.detail()
        self.assertIsNone(data['personal']['mastery'])
        self.assertIsNone(data['content_progress']['percent'])
        with connection.connect() as conn:
            self.assertEqual(conn.execute('select count(*) from materias_estudo').fetchone()[0],0)
            self.assertEqual(conn.execute('select count(*) from sessoes_planejadas').fetchone()[0],0)

    def test_assessments_timestamp_validation_and_replay(self):
        body={'mastery':4,'difficulty':2,'operation_key':'assessment-1'}
        for _ in range(2):
            self.assertEqual(self.client.patch(self.path(),json=body).status_code,200)
        data=self.detail()
        self.assertEqual(len(data['assessment_history']),2)
        self.assertEqual(data['assessment_history'][0]['recorded_at'],'2026-09-28T10:00:00-03:00')
        for bad in (0,6,1.5,True,'wrong'):
            self.assertEqual(self.client.patch(self.path(),json={'mastery':bad}).status_code,400)
        self.assertEqual(self.detail()['personal']['mastery'],4)

    def test_dates_invalid_and_whole_save_rollback(self):
        old=self.detail()['curriculum']
        response=self.client.patch(self.path(),json={'name':'Changed','start_date':'2026-10-10','end_date':'2026-09-28'})
        self.assertEqual(response.status_code,400)
        self.assertEqual(self.detail()['curriculum']['name'],old['name'])

    def test_topics_order_delete_archive_restore_and_legacy_status(self):
        first=self.topic(); second=self.topic(name='Kirchhoff',status='paused')
        self.assertEqual(self.client.post(self.path(0,'/contents/order'),json={'topic_ids':[second,first]}).status_code,200)
        self.assertEqual([t['id'] for t in self.detail()['contents']],[second,first])
        route=self.path(0,f'/contents/{first}')
        self.assertEqual(self.client.patch(route,json={'mastery':3,'description':'Notas'}).status_code,200)
        preview=self.client.get(route+'/removal').json
        self.assertEqual(preview['action'],'archive')
        self.assertEqual(self.client.post(route+'/removal',json={'confirmed':True,'action':'archive'}).status_code,200)
        self.assertEqual(self.detail()['content_progress']['total'],1)
        self.client.post(route+'/restore',json={})
        self.assertEqual(self.detail()['content_progress']['total'],2)
        route=self.path(0,f'/contents/{second}/removal')
        self.assertEqual(self.client.get(route).json['action'],'delete')
        self.assertEqual(self.client.post(route,json={'confirmed':True,'action':'delete'}).status_code,200)
        self.assertEqual(len(self.detail()['contents']),1)

    def test_stage4_optional_contents_order_and_independent_completion(self):
        self.assertIsNone(self.detail()['content_progress']['percent'])
        first = self.topic(sort_order=20, status='paused')
        payload = {'name':'Kirchhoff', 'operation_key':'stage4-create'}
        response = self.client.post(self.path(0, '/contents'), json=payload)
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(self.client.post(self.path(0, '/contents'), json=payload).json, response.json)
        second = response.json['topic']['id']
        data = self.detail()
        self.assertEqual([t['sort_order'] for t in data['contents']], [20, 21])
        self.assertIsNone(data['contents'][1]['estimated_minutes'])
        self.assertIsNone(data['contents'][1]['assessment_mastery'])
        version = data['contents_version']
        self.assertEqual(self.client.post(self.path(0, '/contents/order'), json={
            'topic_ids':[second, first], 'expected_version':version}).status_code, 200)
        self.assertEqual(self.client.post(self.path(0, '/contents/order'), json={
            'topic_ids':[first, second], 'expected_version':version}).status_code, 409)
        self.assertEqual([t['id'] for t in self.detail()['contents']], [second, first])
        for invalid in (-1, 1.5, True):
            self.assertEqual(self.client.patch(self.path(0, f'/contents/{first}'),
                json={'sort_order':invalid}).status_code, 400)
        # Editar um título não converte avaliação antiga em autoavaliação nova.
        with connection.connect() as conn:
            repo.update(conn, 'topicos', first, {'personal_mastery_set':0, 'manual_mastery':3})
        self.assertEqual(self.client.patch(self.path(0, f'/contents/{first}'),
            json={'name':'Lei de Ohm revisada'}).status_code, 200)
        legacy = next(t for t in self.detail()['contents'] if t['id']==first)
        self.assertTrue(legacy['legacy_mastery'])
        self.assertEqual(legacy['status'], 'paused')
        for topic_id in (first, second):
            self.assertEqual(self.client.patch(self.path(0, f'/contents/{topic_id}'),
                json={'status':'completed'}).status_code, 200)
        data = self.detail()
        self.assertEqual(data['content_progress']['percent'], 100)
        self.assertEqual(data['curriculum']['academic_status'], 'not_available')
        self.assertIsNone(data['personal']['mastery'])
        self.client.patch(self.path(0, f'/contents/{first}'), json={'status':'in_progress'})
        self.assertEqual(self.client.post(self.path(0, '/completion'), json={}).status_code, 200)
        self.assertEqual(self.detail()['content_progress']['percent'], 50)
        with connection.connect() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM revisoes').fetchone()[0], 0)

    def test_stage4_removal_preserves_sessions_notes_and_assessments(self):
        topic_id = self.topic(mastery=4)
        with connection.connect() as conn:
            study = repo.insert(conn, 'materias_estudo', {'origin':'curriculum',
                'curriculum_subject_id':self.ids[0], 'status':'paused'})
            session = repo.insert(conn, 'sessoes_estudo', {'study_subject_id':study,
                'topic_id':topic_id, 'date':'2026-09-28', 'duration_seconds':900, 'entry_method':'manual'})
            note = repo.insert(conn, 'anotacoes_estudo', {'study_subject_id':study,
                'topic_id':topic_id, 'title':'Nota de teste', 'content_markdown':'Preservar texto.'})
        path = self.path(0, f'/contents/{topic_id}')
        self.assertEqual(self.client.get(path+'/removal').json['action'], 'archive')
        self.assertEqual(self.client.post(path+'/removal', json={'confirmed':True, 'action':'delete'}).status_code, 409)
        archive = {'confirmed':True, 'action':'archive', 'operation_key':'stage4-archive'}
        response = self.client.post(path+'/removal', json=archive)
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(self.client.post(path+'/removal', json=archive).json, response.json)
        self.assertEqual(self.detail()['content_progress']['total'], 0)
        self.assertEqual(self.client.patch(path, json={'name':'Não deve salvar'}).status_code, 409)
        self.assertEqual(self.client.post(path+'/restore', json={}).status_code, 200)
        data = self.detail()
        self.assertEqual(data['content_progress']['total'], 1)
        self.assertEqual(data['contents'][0]['assessment_mastery'], 4)
        self.assertEqual(data['resources']['sessions'][0]['id'], session)
        self.assertEqual(data['resources']['notes'][0]['id'], note)
        self.assertEqual(data['resources']['notes'][0]['content_markdown'], 'Preservar texto.')
        self.assertEqual(data['assessment_history'][0]['topic_id'], topic_id)
        disposable = self.topic(name='Sem vínculos')
        delete_path = self.path(0, f'/contents/{disposable}/removal')
        self.assertEqual(self.client.get(delete_path).json['action'], 'delete')
        self.assertEqual(self.client.post(delete_path, json={'confirmed':True, 'action':'delete'}).status_code, 200)
        self.assertEqual([t['id'] for t in self.detail()['contents']], [topic_id])

    def test_academic_content_mastery_independent(self):
        self.topic(status='completed')
        self.assertEqual(self.detail()['curriculum']['academic_status'],'not_available')
        self.topic(name='Outro')
        self.client.post(self.path(0,'/completion'),json={})
        data=self.detail()
        self.assertEqual(data['content_progress']['percent'],50)
        self.assertIsNone(data['personal']['mastery'])

    def test_suggestions_separate_reconsider_and_no_implicit_link(self):
        route=self.path(0,'/equivalences')
        self.assertEqual(len(self.client.get(route).json['candidates']),2)
        self.assertEqual(self.detail()['linked_subjects'],[])
        decision=self.path(0,f'/equivalences/{self.ids[1]}/decision')
        self.client.post(decision,json={'decision':'separate'})
        self.assertEqual(len(self.client.get(route).json['separated']),1)
        self.client.post(decision,json={'decision':'reconsider'})
        self.assertEqual(len(self.client.get(route).json['candidates']),2)

    def test_stage5_preview_conflicts_and_retained_history(self):
        first = self.topic()
        second = self.topic(1)  # Mesmo título, IDs e origens independentes.
        self.client.patch(self.path(), json={'mastery':2})
        self.client.patch(self.path(1), json={'mastery':4, 'notes':'Somente Computação'})
        with connection.connect() as conn:
            study = repo.insert(conn, 'materias_estudo', {'origin':'curriculum',
                'curriculum_subject_id':self.ids[1], 'status':'paused'})
            session = repo.insert(conn, 'sessoes_estudo', {'study_subject_id':study,
                'topic_id':second, 'date':'2026-09-28', 'duration_seconds':600, 'entry_method':'manual'})
            note = repo.insert(conn, 'anotacoes_estudo', {'study_subject_id':study,
                'topic_id':second, 'title':'Origem', 'content_markdown':'Antes'})
        route = self.path(0, f'/equivalences/{self.ids[1]}')
        preview = self.client.get(route).json
        self.assertEqual(preview['sides'][1]['sessions'][0]['id'], session)
        self.assertEqual(preview['sides'][1]['notes'][0]['content_markdown'], 'Antes')
        self.assertEqual(preview['sides'][1]['assessments'][0]['origin_formation_name'], 'Computação')
        with connection.connect() as conn:
            repo.update(conn, 'anotacoes_estudo', note, {'content_markdown':'Texto corrigido'})
        self.assertEqual(self.client.post(route, json={'confirmed':True,
            'version':preview['version'], 'assessment_choices':{'mastery':self.ids[1]}}).status_code, 409)
        preview = self.client.get(route).json
        self.assertEqual(self.client.post(route, json={'confirmed':True, 'version':preview['version']}).status_code, 409)
        payload = {'confirmed':True, 'version':preview['version'],
            'assessment_choices':{'mastery':self.ids[1]}, 'operation_key':'stage5-link'}
        linked = self.client.post(route, json=payload)
        self.assertEqual(linked.status_code, 200, linked.json)
        self.assertEqual(self.client.post(route, json=payload).json, linked.json)
        self.assertEqual({t['id'] for t in self.detail()['contents']}, {first,second})
        self.assertEqual(self.detail()['personal']['mastery'], 4)
        self.assertIsNone(self.detail()['curriculum']['notes'])
        old_marks = {r['id'] for r in self.detail()['assessment_history']}
        preview = self.client.get(self.path(0, '/unlink')).json
        unlinked = self.client.post(self.path(0, '/unlink'), json={
            'confirmed':True, 'version':preview['version'], 'operation_key':'stage5-unlink'})
        self.assertEqual(unlinked.status_code, 200, unlinked.json)
        for index in (0,1):
            data = self.detail(index)
            self.assertTrue(old_marks <= {r['id'] for r in data['assessment_history']})
            self.assertEqual(data['resources']['sessions'][0]['id'], session)
            self.assertEqual(data['resources']['notes'][0]['content_markdown'], 'Texto corrigido')
        self.client.patch(self.path(1), json={'mastery':5})
        self.assertEqual(self.detail()['personal']['mastery'], 4)
        self.assertFalse(any(r['value']==5 for r in self.detail()['assessment_history']))
        self.link(0,2)
        self.assertTrue(old_marks <= {r['id'] for r in self.detail(2)['assessment_history']})
        with connection.connect() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM sessoes_estudo').fetchone()[0],1)
            self.assertEqual(conn.execute('SELECT study_subject_id FROM sessoes_estudo').fetchone()[0],study)

    def test_stage5_separate_completion_rollback_and_archive(self):
        route = self.path(0, f'/equivalences/{self.ids[1]}/decision')
        self.assertEqual(self.client.post(route, json={'decision':'separate'}).status_code,200)
        listing = self.client.get(self.path(0, '/equivalences')).json
        self.assertIn(self.ids[1], [r['id'] for r in listing['separated']])
        self.assertNotIn(self.ids[1], [r['id'] for r in listing['candidates']])
        self.client.post(route, json={'decision':'reconsider'})
        self.link()
        self.assertEqual(self.client.post(self.path(0, '/completion'),json={}).status_code,409)
        self.assertEqual(self.detail()['curriculum']['academic_status'],'not_available')
        self.assertEqual(self.client.post(self.path(0, '/completion'),json={
            'completion_targets':[self.ids[2]]}).status_code,409)
        original = core.change_curriculum_status
        def fail_target(conn,ident,*args,**kwargs):
            if ident == self.ids[1]:
                raise core.DomainError('Falha controlada no destino')
            return original(conn,ident,*args,**kwargs)
        payload = {'completion_targets':[self.ids[1]],'operation_key':'stage5-completion'}
        with patch('services.core.change_curriculum_status',side_effect=fail_target):
            self.assertEqual(self.client.post(self.path(0, '/completion'),json=payload).status_code,400)
        self.assertEqual(self.detail()['history'],[])
        for _ in range(2):
            self.assertEqual(self.client.post(self.path(0, '/completion'),json=payload).status_code,200)
        self.assertEqual(len(self.detail(1)['history']),1)
        self.assertEqual(self.detail(2)['curriculum']['academic_status'],'not_available')
        canonical = self.detail()['canonical_study_id']
        with connection.connect() as conn:
            formation = core._get(conn,'disciplinas_grade',self.ids[0])['formation_id']
            result = core.archive_formation(conn, formation)
            self.assertIn(canonical,result['preserved_shared_studies']['ids'])
            self.assertEqual(core._get(conn,'materias_estudo',canonical)['status'],'paused')
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM revisoes').fetchone()[0],0)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM sessoes_foco').fetchone()[0],0)

    def test_link_preserves_both_topics_and_academic_data(self):
        self.topic();self.topic(1)
        self.client.patch(self.path(1),json={'workload_minutes':1800,'notes':'Separadas','academic_status':'in_progress'})
        self.link(operation_key='link-1')
        self.assertEqual(len(self.detail()['contents']),2)
        self.assertEqual(len(self.detail(1)['contents']),2)
        self.assertEqual(self.detail()['curriculum']['workload_minutes'],2700)
        self.assertEqual(self.detail(1)['curriculum']['academic_status'],'in_progress')
        self.link()
        with connection.connect() as conn:
            self.assertEqual(conn.execute('select count(*) from curriculum_study_links').fetchone()[0],2)
            self.assertEqual(conn.execute('select count(*) from curriculum_study_link_audit').fetchone()[0],2)
            self.assertEqual(conn.execute('select count(*) from sessoes_planejadas').fetchone()[0],0)
            self.assertEqual(conn.execute('select status from materias_estudo').fetchone()[0],'paused')

    def test_conflicting_assessments_require_choice(self):
        self.client.patch(self.path(),json={'mastery':1})
        self.client.patch(self.path(1),json={'mastery':5})
        route=self.path(0,f'/equivalences/{self.ids[1]}')
        preview=self.client.get(route).json
        self.assertEqual(preview['conflicts'],['mastery'])
        self.assertEqual(self.client.post(route,json={'confirmed':True,'version':preview['version']}).status_code,409)
        self.assertEqual(self.detail()['linked_subjects'],[])
        self.link(assessment_choices={'mastery':self.ids[1]})
        self.assertEqual(self.detail()['personal']['mastery'],5)
        self.client.patch(self.path(1),json={'mastery':3})
        self.assertEqual(self.detail()['personal']['mastery'],3)

    def test_completion_choice_required_old_and_new_api(self):
        self.link()
        for route in (self.path(),f'/api/curriculum/{self.ids[0]}'):
            self.assertEqual(self.client.patch(route,json={'academic_status':'completed','name':'Unsaved'}).status_code,409)
        self.assertEqual(self.detail()['curriculum']['name'],'Circuitos I')
        self.assertEqual(self.detail()['history'],[])

    def test_completion_current_only_and_selected_and_replay(self):
        self.link();self.link(0,2)
        self.assertEqual(self.client.post(self.path(0,'/completion'),json={'completion_targets':[]}).status_code,200)
        self.assertEqual(self.detail(1)['curriculum']['academic_status'],'not_available')
        body={'completion_targets':[self.ids[2]],'operation_key':'completion-1'}
        for _ in range(2):
            self.assertEqual(self.client.post(self.path(0,'/completion'),json=body).status_code,200)
        self.assertEqual(self.detail(2)['curriculum']['academic_status'],'completed')
        self.assertEqual(len(self.detail(2)['history']),1)
        self.assertIn('origem',self.detail(2)['history'][0]['notes'])
        self.assertEqual(self.detail(1)['curriculum']['academic_status'],'not_available')

    def test_completion_outside_group_and_intermediate_failure_rollback(self):
        self.link()
        self.assertEqual(self.client.post(self.path(0,'/completion'),json={'completion_targets':[self.ids[2]]}).status_code,409)
        original=core.change_curriculum_status
        def fail(conn,ident,*args,**kwargs):
            if ident==self.ids[1]:
                raise core.DomainError('Falha simulada')
            return original(conn,ident,*args,**kwargs)
        with patch('services.core.change_curriculum_status',side_effect=fail):
            self.assertEqual(self.client.post(self.path(0,'/completion'),json={'completion_targets':[self.ids[1]]}).status_code,400)
        self.assertEqual(self.detail()['curriculum']['academic_status'],'not_available')
        self.assertEqual(self.detail()['history'],[])

    def test_new_import_completed_offer(self):
        self.client.post(self.path(0,'/completion'),json={})
        payload=self.payload()
        payload['formation']['name']='Curso recém-importado'
        created=self.client.post('/api/formation-import/confirm',json=payload)
        self.assertEqual(created.status_code,200,created.json)
        self.ids.append(created.json['inserted'][0]['id'])
        result=self.link(0,3)
        self.assertEqual(result['completion_offer']['source']['id'],self.ids[0])
        self.assertEqual(self.detail(3)['curriculum']['academic_status'],'not_available')
        saved=self.client.post(self.path(0,'/completion'),json={'completion_targets':[self.ids[3]]})
        self.assertEqual(saved.status_code,200,saved.json)
        self.assertEqual(self.detail(3)['curriculum']['academic_status'],'completed')

    def test_direct_page_uses_curricular_id_and_no_legacy_bootstrap(self):
        response=self.client.get(f'/curriculum/{self.ids[1]}?tab=contents')
        self.assertEqual(response.status_code,200)
        html=response.get_data(as_text=True)
        self.assertIn(f'data-curriculum-id="{self.ids[1]}"',html)
        self.assertIn('curriculum-subject.js',html)
        self.assertNotIn('js/app.js',html)
        self.assertNotIn('Iniciar sessão',html)
        self.assertEqual(self.client.get('/curriculum/999999').status_code,404)

    def test_stale_comparison_and_operation_key_conflict(self):
        route=self.path(0,f'/equivalences/{self.ids[1]}')
        preview=self.client.get(route).json
        self.topic(1)
        self.assertEqual(self.client.post(route,json={'confirmed':True,'version':preview['version']}).status_code,409)
        self.client.patch(self.path(),json={'mastery':2,'operation_key':'unique'})
        self.assertEqual(self.client.patch(self.path(),json={'mastery':3,'operation_key':'unique'}).status_code,409)
        self.assertEqual(self.detail()['personal']['mastery'],2)

    def test_neutral_link_does_not_call_old_merger_or_create_planning(self):
        with patch('services.canonical_links.link_curriculum_subject',side_effect=AssertionError('Não fundir')), patch('services.core.start_curriculum_study',side_effect=AssertionError('Não iniciar')):
            self.link()

    def test_old_effort_and_deadline_do_not_block_new_academic_flow(self):
        topic=self.topic()
        with connection.connect() as conn:
            conn.execute('UPDATE disciplinas_grade SET required_study_minutes=10,deadline_date=? WHERE id=?',('2026-09-01',self.ids[0]))
            conn.execute('UPDATE topicos SET estimated_minutes=20 WHERE id=?',(topic,))
        self.topic(name='Opcional sem esforço')
        response=self.client.patch(self.path(),json={'start_date':'2026-09-28','academic_status':'completed'})
        self.assertEqual(response.status_code,200,response.json)

    def test_link_rejects_same_formation_or_unconfirmed_or_unknown(self):
        result=self.client.post(self.path(0,f'/equivalences/{self.ids[1]}'),json={'confirmed':False})
        self.assertEqual(result.status_code,400)
        self.assertEqual(self.client.get(self.path(0,'/equivalences/99999')).status_code,404)
        with connection.connect() as conn:
            source=core._get(conn,'disciplinas_grade',self.ids[0])
            other=core.create_curriculum(conn,source['formation_id'],{'name':'Circuitos II'})['id']
        self.assertEqual(self.client.get(self.path(0,f'/equivalences/{other}')).status_code,400)

    def test_reorder_rejects_foreign_topics_and_stale_edit(self):
        own=self.topic();other=self.topic(1)
        self.assertEqual(self.client.post(self.path(0,'/contents/order'),json={'topic_ids':[own,other]}).status_code,400)
        self.assertEqual(self.client.patch(self.path(0,f'/contents/{own}'),json={'name':'Outro','expected_updated_at':'old'}).status_code,409)
        self.assertEqual(self.detail()['contents'][0]['name'],'Lei de Ohm')

    def test_unlink_preserves_origin_sessions_notes_and_legacy_zero(self):
        topic=self.topic(1)
        with connection.connect() as conn:
            study=repo.insert(conn,'materias_estudo',{'origin':'curriculum','curriculum_subject_id':self.ids[1],'status':'paused','mastery_level':0,'mastery_is_provisional':0})
            session=repo.insert(conn,'sessoes_estudo',{'study_subject_id':study,'topic_id':topic,'date':'2026-09-28','duration_seconds':600,'entry_method':'manual'})
            note=repo.insert(conn,'anotacoes_estudo',{'study_subject_id':study,'topic_id':topic,'title':'Histórico original','content_markdown':'Nota preservada'})
        self.link()
        self.assertEqual(self.detail()['personal']['mastery'],0)
        preview=self.client.get(self.path(0,'/unlink')).json
        self.assertEqual(self.client.post(self.path(0,'/unlink'),json={'confirmed':True,'version':preview['version']}).status_code,200)
        self.assertEqual(self.detail()['resources']['session_count'],1)
        self.assertTrue(self.detail()['contents'][0]['read_only'])
        self.topic(1,name='Novo depois de desvincular')
        self.assertEqual(len(self.detail()['contents']),1)
        # Um novo vínculo também compartilha as referências preservadas, sem
        # transformar a referência em uma cópia ou mudar a origem.
        self.link(0,2)
        self.assertEqual(self.detail(2)['resources']['session_count'],1)
        self.assertEqual(self.detail(2)['resources']['note_count'],1)
        self.assertEqual(len(self.detail(2)['contents']),1)
        self.assertTrue(self.detail(2)['contents'][0]['read_only'])
        self.assertEqual([r['id'] for r in self.detail(2)['linked_subjects']],[self.ids[0]])
        self.assertEqual(self.detail(1)['linked_subjects'],[])
        with connection.connect() as conn:
            self.assertEqual(conn.execute('select study_subject_id from sessoes_estudo where id=?',(session,)).fetchone()[0],study)
            self.assertEqual(conn.execute('select study_subject_id from anotacoes_estudo where id=?',(note,)).fetchone()[0],study)
            self.assertEqual(conn.execute('pragma integrity_check').fetchone()[0],'ok')
            self.assertEqual(conn.execute('pragma foreign_key_check').fetchall(),[])


if __name__=='__main__':
    unittest.main()
