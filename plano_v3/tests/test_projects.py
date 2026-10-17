from pathlib import Path
import csv
import io
import tempfile
import unittest
from unittest.mock import patch
from app import create_app
from tracker import db, storage
from upgrade import upgrade


class ProjectFlows(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.path=self.root/'data.db'
        db.initialize(self.path)
        self.client=create_app(self.path).test_client()
        self.course=self.post('/courses',{'name':'Eletrotécnica'})['id']
        self.subject=self.post('/subjects',{'name':'Projetos prediais','course_id':self.course})['id']
        self.project=self.post('/projects',{'name':'Site do curso','objective':'Construir um site','course_id':self.course})
        self.step=self.post(f'/projects/{self.project["id"]}/steps',{'name':'Tela inicial'})

    def post(self, route, values, status=200):
        r=self.client.post('/api'+route,json=values)
        self.assertEqual(r.status_code,status,r.json)
        return r.json

    def edit(self, route, values, status=200):
        r=self.client.patch('/api'+route,json=values)
        self.assertEqual(r.status_code,status,r.json)
        return r.json

    def at(self, stamp, route, values, status=200):
        with patch('tracker.timer.now',return_value='2026-10-15T'+stamp+'+00:00'):
            return self.post(route,values,status)

    def manual(self, token, **values):
        return self.post('/sessions/manual',{'mode':'duration','date':'2026-10-15','duration_seconds':180,'operation_key':token,**values})

    def test_timer_notes_rest_restart_and_snapshots(self):
        t=self.at('12:00:00','/timer',{'project_id':self.project['id'],'step_id':self.step['id'],'operation_key':'start'})
        self.assertEqual((t['title'],t['step_name'],t['course_name']),('Site do curso','Tela inicial','Eletrotécnica'))
        self.at('12:00:01','/timer',{'subject_id':self.subject,'operation_key':'second'},409)
        self.at('12:00:01','/timer',{'project_id':self.project['id'],'operation_key':'start'},409)
        self.edit(f'/projects/{self.project["id"]}',{'version':1,'name':'Novo nome','course_id':None})
        self.edit(f'/projects/{self.project["id"]}/steps/{self.step["id"]}',{'version':1,'name':'Nome novo'})
        for stamp,action,extra in [('12:02:00','pause',{}),('12:03:00','break-plan',{'minutes':1}),('12:06:00','resume',{}),('12:07:00','finish',{'note':'Montei o formulário'})]:
            t=self.at(stamp,f'/timer/{t["id"]}/{action}',{'version':t['version'],**extra})
        s=create_app(self.path).test_client().get(f'/api/sessions/{t["session_id"]}').json
        self.assertEqual((s['effective_seconds'],s['break_seconds'],s['rest_seconds']),(180,60,180))
        self.assertEqual((s['project_name'],s['step_name'],s['project_course_id']),('Site do curso','Tela inicial',self.course))
        self.assertEqual(s['note'],'Montei o formulário')
        again=self.at('12:08:00',f'/timer/{t["id"]}/finish',{'version':t['version']})
        self.assertEqual(again['session_id'],s['id'])
        p=self.client.get(f'/api/projects/{self.project["id"]}').json
        self.assertEqual((p['session_count'],p['effective_seconds'],p['steps'][0]['effective_seconds']),(1,180,180))
        self.manual('after-rename',project_id=self.project['id'],step_id=self.step['id'])
        report=self.client.get('/api/analytics?start=2026-10-15&end=2026-10-15').json
        self.assertEqual(len(report['by_activity']),1)
        self.assertEqual(report['by_activity'][0]['effective_seconds'],360)
        self.assertEqual(len(report['by_step']),1)
        self.assertEqual(report['by_step'][0]['name'],'Nome novo')
        self.assertEqual(len(report['by_course']),2)
        db.diagnostics(self.path)

    def test_analysis_filters_groups_and_csv_never_double_count(self):
        self.manual('project',project_id=self.project['id'],step_id=self.step['id'],note='Construí a tela')
        self.manual('study',subject_id=self.subject)
        independent=self.post('/projects',{'name':'Pessoal'})
        self.manual('personal',project_id=independent['id'])
        self.manual('free',title='Leitura avulsa')
        def report(query=''):
            return self.client.get('/api/analytics?start=2026-10-15&end=2026-10-15'+query).json
        all_data=report()
        self.assertEqual(all_data['summary']['period']['effective_seconds'],720)
        for group in ['by_activity','by_course']:
            self.assertEqual(sum(r['effective_seconds'] for r in all_data[group]),720)
        self.assertEqual(report('&activity=project')['summary']['period']['effective_seconds'],360)
        self.assertEqual(report('&activity=study')['summary']['period']['effective_seconds'],360)
        self.assertEqual(report('&subject_id=free')['summary']['period']['effective_seconds'],180)
        linked=report(f'&course_id={self.course}')
        self.assertEqual((linked['summary']['period']['sessions'],linked['summary']['period']['effective_seconds']),(2,360))
        self.assertEqual(report(f'&activity=project&step_id={self.step["id"]}')['summary']['period']['effective_seconds'],180)
        exported=self.client.get(f'/api/analytics/export.csv?start=2026-10-15&end=2026-10-15&activity=project&course_id={self.course}').text
        rows=list(csv.DictReader(io.StringIO(exported.lstrip('\ufeff')),delimiter=';'))
        self.assertEqual(len(rows),1)
        self.assertEqual((rows[0]['Atividade'],rows[0]['Projeto'],rows[0]['Etapa']),('Projeto','Site do curso','Tela inicial'))
        self.assertEqual(rows[0]['Líquido no período (s)'],'180')

    def test_step_completion_and_project_status_are_independent_and_versioned(self):
        self.edit(f'/projects/{self.project["id"]}/steps/{self.step["id"]}',{'version':1,'completed':True})
        self.edit(f'/projects/{self.project["id"]}/steps/{self.step["id"]}',{'version':1,'completed':False},409)
        p=self.client.get(f'/api/projects/{self.project["id"]}').json
        self.assertEqual((p['completed_steps'],p['status']),(1,'not_started'))
        self.edit(f'/projects/{p["id"]}',{'version':1,'status':'completed'})
        self.edit(f'/projects/{p["id"]}',{'version':1,'name':'Stale'},409)
        self.edit(f'/projects/{p["id"]}',{'version':2,'status':'invalid'},400)

    def test_invalid_links_are_atomic_and_archiving_keeps_history(self):
        other=self.post('/projects',{'name':'Outro'})
        for extra in [{'subject_id':self.subject},{'new_topic_name':'errado'},{'session_kind':'review'},{'project_id':True},{'project_id':other['id'],'step_id':self.step['id']},{'project_id':None,'step_id':self.step['id']}]:
            self.post('/timer',{'operation_key':'invalid','project_id':self.project['id'],**extra},400)
            self.assertIsNone(self.client.get('/api/timer').json)
        session=self.manual('valid',project_id=self.project['id'])
        self.edit(f'/projects/{self.project["id"]}',{'version':1,'archived':True})
        self.post('/timer',{'operation_key':'archived','project_id':self.project['id']},409)
        self.assertEqual(self.client.get(f'/api/sessions/{session["id"]}').json,session)
        self.assertNotIn(self.project['id'],[p['id'] for p in self.client.get('/api/projects').json])
        self.assertIn(self.project['id'],[p['id'] for p in self.client.get('/api/projects?archived=1').json])

    def test_correction_preserves_project_updates_stage_and_audits_time(self):
        s=self.manual('manual',project_id=self.project['id'],step_id=self.step['id'])
        stage=self.post(f'/projects/{self.project["id"]}/steps',{'name':'Testes'})
        c=self.edit(f'/sessions/{s["id"]}',{'version':1,'operation_key':'correct','reason':'Etapa correta','step_id':stage['id'],'mode':'duration','date':'2026-10-15','duration_seconds':300})
        self.assertEqual((c['project_id'],c['step_id'],c['effective_seconds']),(self.project['id'],stage['id'],300))
        audit=self.client.get(f'/api/sessions/{s["id"]}/corrections').json[0]
        self.assertEqual(audit['old_values']['step_name'],'Tela inicial')
        self.assertEqual(audit['new_values']['step_name'],'Testes')
        self.edit(f'/sessions/{s["id"]}',{'version':2,'operation_key':'bad','reason':'Conflito','subject_id':self.subject},400)
        self.assertEqual(self.client.get(f'/api/sessions/{s["id"]}').json,c)

    def test_migration_and_backup_preserve_existing_rows(self):
        old=self.root/'old.db'
        with patch('tracker.db.versions',return_value=db.versions()[:6]):
            db.initialize(old)
        with db.transaction(old) as conn:
            conn.execute("INSERT INTO courses(name,created_at) VALUES ('Original','2026-10-15')")
        result=upgrade(old,self.root/'backups')
        self.assertEqual(result['applied'],['0007_projects'])
        self.assertTrue(result['existing_rows_preserved'])
        self.manual('backup',project_id=self.project['id'],step_id=self.step['id'])
        target=self.root/'backup.db'
        storage.create_backup(self.path,target)
        restored=create_app(target).test_client().get(f'/api/projects/{self.project["id"]}').json
        self.assertEqual(restored,self.client.get(f'/api/projects/{self.project["id"]}').json)
