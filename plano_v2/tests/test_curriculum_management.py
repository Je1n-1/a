import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from flask import Flask

from database import connection
from database.migrations import migrate
from routes.api import api
from services import core


class CurriculumManagementApiTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / "plano-test.db"
        self.original_database_path = connection.DATABASE_PATH
        connection.DATABASE_PATH = self.database
        migrate(self.database)
        app = Flask(__name__)
        app.config["TESTING"] = True
        app.register_blueprint(api)
        self.client = app.test_client()
        self.clock = patch("services.core._local_now", return_value=datetime(2026, 9, 4, 10, 0, 0))
        self.clock.start()

    def tearDown(self):
        self.clock.stop()
        connection.DATABASE_PATH = self.original_database_path
        self.temp.cleanup()

    def formation(self, name="Engenharia de Computação"):
        response = self.client.post("/api/formations", json={"name": name})
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()

    def curriculum(self, formation, name="Circuitos Elétricos I", **extra):
        response = self.client.post(f"/api/formations/{formation['id']}/curriculum", json={"name": name, **extra})
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()

    def active_study(self, curriculum):
        response = self.client.post(f"/api/curriculum/{curriculum['id']}/add-study", json={})
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()

    def planned(self, study, day="2026-09-05"):
        response = self.client.post("/api/planned", json={
            "study_subject_id": study["id"], "scheduled_date": day,
            "start_time": "08:00", "planned_duration_minutes": 50,
        })
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()

    def test_archive_formation_hides_study_cancels_future_and_restores_only_its_own_archives(self):
        formation = self.formation()
        subject = self.curriculum(formation, academic_status="available")
        study = self.active_study(subject)
        block = self.planned(study)
        archived = self.client.post(f"/api/formations/{formation['id']}/archive", json={"study_policy": "archive_studies"})
        self.assertEqual(archived.status_code, 200, archived.get_json())
        self.assertEqual(archived.get_json()["archived_studies"]["ids"], [study["id"]])
        self.assertEqual(archived.get_json()["cancelled_future_blocks"]["ids"], [block["id"]])
        self.assertEqual(self.client.get("/api/studies").get_json(), [])
        archived_studies = self.client.get("/api/studies?visibility=archived")
        self.assertEqual(archived_studies.status_code, 200, archived_studies.get_json())
        self.assertEqual(archived_studies.get_json()[0]["visibility_reason"], "study_archived")
        restored = self.client.post(f"/api/formations/{formation['id']}/restore", json={"restore_studies": True})
        self.assertEqual(restored.status_code, 200, restored.get_json())
        self.assertEqual(restored.get_json()["restored_studies"]["ids"], [study["id"]])
        self.assertEqual(self.client.get("/api/studies").get_json()[0]["id"], study["id"])
        self.assertEqual(self.client.get(f"/api/planned/{block['id']}").get_json()["status"], "cancelled")

    def test_completed_review_is_independent_from_academic_progress_and_has_history(self):
        formation = self.formation()
        subject = self.curriculum(formation, academic_status="completed")
        reviewed = self.client.post(f"/api/curriculum/{subject['id']}/review", json={"status": "queued", "priority": 4})
        self.assertEqual(reviewed.status_code, 200, reviewed.get_json())
        self.assertEqual(reviewed.get_json()["academic_status"], "completed")
        management = self.client.get(f"/api/formations/{formation['id']}/curriculum/management?quick=review")
        self.assertEqual(management.status_code, 200, management.get_json())
        payload = management.get_json()
        self.assertEqual(payload["summary"]["completed"], 1)
        self.assertEqual(payload["summary"]["review"], 1)
        self.assertEqual(payload["summary"]["academic_progress_percent"], 100.0)
        started = self.client.post(f"/api/curriculum/{subject['id']}/review", json={"status": "in_progress", "start_study": True})
        self.assertEqual(started.status_code, 200, started.get_json())
        self.assertEqual(started.get_json()["academic_status"], "completed")
        self.assertEqual(started.get_json()["study"]["status"], "active")
        history = self.client.get(f"/api/curriculum/{subject['id']}/history")
        self.assertEqual(history.status_code, 200, history.get_json())
        self.assertTrue(any(row["review_status"] == "in_progress" for row in history.get_json()))

    def test_archived_parent_is_hidden_but_found_in_archive_filter_and_blocks_new_focus_or_plan(self):
        formation = self.formation()
        subject = self.curriculum(formation, academic_status="available")
        study = self.active_study(subject)
        archived = self.client.post(f"/api/formations/{formation['id']}/archive", json={"study_policy": "hide_studies"})
        self.assertEqual(archived.status_code, 200, archived.get_json())
        self.assertEqual(archived.get_json()["archived_studies"]["count"], 0)
        hidden = self.client.get("/api/studies")
        self.assertEqual(hidden.status_code, 200, hidden.get_json())
        found = self.client.get("/api/studies?visibility=archived")
        self.assertEqual(found.status_code, 200, found.get_json())
        self.assertEqual(found.get_json()[0]["visibility_reason"], "formation_archived")
        blocked = self.client.post("/api/planned", json={
            "study_subject_id": study["id"], "scheduled_date": "2026-09-05", "planned_duration_minutes": 30,
        })
        self.assertEqual(blocked.status_code, 409, blocked.get_json())
        self.assertEqual(blocked.get_json()["code"], "archived_parent")

    def test_remove_current_defaults_available_and_preserves_history_while_cancelling_future(self):
        formation = self.formation()
        subject = self.curriculum(formation, academic_status="available")
        study = self.active_study(subject)
        block = self.planned(study)
        removed = self.client.post(f"/api/studies/{study['id']}/remove-current", json={"academic_status": "available", "cancel_future_blocks": True})
        self.assertEqual(removed.status_code, 200, removed.get_json())
        self.assertEqual(removed.get_json()["study"]["status"], "archived")
        self.assertEqual(removed.get_json()["study"]["archive_reason"], "removed_current")
        self.assertEqual(removed.get_json()["academic_status"], "available")
        self.assertEqual(removed.get_json()["cancelled_future_blocks"]["ids"], [block["id"]])
        record = self.client.get(f"/api/curriculum/{subject['id']}/dependencies")
        self.assertEqual(record.status_code, 200, record.get_json())
        self.assertEqual(record.get_json()["dependencies"]["study_subjects"]["count"], 1)

    def test_dependency_preview_and_confirmed_destroy_are_scoped_and_checked(self):
        first = self.formation("Formação A")
        second = self.formation("Formação B")
        subject = self.curriculum(first, "Álgebra Linear", academic_status="available")
        other = self.curriculum(second, "Álgebra Linear", academic_status="available")
        study = self.active_study(subject)
        topic = self.client.post(f"/api/studies/{study['id']}/topics", json={"name": "Vetores"}).get_json()
        self.planned(study)
        self.client.post("/api/notes", json={"study_subject_id": study["id"], "topic_id": topic["id"], "title": "Nota"})
        dependencies = self.client.get(f"/api/curriculum/{subject['id']}/dependencies")
        self.assertEqual(dependencies.status_code, 200, dependencies.get_json())
        self.assertEqual(dependencies.get_json()["dependencies"]["topics"]["count"], 1)
        blocked = self.client.delete(f"/api/curriculum/{subject['id']}")
        self.assertEqual(blocked.status_code, 409, blocked.get_json())
        self.assertEqual(blocked.get_json()["code"], "curriculum_has_dependencies")
        wrong = self.client.post(f"/api/curriculum/{subject['id']}/destroy", json={"confirmation": "errado", "include_dependencies": True})
        self.assertEqual(wrong.status_code, 400, wrong.get_json())
        deleted = self.client.post(f"/api/curriculum/{subject['id']}/destroy", json={"confirmation": "Álgebra Linear", "include_dependencies": True})
        self.assertEqual(deleted.status_code, 200, deleted.get_json())
        self.assertTrue(Path(deleted.get_json()["backup"]).is_file())
        self.assertEqual(self.client.get(f"/api/curriculum/{subject['id']}/dependencies").status_code, 404)
        self.assertEqual(self.client.get(f"/api/formations/{second['id']}/curriculum").get_json()[0]["id"], other["id"])
        with connection.connect() as conn:
            self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_destroy_rolls_back_when_the_final_integrity_validation_fails(self):
        formation = self.formation()
        subject = self.curriculum(formation, "Disciplina para rollback")
        with patch(
            "services.core._assert_foreign_keys",
            side_effect=core.DomainError("Falha simulada de integridade.", 500, "foreign_key_check_failed"),
        ):
            response = self.client.post(
                f"/api/curriculum/{subject['id']}/destroy",
                json={"confirmation": subject["name"], "include_dependencies": True},
            )
        self.assertEqual(response.status_code, 500, response.get_json())
        self.assertEqual(response.get_json()["code"], "foreign_key_check_failed")
        self.assertEqual(self.client.get(f"/api/curriculum/{subject['id']}/dependencies").status_code, 200)
        with connection.connect() as conn:
            self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_candidates_merge_and_structural_items_do_not_distort_progress(self):
        formation = self.formation()
        clean = self.curriculum(formation, "Circuitos Elétricos I", academic_status="available")
        old = self.curriculum(formation, "Circuitos Elétricos I 45", academic_status="in_progress")
        ucfc = self.curriculum(formation, "UCFC – 1º período", academic_status="completed")
        study = self.active_study(old)
        candidates = self.client.get(f"/api/formations/{formation['id']}/curriculum/duplicates")
        self.assertEqual(candidates.status_code, 200, candidates.get_json())
        self.assertEqual(candidates.get_json()["count"], 1)
        merged = self.client.post(f"/api/formations/{formation['id']}/curriculum/merge", json={
            "primary_id": clean["id"], "duplicate_ids": [old["id"]], "confirmation": clean["name"],
            "preserve": {"academic_status": "in_progress", "workload_minutes": 2700},
        })
        self.assertEqual(merged.status_code, 200, merged.get_json())
        self.assertEqual(merged.get_json()["primary"]["id"], clean["id"])
        self.assertEqual(self.client.get(f"/api/studies/{study['id']}").get_json()["curriculum_subject_id"], clean["id"])
        structural = self.client.get(f"/api/formations/{formation['id']}/curriculum/structural-candidates")
        self.assertEqual(structural.status_code, 200, structural.get_json())
        self.assertEqual(structural.get_json()["items"][0]["id"], ucfc["id"])
        classified = self.client.post(f"/api/formations/{formation['id']}/curriculum/batch", json={"ids": [ucfc["id"]], "action": "classify", "item_type": "section"})
        self.assertEqual(classified.status_code, 200, classified.get_json())
        summary = self.client.get(f"/api/formations/{formation['id']}/curriculum/management").get_json()["summary"]
        self.assertEqual(summary["total_subjects"], 1)
        self.assertEqual(summary["academic_progress_percent"], 0)

    def test_analytics_keeps_real_sessions_distinct_from_completed_plans(self):
        study = self.client.post("/api/studies", json={"personal_name": "Estudo livre"}).get_json()
        block = self.planned(study, "2026-09-04")
        self.client.patch(f"/api/planned/{block['id']}", json={"status": "completed"})
        analytics = self.client.get("/api/analytics")
        self.assertEqual(analytics.status_code, 200, analytics.get_json())
        self.assertEqual(analytics.get_json()["real_sessions"], 0)
        self.assertEqual(analytics.get_json()["completed_planned_blocks"], 1)
        self.assertEqual(analytics.get_json()["completed_planned_without_real_session"], 1)


if __name__ == "__main__":
    unittest.main()
