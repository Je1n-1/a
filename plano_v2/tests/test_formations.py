import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from flask import Flask

from database import connection
from database.migrations import migrate
from routes.api import api


class FormationApiTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / "plano-test.db"
        self.original_database_path = connection.DATABASE_PATH
        connection.DATABASE_PATH = self.database
        migrate(self.database)
        app = Flask(__name__)
        app.register_blueprint(api)
        app.config["TESTING"] = True
        self.client = app.test_client()
        self.clock = patch("services.core._local_now", return_value=datetime(2026, 9, 4, 10, 0, 0))
        self.clock.start()

    def tearDown(self):
        self.clock.stop()
        connection.DATABASE_PATH = self.original_database_path
        self.temp.cleanup()

    def create_formation(self, **extra):
        payload = {"name": "Engenharia Elétrica", "institution": "Instituto Teste", **extra}
        response = self.client.post("/api/formations", json=payload)
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()

    def test_create_edit_and_delete_empty_formation(self):
        formation = self.create_formation()
        edited = self.client.patch(f"/api/formations/{formation['id']}", json={
            "name": "Engenharia de Computação",
            "institution": "Universidade Teste",
            "modality": "Presencial",
            "start_date": "2026-02-01",
            "expected_end_date": "2030-12-01",
            "status": "paused",
            "focus_priority": 5,
        })
        self.assertEqual(edited.status_code, 200, edited.get_json())
        self.assertEqual(edited.get_json()["name"], "Engenharia de Computação")
        self.assertEqual(edited.get_json()["focus_priority"], 5)
        partial = self.client.patch(f"/api/formations/{formation['id']}", json={"name": "Engenharia de Computação II"})
        self.assertEqual(partial.status_code, 200, partial.get_json())
        self.assertEqual(partial.get_json()["institution"], "Universidade Teste")
        cleared = self.client.patch(f"/api/formations/{formation['id']}", json={"institution": "", "modality": "", "start_date": "", "expected_end_date": ""})
        self.assertEqual(cleared.status_code, 200, cleared.get_json())
        self.assertIsNone(cleared.get_json()["institution"])
        self.assertIsNone(cleared.get_json()["start_date"])
        deleted = self.client.delete(f"/api/formations/{formation['id']}")
        self.assertEqual(deleted.status_code, 200, deleted.get_json())
        self.assertEqual(self.client.get("/api/formations?state=all").get_json(), [])

    def test_formation_with_curriculum_cannot_be_deleted_and_can_be_archived(self):
        formation = self.create_formation()
        curriculum = self.client.post(f"/api/formations/{formation['id']}/curriculum", json={"name": "Cálculo I"})
        self.assertEqual(curriculum.status_code, 200, curriculum.get_json())
        blocked = self.client.delete(f"/api/formations/{formation['id']}")
        self.assertEqual(blocked.status_code, 409)
        self.assertEqual(blocked.get_json()["code"], "formation_has_dependencies")
        self.assertIn("Arquive", blocked.get_json()["error"])
        self.assertEqual(blocked.get_json()["blockers"], {
            "curriculum_subjects": 1,
            "study_subjects": 0,
            "topics": 0,
            "planned_sessions": 0,
            "study_sessions": 0,
            "notes": 0,
            "reviews": 0,
            "evaluations": 0,
        })
        archived = self.client.post(f"/api/formations/{formation['id']}/archive")
        self.assertEqual(archived.status_code, 200, archived.get_json())
        self.assertEqual([item["id"] for item in self.client.get("/api/formations?state=archived").get_json()], [formation["id"]])
        blocked_add = self.client.post(f"/api/formations/{formation['id']}/curriculum", json={"name": "Álgebra Linear"})
        self.assertEqual(blocked_add.status_code, 409, blocked_add.get_json())
        self.assertEqual(blocked_add.get_json()["code"], "formation_archived")
        archived_edit = self.client.patch(f"/api/formations/{formation['id']}", json={"name": "Novo nome"})
        self.assertEqual(archived_edit.status_code, 409, archived_edit.get_json())
        self.assertEqual(archived_edit.get_json()["code"], "formation_archived")
        read_only = self.client.patch(f"/api/curriculum/{curriculum.get_json()['id']}", json={"name": "Cálculo Diferencial"})
        self.assertEqual(read_only.status_code, 409, read_only.get_json())
        self.assertEqual(read_only.get_json()["code"], "formation_archived")
        restored = self.client.post(f"/api/formations/{formation['id']}/restore")
        self.assertEqual(restored.status_code, 200, restored.get_json())
        self.assertIsNone(restored.get_json()["archived_at"])
        self.assertEqual(restored.get_json()["status"], "active")

    def test_formation_delete_reports_historic_links_without_removing_them(self):
        formation = self.create_formation()
        curriculum = self.client.post(f"/api/formations/{formation['id']}/curriculum", json={
            "name": "Eletrônica I", "academic_status": "available",
        }).get_json()
        study = self.client.post(f"/api/curriculum/{curriculum['id']}/add-study", json={})
        self.assertEqual(study.status_code, 200, study.get_json())
        study = study.get_json()
        topic = self.client.post(f"/api/studies/{study['id']}/topics", json={"name": "Diodos"})
        self.assertEqual(topic.status_code, 200, topic.get_json())
        topic = topic.get_json()
        planned = self.client.post("/api/planned", json={
            "study_subject_id": study["id"],
            "topic_id": topic["id"],
            "scheduled_date": "2026-09-04",
            "start_time": "08:00",
            "planned_duration_minutes": 50,
        })
        self.assertEqual(planned.status_code, 200, planned.get_json())
        session = self.client.post("/api/sessions", json={
            "study_subject_id": study["id"],
            "topic_id": topic["id"],
            "date": "2026-09-04",
            "duration_seconds": 1500,
            "entry_method": "manual",
        })
        self.assertEqual(session.status_code, 200, session.get_json())
        note = self.client.post("/api/notes", json={
            "study_subject_id": study["id"],
            "topic_id": topic["id"],
            "title": "Rascunho de diodos",
            "content_markdown": "Anotação de estudo.",
        })
        self.assertEqual(note.status_code, 200, note.get_json())
        evaluation = self.client.post("/api/evaluations", json={
            "study_subject_id": study["id"],
            "title": "Prova 1",
            "date": "2026-09-10",
        })
        self.assertEqual(evaluation.status_code, 200, evaluation.get_json())

        blocked = self.client.delete(f"/api/formations/{formation['id']}")
        self.assertEqual(blocked.status_code, 409, blocked.get_json())
        payload = blocked.get_json()
        self.assertEqual(payload["code"], "formation_has_dependencies")
        self.assertEqual(payload["blockers"], {
            "curriculum_subjects": 1,
            "study_subjects": 1,
            "topics": 1,
            "planned_sessions": 1,
            "study_sessions": 1,
            "notes": 1,
            "reviews": 1,
            "evaluations": 1,
        })
        self.assertIn("1 bloco de planejamento", payload["error"])
        self.assertEqual(self.client.get(f"/api/formations/{formation['id']}/curriculum").status_code, 200)
        self.assertEqual(self.client.get(f"/api/studies/{study['id']}").status_code, 200)
        self.assertEqual(self.client.get(f"/api/planned/{planned.get_json()['id']}").status_code, 200)
        sessions = self.client.get("/api/sessions?start=2026-09-04&end=2026-09-04")
        self.assertEqual(sessions.status_code, 200, sessions.get_json())
        self.assertIn(session.get_json()["id"], {item["id"] for item in sessions.get_json()})

    def test_formation_filter_and_validation_errors_are_friendly(self):
        active = self.create_formation(name="Ativa")
        archived = self.create_formation(name="Arquivada")
        self.client.post(f"/api/formations/{archived['id']}/archive")
        self.assertEqual([item["id"] for item in self.client.get("/api/formations?state=active").get_json()], [active["id"]])
        self.assertEqual([item["id"] for item in self.client.get("/api/formations?state=archived").get_json()], [archived["id"]])
        self.assertEqual({item["id"] for item in self.client.get("/api/formations?state=all").get_json()}, {active["id"], archived["id"]})
        bad_filter = self.client.get("/api/formations?state=unexpected")
        self.assertEqual(bad_filter.status_code, 400, bad_filter.get_json())
        invalid = self.client.post("/api/formations", json={"name": "Inválida", "focus_priority": 8})
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(invalid.get_json()["code"], "domain_error")
        archive_directly = self.client.post("/api/formations", json={"name": "Arquivada diretamente", "status": "archived"})
        self.assertEqual(archive_directly.status_code, 400)
        self.assertEqual(archive_directly.get_json()["code"], "use_archive_action")
        dates = self.client.post("/api/formations", json={"name": "Datas", "start_date": "2030-01-01", "expected_end_date": "2029-01-01"})
        self.assertEqual(dates.status_code, 400)
        self.assertIn("previsão", dates.get_json()["error"].lower())


if __name__ == "__main__":
    unittest.main()
