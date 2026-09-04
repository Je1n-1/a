import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from flask import Flask

from database import connection
from database.migrations import migrate
from routes.api import api
from routes.pages import pages


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class PlanningAndFocusTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / "plano-test.db"
        self.original_database_path = connection.DATABASE_PATH
        connection.DATABASE_PATH = self.database
        migrate(self.database)
        app = Flask(
            __name__,
            template_folder=str(PROJECT_ROOT / "templates"),
            static_folder=str(PROJECT_ROOT / "static"),
        )
        app.config["TESTING"] = True
        app.register_blueprint(pages)
        app.register_blueprint(api)
        self.client = app.test_client()
        self.clock = patch("services.core._local_now", return_value=datetime(2026, 9, 4, 10, 0, 0))
        self.clock.start()

    def tearDown(self):
        self.clock.stop()
        connection.DATABASE_PATH = self.original_database_path
        self.temp.cleanup()

    def study_and_topic(self):
        study = self.client.post("/api/studies", json={"personal_name": "Circuitos Elétricos I"})
        self.assertEqual(study.status_code, 200, study.get_json())
        topic = self.client.post(f"/api/studies/{study.get_json()['id']}/topics", json={"name": "Análise nodal"})
        self.assertEqual(topic.status_code, 200, topic.get_json())
        return study.get_json(), topic.get_json()

    def create_planned(self, date="2026-09-04", start_time="06:00"):
        study, topic = self.study_and_topic()
        response = self.client.post("/api/planned", json={
            "study_subject_id": study["id"],
            "topic_id": topic["id"],
            "scheduled_date": date,
            "start_time": start_time,
            "planned_duration_minutes": 50,
        })
        self.assertEqual(response.status_code, 200, response.get_json())
        return study, topic, response.get_json()

    def test_planned_delete_removes_block_from_visible_range(self):
        _, _, first = self.create_planned()
        _, _, second = self.create_planned(date="2026-10-01", start_time="13:00")
        visible = self.client.get("/api/planned?start=2026-09-01&end=2026-09-30")
        self.assertEqual(visible.status_code, 200, visible.get_json())
        self.assertEqual([item["id"] for item in visible.get_json()], [first["id"]])
        deleted = self.client.delete(f"/api/planned/{first['id']}")
        self.assertEqual(deleted.status_code, 200, deleted.get_json())
        self.assertEqual(self.client.get("/api/planned?start=2026-09-01&end=2026-09-30").get_json(), [])
        self.assertEqual(self.client.get(f"/api/planned/{first['id']}").status_code, 404)
        self.assertEqual([item["id"] for item in self.client.get("/api/planned?start=2026-10-01&end=2026-10-31").get_json()], [second["id"]])

    def test_daily_planned_delete_is_atomic_and_keeps_historic_or_other_dates(self):
        _, _, first = self.create_planned(start_time="06:00")
        _, _, second = self.create_planned(start_time="08:00")
        _, _, cancelled = self.create_planned(start_time="10:00")
        _, _, completed = self.create_planned(start_time="12:00")
        _, _, following_day = self.create_planned(date="2026-09-05", start_time="06:00")
        self.assertEqual(
            self.client.patch(f"/api/planned/{cancelled['id']}", json={"status": "cancelled"}).status_code,
            200,
        )
        self.assertEqual(
            self.client.patch(f"/api/planned/{completed['id']}", json={"status": "completed"}).status_code,
            200,
        )

        deleted = self.client.delete("/api/planned/day/2026-09-04")
        self.assertEqual(deleted.status_code, 200, deleted.get_json())
        self.assertEqual(deleted.get_json(), {"deleted": 2, "ids": [first["id"], second["id"]]})
        self.assertEqual(self.client.get(f"/api/planned/{first['id']}").status_code, 404)
        self.assertEqual(self.client.get(f"/api/planned/{second['id']}").status_code, 404)
        self.assertEqual(self.client.get(f"/api/planned/{cancelled['id']}").get_json()["status"], "cancelled")
        self.assertEqual(self.client.get(f"/api/planned/{completed['id']}").get_json()["status"], "completed")
        self.assertEqual(self.client.get(f"/api/planned/{following_day['id']}").status_code, 200)

        # Uma data inválida falha antes de executar o DELETE; não há remoção parcial.
        invalid = self.client.delete("/api/planned/day/20260905")
        self.assertEqual(invalid.status_code, 400, invalid.get_json())
        self.assertEqual(self.client.get(f"/api/planned/{following_day['id']}").status_code, 200)

    def test_cancel_preserves_history_and_reschedule_creates_a_successor(self):
        _, _, cancelled = self.create_planned(start_time="08:00")
        response = self.client.patch(f"/api/planned/{cancelled['id']}", json={"status": "cancelled"})
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()["status"], "cancelled")
        self.assertEqual(self.client.get("/api/planned?start=2026-09-04&end=2026-09-04").get_json(), [])
        self.assertEqual(self.client.get(f"/api/planned/{cancelled['id']}").get_json()["status"], "cancelled")

        _, _, original = self.create_planned(start_time="10:00")
        moved = self.client.post(f"/api/planned/{original['id']}/reschedule", json={
            "scheduled_date": "2026-09-05",
            "start_time": "13:13",
            "planned_duration_minutes": 90,
        })
        self.assertEqual(moved.status_code, 200, moved.get_json())
        payload = moved.get_json()
        self.assertEqual(payload["previous"]["status"], "rescheduled")
        self.assertEqual(payload["rescheduled"]["scheduled_date"], "2026-09-05")
        self.assertEqual(payload["rescheduled"]["start_time"], "13:13")
        self.assertEqual(payload["rescheduled"]["planned_duration_minutes"], 90)
        self.assertEqual(self.client.get(f"/api/planned/{original['id']}").get_json()["rescheduled_to_id"], payload["rescheduled"]["id"])

    def test_finishing_planned_session_marks_block_complete_once(self):
        study, topic, planned = self.create_planned()
        payload = {
            "study_subject_id": study["id"],
            "topic_id": topic["id"],
            "planned_session_id": planned["id"],
            "date": "2026-09-04",
            "started_at": "2026-09-04T06:00:00-03:00",
            "ended_at": "2026-09-04T06:25:00-03:00",
            "duration_seconds": 1500,
            "entry_method": "timer",
        }
        completed = self.client.post("/api/sessions", json=payload)
        self.assertEqual(completed.status_code, 200, completed.get_json())
        self.assertEqual(self.client.get(f"/api/planned/{planned['id']}").get_json()["status"], "completed")
        duplicate = self.client.post("/api/sessions", json=payload)
        self.assertEqual(duplicate.status_code, 409, duplicate.get_json())
        self.assertEqual(duplicate.get_json()["code"], "planned_already_completed")

    def test_focus_route_is_available(self):
        response = self.client.get("/focus")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"data-focus-page", response.data)

    def test_focus_entrypoints_open_the_dedicated_page(self):
        source = (PROJECT_ROOT / "static" / "js" / "app.js").read_text(encoding="utf-8")
        self.assertIn('if (target.dataset.action === "focus") return openPlanningFocus(null, target);', source)
        self.assertIn('if (target.dataset.focus !== undefined) return openPlanningFocus(null, target);', source)
        self.assertIn('if (target.dataset.startPlan) return openPlanningFocus(Number(target.dataset.startPlan), target);', source)
        self.assertNotIn('target.dataset.startPlan) return startTimer(', source)


if __name__ == "__main__":
    unittest.main()
