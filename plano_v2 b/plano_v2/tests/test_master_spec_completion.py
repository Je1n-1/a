import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch

from flask import Flask

from database import connection
from database.migrations import migrate
from routes.api import api
from routes.pages import pages


ROOT = Path(__file__).resolve().parents[1]


class MasterSpecCompletionTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / "master-spec.db"
        self.previous = connection.DATABASE_PATH
        connection.DATABASE_PATH = self.database
        migrate(self.database)
        self.clock = patch("services.core._local_now", return_value=datetime(2026, 9, 21, 9, 0))
        self.clock.start()
        app = Flask(__name__, template_folder=str(ROOT / "templates"), static_folder=str(ROOT / "static"))
        app.config["TESTING"] = True
        app.register_blueprint(pages)
        app.register_blueprint(api)
        self.client = app.test_client()

    def tearDown(self):
        self.clock.stop()
        connection.DATABASE_PATH = self.previous
        self.temp.cleanup()

    def post(self, url, payload=None, expected=200):
        response = self.client.post(url, json=payload or {})
        self.assertEqual(response.status_code, expected, response.get_json())
        return response.get_json()

    def personal(self, name="Cálculo", **values):
        return self.post("/api/studies", {
            "personal_name": name, "difficulty": 3, "mastery_level": None,
            "start_date": "2026-09-21", "target_date": "2026-10-18",
            "allowed_weekdays": [0, 1, 2, 3, 4, 5],
            "idempotency_key": f"personal-{name}", **values,
        })

    def test_registration_preview_has_no_side_effect_and_exposes_capacity_impact(self):
        before = self.client.get("/api/studies?visibility=all").get_json()
        preview = self.post("/api/studies/preview", {
            "registration_kind": "personal", "personal_name": "Álgebra",
            "difficulty": 4, "mastery_level": "unknown", "start_date": "2026-09-21",
            "allowed_weekdays": [0, 2, 4], "preferred_block_minutes": 50,
        })
        after = self.client.get("/api/studies?visibility=all").get_json()
        self.assertEqual(before, after)
        self.assertFalse(preview["persisted"])
        self.assertEqual(preview["subject_name"], "Álgebra")
        self.assertIn("recommended_block_minutes", preview)
        self.assertIn("remaining_capacity_minutes", preview)
        self.assertFalse(preview["will_persist_deadline"])

    def test_curriculum_unknown_effort_and_deadline_remain_null_and_retry_is_idempotent(self):
        formation = self.post("/api/formations", {"name": "Engenharia"})
        subject = self.post(f"/api/formations/{formation['id']}/curriculum", {
            "name": "Fenômenos de Transporte", "academic_status": "available",
        })
        payload = {
            "difficulty": "unknown", "mastery_level": "unknown",
            "start_date": "2026-09-21", "effort_mode": "automatic",
            "idempotency_key": "start-fenomenos",
        }
        first = self.post(f"/api/curriculum/{subject['id']}/start", payload)
        second = self.post(f"/api/curriculum/{subject['id']}/start", payload)
        self.assertEqual(first["study"]["id"], second["study"]["id"])
        self.assertTrue(second["idempotent"])
        self.assertIsNone(first["profile"]["persisted_required_study_minutes"])
        with connection.connect() as conn:
            curriculum = conn.execute(
                "SELECT required_study_minutes,deadline_date FROM disciplinas_grade WHERE id=?",
                (subject["id"],),
            ).fetchone()
            count = conn.execute("SELECT COUNT(*) FROM materias_estudo").fetchone()[0]
        self.assertEqual(tuple(curriculum), (None, None))
        self.assertEqual(count, 1)

    def test_fatigue_shortens_a_long_block_without_increasing_daily_budget(self):
        study = self.personal("Física", preferred_block_minutes=120)
        before = self.client.get(f"/api/studies/{study['id']}/recommendation").get_json()
        result = self.post(f"/api/studies/{study['id']}/observations", {
            "kind": "fatigue", "raw_value": "high", "idempotency_key": "fatigue-1",
        })
        after = result["recommendation"]
        self.assertEqual(after["recommended_block_minutes"], 40)
        self.assertEqual(after["recommended_daily_minutes"], before["recommended_daily_minutes"])

    def test_new_content_changes_only_future_budget_not_studied_hours(self):
        study = self.personal("Biologia")
        with connection.connect() as conn:
            before = conn.execute(
                "SELECT current_budget_minutes FROM study_plan_baselines WHERE study_subject_id=?",
                (study["id"],),
            ).fetchone()[0]
        result = self.post(f"/api/studies/{study['id']}/observations", {
            "kind": "new_content", "raw_value": "novo capítulo", "idempotency_key": "content-1",
        })
        with connection.connect() as conn:
            after = conn.execute(
                "SELECT current_budget_minutes FROM study_plan_baselines WHERE study_subject_id=?",
                (study["id"],),
            ).fetchone()[0]
            studied = conn.execute("SELECT COUNT(*) FROM sessoes_estudo").fetchone()[0]
        self.assertTrue(result["adjustment_applied"])
        self.assertGreater(after, before)
        self.assertEqual(studied, 0)

    @patch('services.adaptive_planning._today', return_value=date(2026, 9, 21))
    @patch('services.adaptive_planning._now', return_value='2026-09-21T09:00:00.000000-03:00')
    def test_deadline_check_is_once_and_prepared_does_not_add_budget(self, _now, _today):
        study = self.personal("Química", target_date="2026-09-25")
        recommendation = self.client.get(f"/api/studies/{study['id']}/recommendation").get_json()
        self.assertTrue(recommendation["deadline_check_due"])
        with connection.connect() as conn:
            budget_before = conn.execute(
                "SELECT current_budget_minutes FROM study_plan_baselines WHERE study_subject_id=?",
                (study["id"],),
            ).fetchone()[0]
        first = self.post(f"/api/studies/{study['id']}/observations", {
            "kind": "deadline_check", "raw_value": "prepared", "idempotency_key": "deadline-1",
        })
        second = self.post(f"/api/studies/{study['id']}/observations", {
            "kind": "deadline_check", "raw_value": "needs_more", "idempotency_key": "deadline-2",
        })
        with connection.connect() as conn:
            budget_after = conn.execute(
                "SELECT current_budget_minutes FROM study_plan_baselines WHERE study_subject_id=?",
                (study["id"],),
            ).fetchone()[0]
        self.assertFalse(first["adjustment_applied"])
        self.assertTrue(second["deadline_check_already_recorded"])
        self.assertEqual(budget_before, budget_after)

    def test_session_edit_is_audited_and_idempotent(self):
        study = self.personal("História")
        session = self.post("/api/sessions", {
            "study_subject_id": study["id"], "date": "2026-09-21",
            "duration_seconds": 1800, "entry_method": "manual", "purpose": "study",
        })
        payload = {"duration_seconds": 2400, "notes": "corrigido", "edit_reason": "anotação incorreta", "idempotency_key": "edit-1"}
        first = self.client.patch(f"/api/sessions/{session['id']}", json=payload)
        second = self.client.patch(f"/api/sessions/{session['id']}", json=payload)
        self.assertEqual(first.status_code, 200, first.get_json())
        self.assertTrue(second.get_json()["idempotent"])
        detail = self.client.get(f"/api/sessions/{session['id']}").get_json()
        self.assertEqual(detail["duration_seconds"], 2400)
        self.assertEqual(len(detail["corrections"]), 1)
        self.assertEqual(detail["corrections"][0]["correction_type"], "edit_session")

    def test_accent_insensitive_search_and_real_analytics_series(self):
        study = self.personal("Cálculo Numérico")
        rows = self.client.get("/api/studies?visibility=all&q=calculo").get_json()
        self.assertEqual([row["id"] for row in rows], [study["id"]])
        self.post("/api/sessions", {
            "study_subject_id": study["id"], "date": "2026-09-21",
            "duration_seconds": 3600, "entry_method": "manual", "purpose": "study",
        })
        analytics = self.client.get(
            f"/api/analytics/detailed?start=2026-09-21&end=2026-09-21&item_id={study['id']}&purpose=study"
        ).get_json()
        self.assertEqual(analytics["totals"]["focus_seconds"], 3600)
        self.assertEqual(analytics["daily"][0]["subjects"][0]["name"], "Cálculo Numérico")
        self.assertEqual(analytics["filters"]["purpose"], "study")


if __name__ == "__main__":
    unittest.main()
