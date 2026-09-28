"""Contrato da etapa 1: importação atômica e situação acadêmica independente."""
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from flask import Flask
from database import connection
from database.migrations import migrate
from routes.api import api
from routes.formation_import import formation_import
from routes.pages import pages


class FormationsRedesignTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.previous = connection.DATABASE_PATH
        connection.DATABASE_PATH = Path(self.tmp.name) / 'test.db'
        migrate()
        root = Path(__file__).resolve().parents[1]
        app = Flask(__name__, template_folder=str(root/'templates'), static_folder=str(root/'static'))
        app.register_blueprint(api)
        app.register_blueprint(formation_import)
        app.register_blueprint(pages)
        app.config['TESTING'] = True
        self.client = app.test_client()

    def tearDown(self):
        connection.DATABASE_PATH = self.previous
        self.tmp.cleanup()

    def payload(self):
        return {'confirmed': True, 'formation': {'name':'Engenharia Teste'}, 'items':[
            {'name':'Circuitos I','period':'Módulo 1','workload_hours':25,'academic_status':'not_available','include':True},
            {'name':'Cálculo I','period':'Módulo 1','workload_hours':15,'academic_status':'not_available','include':True}]}

    def test_shell_has_no_global_pdf_account_or_planning(self):
        for url in ['/', '/formations']:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            html = response.get_data(as_text=True)
            self.assertIn('formations.js', html)
            self.assertNotIn('js/app.js', html)
            self.assertNotIn('href="/planning"', html)
            header = html.split('<header class="topbar">')[1].split('</header>')[0]
            self.assertNotIn('PDF', header)
            self.assertNotIn('avatar', html)

    def test_preview_does_not_create_formation(self):
        response = self.client.post('/api/formation-import/preview', data={'file':(io.BytesIO(b'Disciplina;Carga horaria\nCircuitos;25'), 'grade.csv')})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json['items']), 1)
        self.assertEqual(self.client.get('/api/formations').json, [])

    def test_atomic_import_and_confirmation_repeat(self):
        response = self.client.post('/api/formation-import/confirm', json=self.payload())
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(response.json['summary']['inserted'], 2)
        repeated = self.client.post('/api/formation-import/confirm', json=self.payload())
        self.assertEqual(repeated.status_code, 409)
        self.assertEqual(len(self.client.get('/api/formations').json), 1)
        with connection.connect() as conn:
            self.assertEqual(conn.execute('select count(*) from disciplinas_grade').fetchone()[0], 2)
            self.assertEqual(conn.execute('pragma integrity_check').fetchone()[0], 'ok')
            self.assertEqual(conn.execute('pragma foreign_key_check').fetchall(), [])

    def test_invalid_row_rolls_back_formation_and_subjects(self):
        payload = self.payload()
        payload['items'][1]['name'] = ''
        response = self.client.post('/api/formation-import/confirm', json=payload)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.get('/api/formations').json, [])

    def test_confirmation_and_selected_rows_required(self):
        for extra in [{'confirmed':False}, {'items':[]}, {'items':[{'name':'Não incluir','include':False}]}]:
            response=self.client.post('/api/formation-import/confirm',json={**self.payload(),**extra})
            self.assertEqual(response.status_code,400,response.json)
        self.assertEqual(self.client.get('/api/formations').json, [])

    def test_academic_status_progress_and_edit_without_planner(self):
        created=self.client.post('/api/formation-import/confirm',json=self.payload()).json
        ident=created['formation']['id']
        subjects=created['inserted']
        with patch('services.core.start_curriculum_study', side_effect=AssertionError('Não iniciar planejamento')):
            started=self.client.post(f"/api/curriculum/{subjects[0]['id']}/status",json={'academic_status':'in_progress'})
            self.assertEqual(started.status_code,200)
            for subject in subjects:
                result=self.client.post(f"/api/curriculum/{subject['id']}/status",json={'academic_status':'completed'})
                self.assertEqual(result.status_code,200)
        saved=self.client.patch(f"/api/curriculum/{subjects[0]['id']}",json={'start_date':'2026-09-01','end_date':'2026-10-15','workload_minutes':1800})
        self.assertEqual(saved.status_code,200)
        reloaded=self.client.get(f'/api/formations/{ident}/curriculum/management').json
        self.assertEqual(reloaded['summary']['academic_progress_percent'],100)
        self.assertEqual(reloaded['summary']['by_period'][0]['academic_progress_percent'],100)
        with connection.connect() as conn:
            self.assertEqual(conn.execute('select count(*) from materias_estudo').fetchone()[0],0)
            self.assertEqual(conn.execute('select count(*) from sessoes_planejadas').fetchone()[0],0)
            self.assertEqual(conn.execute('select count(*) from curriculum_status_history').fetchone()[0],3)

    def test_reimport_skips_duplicates_and_preserves_completion(self):
        created=self.client.post('/api/formation-import/confirm',json=self.payload()).json
        ident=created['formation']['id']; subject=created['inserted'][0]
        self.client.post(f"/api/curriculum/{subject['id']}/status",json={'academic_status':'completed'})
        response=self.client.post(f'/api/formations/{ident}/curriculum/import',json=self.payload())
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json['summary']['inserted'],0)
        self.assertEqual(response.json['summary']['skipped'],2)
        rows=self.client.get(f'/api/formations/{ident}/curriculum').json
        self.assertEqual(next(x for x in rows if x['id']==subject['id'])['academic_status'],'completed')


if __name__ == '__main__':
    unittest.main()
