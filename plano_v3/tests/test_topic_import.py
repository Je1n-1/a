"""Prévia sem escrita, confirmação atômica e preservação do conteúdo estudado."""
from pathlib import Path
import tempfile
import unittest
from app import create_app
from tracker import db


class TopicImport(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'study.db'
        db.initialize(self.path)
        self.client = create_app(self.path).test_client()
        course = self.post('/courses', {'name':'Eletrotécnica'})['id']
        self.subject = self.post('/subjects', {'name':'Projetos Elétricos Prediais','course_id':course})['id']
        self.prefix = f'/subjects/{self.subject}/topics/'

    def post(self, route, values, status=200):
        response = self.client.post('/api'+route, json=values)
        self.assertEqual(response.status_code, status, response.json)
        return response.json

    def test_real_concatenated_example_preserves_original_history_and_incomplete_text(self):
        text = 'Dados e informações técnicas para projetos de instalações elétricas 6 Padrões das concessionárias de energia elétrica utilizados nos projetos elétricos 15 Documentos e ferramentas usadas na gestão de'
        topic = self.post('/topics', {'subject_id':self.subject,'name':text})
        session = self.post('/sessions/manual', {'operation_key':'original','subject_id':self.subject,'topic_id':topic['id'],'mode':'duration','date':'2026-10-13','duration_seconds':8059})
        before = self.client.get('/api/topics').json
        preview = self.post(self.prefix+'preview', {'mode':'pages','text':text})
        self.assertEqual(len(preview['rows']), 3)
        self.assertEqual(preview['rows'][2]['name'], 'Documentos e ferramentas usadas na gestão de')
        self.assertEqual(self.client.get('/api/topics').json, before)
        names = [r['name'] for r in preview['rows']]
        result = self.post(self.prefix+'confirm', {'names':names})
        self.assertEqual(result['created'], 3)
        self.assertEqual(self.post(self.prefix+'confirm', {'names':names})['created'], 0)
        self.assertEqual(self.client.get(f'/api/sessions/{session["id"]}').json, session)
        self.assertEqual(self.client.get('/api/topics').json[0], before[0])

    def test_explicit_modes_do_not_remove_content_numbers_by_default(self):
        p = self.post(self.prefix+'preview', {'text':'• Circuitos 220 V\n2. Norma NBR 5410\n3) Proteção; Aterramento'})
        self.assertEqual([r['name'] for r in p['rows']], ['Circuitos 220 V','Norma NBR 5410','Proteção; Aterramento'])
        p = self.post(self.prefix+'preview', {'text':'Circuitos;Proteção','mode':'semicolon'})
        self.assertEqual(len(p['rows']), 2)
        p = self.post(self.prefix+'preview', {'text':'Instalações .... 6\nProjetos 15','mode':'pages'})
        self.assertEqual([r['name'] for r in p['rows']], ['Instalações','Projetos'])

    def test_atomic_validation_deduplication_and_archive(self):
        for names in [[], ['Válido', ''], ['Válido', 'a'*201], ['Válido', 4], ['Válido', '!!!'], ['x']*301]:
            self.post(self.prefix+'confirm', {'names':names},400)
            self.assertEqual(self.client.get('/api/topics').json, [])
        self.post(self.prefix+'confirm', {'names':['Proteção','Protecao','Circuitos']})
        self.assertEqual(len(self.client.get('/api/topics').json), 2)
        p = self.post(self.prefix+'preview', {'text':'Proteção\nNovo\nnovo'})
        self.assertEqual([r['duplicate'] for r in p['rows']], [True,False,True])
        self.post(f'/subject/{self.subject}/archive', {'archived':True})
        self.post(self.prefix+'confirm', {'names':['Outro']},409)

    def test_preview_keeps_long_text_for_manual_editing(self):
        text = 'a'*250
        self.assertEqual(self.post(self.prefix+'preview', {'text':text})['rows'][0]['name'], text)
        for values in [{'text':''}, {'text':'a'*50001}, {'text':'a','mode':'unknown'}, {'text':'\n'.join(['a']*301)}]:
            self.post(self.prefix+'preview', values,400)
