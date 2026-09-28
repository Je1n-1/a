"""Etapa 6: dois percursos integrados, relógio fixo e banco descartável."""
import unittest
from datetime import datetime
from unittest.mock import patch
from config import LOCAL_TIMEZONE
from tests import test_formations_redesign as base
from database import connection
from database.repositories import core as repo
from routes.manual_study import manual_study
from routes.curriculum_workspace import curriculum_workspace


class ManualStudyTest(unittest.TestCase):
    payload=base.FormationsRedesignTest.payload

    def setUp(self):
        base.FormationsRedesignTest.setUp(self)
        self.client.application.register_blueprint(manual_study)
        self.client.application.register_blueprint(curriculum_workspace)
        self.clock=datetime(2026,9,28,14,tzinfo=LOCAL_TIMEZONE)
        self.now=patch('services.manual_study.now',side_effect=lambda:self.clock)
        self.now.start()
        self.sequence=0
        for name in ('generate_plan','create_session','start_curriculum_study'):
            guard=patch('services.core.'+name,side_effect=AssertionError('Não chamar o motor antigo: '+name))
            guard.start();self.addCleanup(guard.stop)
        imported=self.client.post('/api/formation-import/confirm',json=self.payload()).json
        self.cid=imported['inserted'][0]['id']
        self.other=imported['inserted'][1]['id']
        self.client.patch(f'/api/curriculum-workspace/{self.cid}',json={'academic_status':'completed'})

    def tearDown(self):
        self.now.stop()
        with connection.connect() as conn:
            self.assertEqual(conn.execute('PRAGMA integrity_check').fetchone()[0],'ok')
            self.assertEqual(conn.execute('PRAGMA foreign_key_check').fetchall(),[])
            for table in ('sessoes_planejadas','revisoes','study_plan_baselines'):
                self.assertEqual(conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0],0)
        base.FormationsRedesignTest.tearDown(self)

    def at(self,hour,minute=0,day=28):
        self.clock=datetime(2026,9,day,hour,minute,tzinfo=LOCAL_TIMEZONE)

    def send(self,path,values=None,expected=200,key=None,method='post'):
        self.sequence+=1
        result=getattr(self.client,method)('/api/manual-study'+path,json={
            'operation_key':key or f'op-{self.sequence}',**(values or {})})
        self.assertEqual(result.status_code,expected,result.json)
        return result.json

    def get(self,path):
        result=self.client.get('/api/manual-study'+path)
        self.assertEqual(result.status_code,200,result.json)
        return result.json

    def test_timer_pause_note_finish_reload_midnight_without_planner(self):
        for page in ('/today','/focus'):
            html=self.client.get(page).get_data(as_text=True)
            self.assertIn('manual-study.js',html)
            self.assertNotIn('js/app.js',html)
        f=self.send('/focus',{'curriculum_id':self.cid,'target_seconds':7200},key='start')
        self.assertEqual(f['purpose'],'review')
        self.assertIsNone(f['topic_id'])
        self.assertEqual(self.send('/focus',{'curriculum_id':self.cid,'target_seconds':7200},key='start')['id'],f['id'])
        self.send('/focus',{'curriculum_id':self.other},expected=409)
        base=f'/focus/{f["id"]}'
        self.at(14,30)
        f=self.send(base+'/pause',{'version':f['version'],'reason':'rest'})
        self.send(base+'/pause',{'version':1})  # Duplo clique sem nova pausa.
        self.at(15)
        f=self.send(base+'/resume',{'version':f['version']})
        self.send(base+'/resume',{'version':1})
        self.send(base+'/note',{'revision':0,'text':'Anotação persistente'},method='put')
        self.at(15,15)
        fresh=self.client.application.test_client().get('/api/manual-study/focus/active').json
        self.assertEqual(fresh['elapsed_seconds'],2700)  # 45 min: 270 graus em 60 min.
        self.assertEqual(fresh['note']['content_markdown'],'Anotação persistente')
        self.at(16)
        closed=self.send(base+'/finish',{'version':fresh['version']},key='finish')
        self.assertEqual(closed['result']['duration_seconds'],5400)
        self.assertEqual(closed['result']['pause_seconds'],1800)
        self.assertEqual(len(closed['result']['intervals']),3)
        self.assertEqual(len(closed['breaks']),1)
        self.assertEqual(self.send(base+'/finish',{'version':1})['result']['id'],closed['result']['id'])
        self.assertIsNone(self.get('/focus/active'))
        self.assertEqual(self.client.post(f'/api/focus/sessions/{f["id"]}/finish',json={}).status_code,409)
        self.assertEqual(self.client.get(f'/api/curriculum-workspace/{self.cid}').json['curriculum']['academic_status'],'completed')
        # Encerrar durante pausa fecha o intervalo e não conta pausa como estudo.
        second=self.send('/focus',{'curriculum_id':self.other})
        self.at(16,10)
        second=self.send(f'/focus/{second["id"]}/pause')
        self.at(16,20)
        second=self.send(f'/focus/{second["id"]}/finish')
        self.assertEqual(second['result']['duration_seconds'],600)
        self.assertEqual(second['result']['pause_seconds'],600)
        self.assertIsNotNone(second['breaks'][0]['ended_at'])
        self.at(23,50)
        third=self.send('/focus',{'curriculum_id':self.cid})
        self.at(0,10,29)
        self.send(f'/focus/{third["id"]}/finish')
        self.assertEqual(self.get('/today')['total_seconds'],600)
        with connection.connect() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM sessoes_estudo').fetchone()[0],3)

    def test_retroactive_conflicts_long_session_review_and_optional_result(self):
        manual={'curriculum_id':self.cid,'date':'2026-09-27','duration_seconds':3600,
            'pauses':[{'duration_seconds':900,'reason':'rest'}]}
        result=self.send('/sessions',manual,key='retro')
        self.assertIsNone(result['started_at']);self.assertIsNone(result['ended_at'])
        self.assertEqual(result['pause_seconds'],900)
        self.assertEqual(result['duration_seconds'],3600)
        self.assertEqual(result['entry_method'],'manual')
        self.assertEqual(self.send('/sessions',manual,key='retro')['id'],result['id'])
        self.send('/sessions',{**manual,'date':'2026-09-29'},expected=400)
        self.send('/sessions',{**manual,'duration_seconds':86400},expected=400)
        topic=self.client.post(f'/api/curriculum-workspace/{self.other}/contents',json={'name':'Tópico alheio'}).json['topic']['id']
        self.send('/focus',{'curriculum_id':self.cid,'topic_id':topic},expected=400)
        self.at(0,0,29)
        f=self.send('/focus',{'curriculum_id':self.cid})
        base=f'/focus/{f["id"]}'
        self.send(base+'/note',{'revision':0,'text':'Primeira versão'},method='put')
        self.send(base+'/note',{'revision':0,'text':'Outra aba'},method='put',expected=409)
        self.assertEqual(self.get(base)['note']['content_markdown'],'Primeira versão')
        self.at(9,0,29)
        self.assertTrue(self.get(base)['review_required'])
        self.send(base+'/finish',expected=409)
        closed=self.send(base+'/finish',{'review_confirmed':True,'reviewed_end_at':'2026-09-29T08:00:00-03:00'})
        self.assertEqual(closed['result']['duration_seconds'],8*3600)
        self.assertEqual(closed['elapsed_seconds'],9*3600)  # Evento bruto preservado.
        self.send(base+'/note',{'revision':1,'text':'Complemento após encerrar'},method='put')
        outcome=self.send(f'/sessions/{closed["result"]["id"]}/feedback',{'version':1,'notes':'Resultado opcional','mastery':3})
        self.assertEqual(outcome['duration_seconds'],8*3600)
        self.assertEqual(self.client.get(f'/api/curriculum-workspace/{self.cid}').json['personal']['mastery'],3)
        with connection.connect() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM study_session_corrections').fetchone()[0],1)


if __name__=='__main__':
    unittest.main()
