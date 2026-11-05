from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from app import create_app
from tracker import db, storage
from upgrade import contents, verify_preserved


class ObjectiveFlows(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'test.db'
        db.initialize(self.path)
        self.app = create_app(self.path)
        self.client = self.app.test_client()
        self.course = self.post('/courses', {'name': 'Curso'})['id']
        self.subject = self.post('/subjects', {'course_id': self.course, 'name': 'Circuitos', 'academic_status': 'completed'})['id']
        self.topic = self.post('/topics', {'subject_id': self.subject, 'name': 'Sensores'})['id']
        self.project = self.post('/projects', {'name': 'Protótipo'})['id']
        self.step = self.post(f'/projects/{self.project}/steps', {'name': 'Montagem'})['id']

    def post(self, path, data, status=200):
        response = self.client.post('/api'+path, json=data)
        self.assertEqual(response.status_code, status, response.json)
        return response.json

    def patch(self, path, data, status=200):
        response = self.client.patch('/api'+path, json=data)
        self.assertEqual(response.status_code, status, response.json)
        return response.json

    def document(self):
        return {'schema_version': 1, 'objective': {'title': 'Automação', 'description': 'Um resultado concreto', 'stages': [
            {'key': 'base', 'title': 'Preparação', 'tasks': [
                {'key': 'circuitos', 'title': 'Reaproveitar circuitos', 'planned_minutes': 60, 'source': {'kind': 'subject', 'id': self.subject}},
                {'key': 'sensores', 'title': 'Entender os sensores', 'planned_minutes': 90, 'source': {'kind': 'topic', 'id': self.topic}, 'requires': ['circuitos']}]},
            {'key': 'aplicar', 'title': 'Aplicação', 'tasks': [
                {'key': 'definir', 'title': 'Definir a aplicação', 'description': 'Sem vínculo obrigatório', 'planned_minutes': 30, 'requires': ['sensores']}]}
        ]}}

    def create(self, document=None, key='create'):
        return self.post('/objectives', {'document': document or self.document(), 'operation_key': key})

    def task(self, obj, key):
        return next(t for s in obj['stages'] for t in s['tasks'] if t['task_key'] == key)

    def test_live_status_review_and_existing_sessions_are_preserved(self):
        self.post('/sessions/manual', {'mode': 'duration', 'date': '2026-11-04', 'duration_seconds': 1800,
                                      'subject_id': self.subject, 'topic_id': self.topic, 'operation_key': 'time'})
        before = contents(self.path)
        obj = self.create()
        self.assertEqual((obj['progress'], obj['effective_seconds'], obj['planned_minutes']), (33, 1800, 180))
        self.assertEqual(self.task(obj, 'sensores')['status'], 'in_progress')
        # Parent subject and topic both match; objective total counts the session once.
        self.assertEqual(obj['stages'][0]['effective_seconds'], 1800)
        verify_preserved(self.path, {k: v for k, v in before.items() if not k.startswith('objective')})
        self.patch(f'/topics/{self.topic}', {'version': 1, 'completed': True, 'needs_review': True})
        obj = self.client.get(f'/api/objectives/{obj["id"]}').json
        self.assertEqual(obj['progress'], 67)
        task = self.task(obj, 'sensores')
        self.assertTrue(task['needs_review'])
        self.assertEqual(self.task(obj, 'definir')['pending_requires'], ['sensores'])
        obj = self.patch(f'/objectives/{obj["id"]}/tasks/{task["id"]}', {'version': obj['version'], 'source_version': task['source']['version'], 'needs_review': False})
        self.assertEqual((obj['progress'], self.task(obj, 'definir')['pending_requires']), (67, []))
        self.assertFalse(self.client.get('/api/topics').json[0]['needs_review'])

    def test_independent_goal_and_stale_mutations(self):
        doc = self.document()
        for s in doc['objective']['stages']:
            for t in s['tasks']:
                t['source'] = None
        obj = self.create(doc)
        task = self.task(obj, 'definir')
        updated = self.patch(f'/objectives/{obj["id"]}/tasks/{task["id"]}', {'version': obj['version'], 'status': 'completed', 'needs_review': True})
        self.assertEqual((updated['progress'], updated['review_count'], updated['effective_seconds']), (33, 1, 0))
        self.patch(f'/objectives/{obj["id"]}/tasks/{task["id"]}', {'version': obj['version'], 'status': 'not_started'}, 409)
        self.assertEqual(self.task(self.client.get(f'/api/objectives/{obj["id"]}').json, 'definir')['status'], 'completed')

    def test_linked_status_cannot_be_overwritten_or_stale_topic_review(self):
        obj = self.create()
        task = self.task(obj, 'circuitos')
        self.patch(f'/objectives/{obj["id"]}/tasks/{task["id"]}', {'version': 1, 'status': 'not_started'}, 400)
        topic = self.task(obj, 'sensores')
        self.patch(f'/topics/{self.topic}', {'version': 1, 'needs_review': True})
        self.patch(f'/objectives/{obj["id"]}/tasks/{topic["id"]}', {'version': 1, 'source_version': 1, 'needs_review': False}, 409)
        self.assertTrue(self.client.get('/api/topics').json[0]['needs_review'])

    def test_preview_is_read_only_invalid_and_cyclic_imports_are_atomic(self):
        before = contents(self.path)
        self.post('/objectives/preview', {'document': self.document()})
        self.assertEqual(before, contents(self.path))
        bad = []
        for minutes in (True, -1, 0, 1.5, 99999999):
            d = self.document(); d['objective']['stages'][0]['tasks'][0]['planned_minutes'] = minutes; bad.append(d)
        d = self.document(); d['objective']['stages'][0]['tasks'][0]['requires'] = ['definir']; bad.append(d)
        d = self.document(); d['objective']['stages'][0]['tasks'][0]['requires'] = ['missing']; bad.append(d)
        d = self.document(); d['objective']['stages'][0]['tasks'][0]['source'] = {'kind': [], 'id': 1}; bad.append(d)
        d = self.document(); d['objective']['stages'][0]['tasks'][0]['source']['id'] = 999999; bad.append(d)
        for d in bad:
            self.post('/objectives', {'document': d, 'operation_key': 'bad'}, 400)
            self.assertEqual(before, contents(self.path))

    def test_idempotent_create_and_path_revision_preserve_manual_state(self):
        obj = self.create()
        self.assertEqual(self.create()['id'], obj['id'])
        changed = self.document(); changed['objective']['title'] = 'Outro'
        self.post('/objectives', {'document': changed, 'operation_key': 'create'}, 409)
        task = self.task(obj, 'definir')
        obj = self.patch(f'/objectives/{obj["id"]}/tasks/{task["id"]}', {'version': 1, 'status': 'completed', 'needs_review': True})
        changed['objective']['stages'][1]['tasks'][0]['title'] = 'Nome revisado'
        response = self.client.put(f'/api/objectives/{obj["id"]}/path', json={'version': obj['version'], 'document': changed})
        self.assertEqual(response.status_code, 200, response.json)
        updated = response.json
        self.assertEqual((self.task(updated, 'definir')['status'], self.task(updated, 'definir')['needs_review']), ('completed', True))
        self.assertEqual(self.client.put(f'/api/objectives/{obj["id"]}/path', json={'version': 1, 'document': changed}).status_code, 409)
        broken = deepcopy(changed); broken['objective']['stages'][0]['tasks'][0]['requires'] = ['definir']
        before = contents(self.path)
        self.assertEqual(self.client.put(f'/api/objectives/{obj["id"]}/path', json={'version': updated['version'], 'document': broken}).status_code, 400)
        self.assertEqual(before, contents(self.path))
        db.diagnostics(self.path)

    def test_project_and_step_dynamic_status_archive_and_recovery(self):
        doc = self.document()
        a, b = doc['objective']['stages'][0]['tasks']
        a['source'] = {'kind': 'project', 'id': self.project}
        b['source'] = {'kind': 'step', 'id': self.step}
        obj = self.create(doc)
        self.patch(f'/projects/{self.project}/steps/{self.step}', {'version': 1, 'completed': True})
        obj = self.client.get(f'/api/objectives/{obj["id"]}').json
        self.assertEqual(self.task(obj, 'sensores')['status'], 'completed')
        obj = self.patch(f'/objectives/{obj["id"]}', {'version': obj['version'], 'archived': True})
        self.assertEqual(self.client.get('/api/objectives').json, [])
        self.assertEqual(len(self.client.get('/api/objectives?archived=1').json), 1)
        self.patch(f'/objectives/{obj["id"]}/tasks/{self.task(obj,"definir")["id"]}', {'version': obj['version'], 'status': 'completed'}, 409)
        backup = self.path.parent / 'backup.db'
        storage.copy_database(self.path, backup)
        self.assertEqual(contents(self.path), contents(backup))
        restored = create_app(backup).test_client().get(f'/api/objectives/{obj["id"]}').json
        self.assertEqual(restored['task_count'], 3)

    def test_next_task_respects_requirements_before_review_priority(self):
        doc = self.document()
        for stage in doc['objective']['stages']:
            for task in stage['tasks']:
                task['source'] = None
        obj = self.create(doc)
        pending = self.task(obj, 'definir')
        obj = self.patch(f'/objectives/{obj["id"]}/tasks/{pending["id"]}', {
            'version': obj['version'], 'needs_review': True})
        self.assertEqual(obj['next_task']['task_key'], 'circuitos')
        self.assertEqual(obj['blocked_count'], 2)
        first = self.task(obj, 'circuitos')
        obj = self.patch(f'/objectives/{obj["id"]}/tasks/{first["id"]}', {
            'version': obj['version'], 'status': 'completed'})
        self.assertEqual(obj['next_task']['task_key'], 'sensores')

    def test_source_links_resolve_exact_subject_topic_and_project(self):
        rows = self.client.get('/api/objectives/context').json['sources']
        refs = {(r['kind'], r['id']): r for r in rows}
        self.assertEqual(refs['subject', self.subject]['url'], f'/subjects?course={self.course}&subject={self.subject}')
        self.assertEqual(refs['topic', self.topic]['url'], f'/subjects?course={self.course}&subject={self.subject}&topic={self.topic}')
        self.assertEqual(refs['step', self.step]['url'], f'/projects?project={self.project}#step-{self.step}')
        self.assertEqual(refs['topic', self.topic]['course'], 'Curso')


if __name__ == '__main__':
    unittest.main()
