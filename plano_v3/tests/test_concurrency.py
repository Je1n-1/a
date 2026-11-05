from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app import create_app
from tracker import db
from upgrade import upgrade


class Concurrency(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name)/'test.db'
        db.initialize(self.path)
        self.app = create_app(self.path)
        self.client = self.app.test_client()
        self.course = self.post('/courses', {'name':'Curso'})
        self.subject = self.post('/subjects', {'course_id':self.course['id'], 'name':'Circuitos'})

    def post(self, route, data, status=200, method='post'):
        response = getattr(self.client, method)('/api'+route, json=data)
        self.assertEqual(response.status_code, status, response.json)
        return response.json

    def manual(self, **values):
        return {'operation_key':'manual-1', 'mode':'duration', 'date':'2026-10-15', 'duration_seconds':60, **values}

    def test_catalog_requires_integer_current_version(self):
        for route in (f'/courses/{self.course["id"]}', f'/subjects/{self.subject["id"]}'):
            for version in (None, True, '1', 0):
                self.post(route, {'version':version,'name':'Changed'}, 409, 'patch')
            result=self.post(route, {'version':1,'name':'Changed'}, method='patch')
            self.assertEqual(result['version'], 2)
            self.post(route, {'version':1,'name':'Lost update'},409,'patch')

    def test_parallel_writers_only_one_succeeds(self):
        route=f'/api/subjects/{self.subject["id"]}'
        def write(name):
            return self.app.test_client().patch(route,json={'version':1,'name':name}).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(write,['A','B'])), [200,409])
        self.assertEqual(self.client.get('/api/subjects').json[0]['version'],2)

    def test_archive_and_restore_invalidate_stale_edits(self):
        for kind, row in (('course',self.course),('subject',self.subject)):
            route=f'/{kind}/{row["id"]}/archive'
            self.post(route,{'archived':True},409)
            self.post(route,{'version':1,'archived':True})
            self.post(route,{'version':1,'archived':False},409)
            restored=self.post(route,{'version':2,'archived':False})
            self.assertEqual(restored['version'],3)
            self.post(f'/{kind}s/{row["id"]}',{'version':1,'name':'Old'},409,'patch')

    def preview_row(self):
        row=self.post(f'/courses/{self.course["id"]}/import/preview',{'text':'Disciplina\tCarga horária\nCircuitos\t60'})['items'][0]
        row.update(duplicate_action='update',expected_id=row['duplicate']['existing_id'],version=row['duplicate']['version'])
        return row

    def test_import_update_and_batch_conflict_are_atomic(self):
        row=self.preview_row()
        route=f'/courses/{self.course["id"]}/import/confirm'
        self.post(f'/subjects/{self.subject["id"]}',{'version':1,'notes':'Another tab'},method='patch')
        self.post(route,{'confirmed':True,'items':[{'name':'Must roll back'},row]},409)
        self.assertEqual(len(self.client.get('/api/subjects').json),1)
        fresh=self.preview_row()
        self.assertEqual(self.post(route,{'confirmed':True,'items':[fresh]})['updated'],1)
        self.assertEqual(self.client.get('/api/subjects').json[0]['version'],3)

    def test_import_cannot_retarget_a_renamed_subject(self):
        row=self.preview_row()
        self.post(f'/subjects/{self.subject["id"]}',{'version':1,'name':'Renamed'},method='patch')
        self.post(f'/courses/{self.course["id"]}/import/confirm',{'confirmed':True,'items':[row]},409)
        self.assertEqual(len(self.client.get('/api/subjects').json),1)

    def test_manual_same_key_same_payload_and_changed_payload(self):
        payload=self.manual()
        saved=self.post('/sessions/manual',payload)
        self.assertEqual(self.post('/sessions/manual',dict(reversed(list(payload.items())))),saved)
        for changes in ({'duration_seconds':3600},{'note':'different'},{'subject_id':self.subject['id']},{'date':'2026-10-14'}):
            self.post('/sessions/manual',{**payload,**changes},409)
        self.assertEqual(len(self.client.get('/api/sessions/recent').json),1)

    def test_correct_replay_checks_content_and_preserves_later_corrections(self):
        saved=self.post('/sessions/manual',self.manual())
        route=f'/sessions/{saved["id"]}'
        values={'version':1,'operation_key':'correct-1','reason':'Fix note','note':'First'}
        corrected=self.post(route,values,method='patch')
        self.assertEqual(self.post(route,values,method='patch'),corrected)
        self.post(route,{**values,'note':'Other'},409,'patch')
        latest=self.post(route,{'version':2,'operation_key':'correct-2','reason':'More detail','note':'Second'},method='patch')
        self.assertEqual(self.post(route,values,method='patch'),latest)
        self.assertEqual(len(self.client.get('/api'+route+'/corrections').json),2)
        self.assertEqual(self.post('/sessions/manual',self.manual()),latest)

    def test_replay_after_project_rename_and_archive(self):
        project=self.post('/projects',{'name':'Projeto'})
        step=self.post(f'/projects/{project["id"]}/steps',{'name':'Etapa'})
        payload=self.manual(project_id=project['id'],step_id=step['id'])
        saved=self.post('/sessions/manual',payload)
        self.post(f'/projects/{project["id"]}',{'version':1,'name':'Renamed','archived':True},method='patch')
        self.assertEqual(self.post('/sessions/manual',payload),saved)
        self.post('/sessions/manual',{**payload,'duration_seconds':100},409)

    def test_legacy_signature_is_not_invented(self):
        saved=self.post('/sessions/manual',self.manual())
        with db.transaction(self.path) as conn:
            conn.execute('UPDATE study_sessions SET request_signature=NULL WHERE id=?',(saved['id'],))
        self.post('/sessions/manual',self.manual(),409)
        self.assertEqual(self.client.get('/api/sessions/recent').json[0]['effective_seconds'],60)

    def test_concurrent_identical_manual_retries_create_one_record(self):
        def submit(_):
            return self.app.test_client().post('/api/sessions/manual',json=self.manual())
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses=list(pool.map(submit,range(2)))
        self.assertEqual([r.status_code for r in responses],[200,200])
        self.assertEqual(responses[0].json,responses[1].json)
        self.assertEqual(len(self.client.get('/api/sessions/recent').json),1)

    def test_correction_after_project_rename_preserves_historical_names(self):
        project=self.post('/projects',{'name':'Original'})
        step=self.post(f'/projects/{project["id"]}/steps',{'name':'Etapa original'})
        saved=self.post('/sessions/manual',self.manual(project_id=project['id'],step_id=step['id']))
        self.post(f'/projects/{project["id"]}/steps/{step["id"]}',{'version':1,'name':'Etapa nova'},method='patch')
        self.post(f'/projects/{project["id"]}',{'version':1,'name':'Novo','archived':True},method='patch')
        corrected=self.post(f'/sessions/{saved["id"]}',{'version':1,'operation_key':'edit-archived','reason':'Nota','note':'Registro conferido'},method='patch')
        self.assertEqual((corrected['project_name'],corrected['step_name']),('Original','Etapa original'))

    def test_legacy_correction_key_conflicts_without_modifying_history(self):
        saved=self.post('/sessions/manual',self.manual())
        route=f'/sessions/{saved["id"]}'
        payload={'version':1,'operation_key':'old-correction','reason':'Nota','note':'Nota original'}
        corrected=self.post(route,payload,method='patch')
        with db.transaction(self.path) as conn:
            conn.execute('UPDATE session_corrections SET request_signature=NULL')
        self.post(route,payload,409,'patch')
        self.assertEqual(self.client.get('/api'+route).json,corrected)

    def test_migration_from_seven_preserves_existing_values(self):
        legacy=Path(self.folder.name)/'legacy.db'
        with patch('tracker.db.versions',return_value=db.versions()[:7]):
            db.initialize(legacy)
        with db.transaction(legacy) as conn:
            conn.execute("INSERT INTO courses(name,created_at) VALUES ('Existing','2026-10-15')")
        result=upgrade(legacy,Path(self.folder.name)/'backups')
        self.assertEqual(result['applied'],['0008_catalog_concurrency', '0009_objectives'])
        self.assertTrue(result['existing_rows_preserved'])
        with db.read_transaction(legacy) as conn:
            row=conn.execute('SELECT name,version FROM courses').fetchone()
            self.assertEqual(tuple(row),('Existing',1))
