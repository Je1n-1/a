import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from flask import Flask

from database import connection
from database.migrations import migrate
from routes.api import api


class DailyGoalsAndReviewCampaignsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / "daily-goals.db"
        self.previous = connection.DATABASE_PATH
        connection.DATABASE_PATH = self.database
        migrate(self.database)
        self.clock = patch("services.core._local_now", return_value=datetime(2026, 9, 1, 8, 0))
        self.clock.start()
        app = Flask(__name__)
        app.config["TESTING"] = True
        app.register_blueprint(api)
        self.client = app.test_client()

    def tearDown(self):
        self.clock.stop()
        connection.DATABASE_PATH = self.previous
        self.temp.cleanup()

    def post(self, url, payload):
        response = self.client.post(url, json=payload)
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()

    def test_daily_goal_respects_selected_weekdays(self):
        study = self.post("/api/studies", {
            "personal_name": "Python", "daily_goal_minutes": 60,
            "daily_goal_mode": "per_selected_day", "allowed_weekdays": [1],
        })
        self.post("/api/availability", {"weekday": 1, "start_time": "07:00", "end_time": "09:00"})
        preview = self.post("/api/planning/generate-smart", {"start": "2026-09-01", "days": 2})
        self.assertEqual(sum(item["planned_duration_minutes"] for item in preview["sessions"]), 60)
        self.assertEqual({item["study_subject_id"] for item in preview["sessions"]}, {study["id"]})
        self.assertEqual(preview["items"][0]["demand_mode"], "recurring_daily")

    def test_campaign_preserves_completed_academic_status_and_splits_total(self):
        formation = self.post("/api/formations", {"name": "Engenharia"})
        first = self.post(f"/api/formations/{formation['id']}/curriculum", {
            "name": "Circuitos", "academic_status": "completed",
        })
        second = self.post(f"/api/formations/{formation['id']}/curriculum", {
            "name": "Cálculo", "academic_status": "completed",
        })
        campaign = self.post("/api/review-campaigns", {
            "name": "Retomada", "start_date": "2026-09-01", "end_date": "2026-09-02",
            "daily_goal_minutes": 120, "allowed_weekdays": [1],
            "curriculum_subject_ids": [first["id"], second["id"]],
        })
        self.assertTrue(campaign["created"])
        self.post("/api/availability", {"weekday": 1, "start_time": "07:00", "end_time": "11:00"})
        preview = self.post("/api/planning/generate-smart", {"start": "2026-09-01", "days": 2})
        campaign_items = [item for item in preview["items"] if item["review_campaign_id"] == campaign["campaign"]["id"]]
        self.assertEqual(len(campaign_items), 2)
        self.assertEqual(sum(item["daily_goal_minutes"] for item in campaign_items), 120)
        self.assertEqual(sum(item["planned_duration_minutes"] for item in preview["sessions"]), 120)
        self.assertTrue(all(item["review_campaign_id"] == campaign["campaign"]["id"] for item in preview["sessions"]))
        applied = self.post("/api/planning/apply", {"sessions": preview["sessions"]})
        block = applied["created"][0]
        session = self.post("/api/sessions", {
            "study_subject_id": block["study_subject_id"], "planned_session_id": block["id"],
            "date": "2026-09-01", "duration_seconds": block["planned_duration_minutes"] * 60,
            "entry_method": "manual",
        })
        self.assertEqual(session["review_campaign_id"], campaign["campaign"]["id"])
        for subject in (first, second):
            detail = self.client.get(f"/api/curriculum/{subject['id']}")
            self.assertEqual(detail.status_code, 200, detail.get_json())
            self.assertEqual(detail.get_json()["curriculum"]["academic_status"], "completed")

    def test_calendar_feed_does_not_duplicate_planned_completion(self):
        study = self.post("/api/studies", {"personal_name": "SQL"})
        block = self.post("/api/planned", {
            "study_subject_id": study["id"], "scheduled_date": "2026-09-01",
            "start_time": "09:00", "planned_duration_minutes": 45,
        })
        self.post("/api/sessions", {
            "study_subject_id": study["id"], "planned_session_id": block["id"],
            "date": "2026-09-01", "duration_seconds": 2700, "entry_method": "manual",
        })
        self.post("/api/sessions", {
            "study_subject_id": study["id"], "date": "2026-09-01",
            "duration_seconds": 1800, "entry_method": "manual",
        })
        response = self.client.get("/api/planning/calendar-events?start=2026-09-01&end=2026-09-01")
        self.assertEqual(response.status_code, 200, response.get_json())
        events = response.get_json()["events"]
        self.assertEqual(len(events), 2)
        self.assertEqual({event["event_type"] for event in events}, {"completed_planned_block", "unplanned_real_session"})
        completed = next(event for event in events if event["event_type"] == "completed_planned_block")
        self.assertEqual(completed["real_minutes"], 45)


if __name__ == "__main__":
    unittest.main()
