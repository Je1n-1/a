"""Conferência básica da Etapa 3 em banco temporário."""
import unittest
from tests.test_formations_redesign import FormationsRedesignTest
from routes.curriculum_workspace import curriculum_workspace
from database import connection
from database.repositories import core as repo


class DisciplineCatalogTest(unittest.TestCase):
    setUp = FormationsRedesignTest.setUp
    tearDown = FormationsRedesignTest.tearDown
    payload = FormationsRedesignTest.payload

    def test_shared_catalog_filters_and_explicit_id_navigation(self):
        self.client.application.register_blueprint(curriculum_workspace)
        a=self.client.post('/api/formation-import/confirm',json=self.payload()).json
        payload=self.payload();payload['formation']['name']='Computação'
        b=self.client.post('/api/formation-import/confirm',json=payload).json
        left,right=a['inserted'][0]['id'],b['inserted'][0]['id']
        base='/api/curriculum-workspace'
        self.client.patch(f'{base}/{right}',json={'academic_status':'completed'})
        preview=self.client.get(f'{base}/{left}/equivalences/{right}').json
        linked=self.client.post(f'{base}/{left}/equivalences/{right}',json={'confirmed':True,'version':preview['version']})
        self.assertEqual(linked.status_code,200,linked.json)
        response=self.client.get(base+'/catalog')
        self.assertEqual(response.status_code,200,response.json)
        self.assertEqual(len(response.json['items']),3)
        shared=next(r for r in response.json['items'] if r['shared'])
        self.assertEqual(len(shared['contexts']),2)
        self.assertEqual({c['academic_status'] for c in shared['contexts']},{'not_available','completed'})
        matched=self.client.get(base+'/catalog',query_string={'q':'circuitos','formation_id':b['formation']['id'],'status':'completed'}).json['items']
        self.assertEqual(len(matched),1)
        self.assertEqual(matched[0]['curriculum_id'],right)
        self.assertEqual(self.client.get(base+'/catalog',query_string={'formation_id':a['formation']['id'],'status':'completed'}).json['items'],[])
        with connection.connect() as conn:
            # ID de estudo intencionalmente diferente do ID curricular.
            study_id=repo.insert(conn,'materias_estudo',{'id':987,'origin':'curriculum','curriculum_subject_id':right,'status':'archived'})
            self.assertEqual(conn.execute('PRAGMA integrity_check').fetchone()[0],'ok')
            self.assertEqual(conn.execute('PRAGMA foreign_key_check').fetchall(),[])
        old=self.client.get(f'/subjects/{study_id}/contents')
        self.assertEqual(old.status_code,302)
        self.assertIn(f'/curriculum/{right}?tab=contents',old.location)
        self.assertEqual(self.client.get('/subjects').status_code,200)
        self.assertEqual(self.client.get('/disciplines?q=circuitos').location,'/subjects?q=circuitos')


if __name__=='__main__':
    unittest.main()
