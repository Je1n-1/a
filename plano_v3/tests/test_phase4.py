"""Contrato do carregamento consolidado, sobre banco temporário."""

from pathlib import Path
import tempfile
import unittest

from app import create_app
from tracker import db


class TodayOverview(unittest.TestCase):
    def test_review_subjects_are_distinct_active_and_independent_of_completion(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "review.db"
            db.initialize(path)
            client = create_app(path).test_client()
            course = client.post('/api/courses', json={'name':'Curso'}).json['id']
            hidden_course = client.post('/api/courses', json={'name':'Arquivado'}).json['id']
            ids = []
            for i, status in enumerate(['in_progress', 'completed', 'available', 'completed']):
                subject = client.post('/api/subjects', json={'course_id':hidden_course if i==3 else course, 'name':f'Disciplina {i}', 'academic_status':status}).json['id']
                ids.append(subject)
                for j in range(2):
                    topic = client.post('/api/topics', json={'subject_id':subject,'name':f'Tópico {j}'}).json
                    client.patch(f'/api/topics/{topic["id"]}', json={'version':topic['version'],'needs_review':True,'completed':True})
            client.post(f'/api/subject/{ids[2]}/archive', json={'archived':True})
            client.post(f'/api/course/{hidden_course}/archive', json={'archived':True})
            data = client.get('/api/today').json
            self.assertEqual(data['review_subject_ids'], ids[:2])
            self.assertEqual(len(data['subjects']), 2)
            self.assertNotIn('review_subject_ids', client.get('/api/today?catalog=0').json)

    def test_overview_matches_existing_contracts_and_omits_optional_catalog(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.db"
            db.initialize(path)
            client = create_app(path).test_client()
            course = client.post("/api/courses", json={"name": "Teste isolado"}).json
            client.post("/api/subjects", json={"course_id": course["id"], "name": "Matéria"})
            client.post(
                "/api/sessions/manual",
                json={
                    "operation_key": "phase4",
                    "mode": "duration",
                    "date": "2026-10-09",
                    "duration_seconds": 1800,
                    "title": "Leitura",
                },
            )
            data = client.get("/api/today").json
            for key, route in {
                "courses": "/courses",
                "subjects": "/subjects",
                "timer": "/timer",
                "recent": "/sessions/recent",
                "summary": "/sessions/summary",
            }.items():
                self.assertEqual(data[key], client.get("/api" + route).json)
            self.assertEqual(len(data["recent"]), 1)
            compact = client.get("/api/today?catalog=0").json
            self.assertEqual(set(compact), {"timer", "recent", "summary"})
            self.assertEqual(compact, {key: data[key] for key in compact})
