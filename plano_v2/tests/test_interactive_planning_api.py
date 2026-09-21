from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from flask import Flask

from database import connection
from database.migrations import migrate
from routes.api import api


class InteractivePlanningApiTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / "interactive.db"
        self.previous = connection.DATABASE_PATH
        connection.DATABASE_PATH = self.database
        migrate(self.database)
        self.clock = patch("services.core._local_now", return_value=datetime(2026, 9, 21, 6, 0))
        self.clock.start()
        app = Flask(__name__)
        app.config["TESTING"] = True
        app.register_blueprint(api)
        self.client = app.test_client()

    def tearDown(self):
        self.clock.stop()
        connection.DATABASE_PATH = self.previous
        self.temp.cleanup()

    def post(self, url, values=None, expected=200):
        response = self.client.post(url, json=values or {})
        self.assertEqual(response.status_code, expected, response.get_json())
        return response.get_json()

    def study(self, name="Programação", **values):
        return self.post("/api/studies", {
            "personal_name": name, "start_date": "2026-09-21", "target_date": "2026-09-23",
            "required_study_minutes": 150, "difficulty": 3, "mastery_level": 2,
            "rhythm_mode": "manual", "manual_daily_minutes": 50,
            "allowed_weekdays": list(range(7)), **values,
        })

    def topic(self, study, name="Vetores"):
        return self.post(f"/api/studies/{study['id']}/topics", {"name": name})

    def availability(self):
        for weekday in range(7):
            self.post("/api/availability", {"weekday": weekday, "start_time": "08:00", "end_time": "12:00"})

    def test_manual_daily_target_is_a_hard_daily_cap_and_default_block_does_not_multiply_it(self):
        study = self.study(preferred_block_minutes=50)
        self.topic(study)
        self.availability()
        preview = self.post("/api/planning/preview", {
            "start": "2026-09-21", "days": 3, "selected_study_ids": [study["id"]],
            "intents": [{"type": "distribute_remaining"}],
        })
        by_day = {}
        for item in preview["sessions"]:
            by_day[item["scheduled_date"]] = by_day.get(item["scheduled_date"], 0) + item["planned_duration_minutes"]
        self.assertEqual(by_day, {"2026-09-21": 50, "2026-09-22": 50, "2026-09-23": 50})
        self.assertTrue(all(item["planned_duration_minutes"] == 50 for item in preview["sessions"]))

    def test_preview_persists_only_a_draft_and_apply_is_idempotent(self):
        study = self.study()
        self.topic(study)
        self.availability()
        preview = self.post("/api/planning/preview", {
            "start": "2026-09-21", "days": 3, "selected_study_ids": [study["id"]],
            "intents": [{"type": "distribute_remaining"}],
        })
        self.assertEqual(self.client.get("/api/planned?start=2026-09-21&end=2026-09-23").get_json(), [])
        draft = self.client.get(f"/api/planning/drafts/{preview['preview_token']}").get_json()
        self.assertEqual(draft["status"], "draft")
        payload = {"preview_token": preview["preview_token"], "idempotency_key": "interactive-apply"}
        first = self.post("/api/planning/apply-versioned", payload)
        second = self.post("/api/planning/apply-versioned", payload)
        self.assertEqual(len(first["created"]), 3)
        self.assertTrue(second["idempotent"])
        self.assertEqual([row["id"] for row in first["created"]], [row["id"] for row in second["created"]])

    def test_manual_choices_and_automatic_remainder_coexist(self):
        study = self.study(required_study_minutes=300, manual_daily_minutes=None, rhythm_mode="suggested")
        self.topic(study)
        self.availability()
        preview = self.post("/api/planning/preview", {
            "start": "2026-09-21", "days": 3, "selected_study_ids": [study["id"]],
            "intents": [
                {"type": "subject_day", "study_subject_id": study["id"], "date": "2026-09-21", "minutes": 120},
                {"type": "subject_day", "study_subject_id": study["id"], "date": "2026-09-22", "minutes": 120},
                {"type": "distribute_remaining"},
            ],
        })
        by_day = {row["scheduled_date"]: row for row in preview["sessions"]}
        self.assertEqual(by_day["2026-09-21"]["planned_duration_minutes"], 120)
        self.assertEqual(by_day["2026-09-21"]["source"], "manual")
        self.assertEqual(by_day["2026-09-22"]["planned_duration_minutes"], 120)
        self.assertEqual(by_day["2026-09-23"]["planned_duration_minutes"], 60)

    def test_automatic_requires_deadline_and_topic_but_manual_draft_remains_available(self):
        study = self.study(target_date=None)
        self.availability()
        automatic = self.post("/api/planning/preview", {
            "start": "2026-09-21", "days": 1, "selected_study_ids": [study["id"]],
            "intents": [{"type": "distribute_remaining"}],
        })
        self.assertFalse(automatic["sessions"])
        self.assertEqual({row["code"] for row in automatic["blockers"]}, {"deadline_required", "topic_required"})
        manual = self.post("/api/planning/preview", {
            "start": "2026-09-21", "days": 1, "selected_study_ids": [study["id"]],
            "intents": [{"type": "subject_day", "study_subject_id": study["id"], "date": "2026-09-21", "minutes": 30}],
        })
        self.assertEqual(manual["totals"]["manual_minutes"], 30)

    def test_discarded_draft_does_not_modify_calendar(self):
        study = self.study()
        self.topic(study)
        self.availability()
        preview = self.post("/api/planning/preview", {
            "start": "2026-09-21", "days": 1, "selected_study_ids": [study["id"]],
            "intents": [{"type": "distribute_remaining"}],
        })
        discarded = self.post(f"/api/planning/drafts/{preview['preview_token']}/discard")
        self.assertEqual(discarded["status"], "discarded")
        self.assertEqual(self.client.get("/api/planned?start=2026-09-21&end=2026-09-21").get_json(), [])

    def test_real_session_is_linked_to_active_objective_and_reduces_only_that_cycle(self):
        study = self.study()
        topic = self.topic(study)
        objective = self.client.get(f"/api/studies/{study['id']}/objectives").get_json()[0]
        session = self.post("/api/sessions", {
            "study_subject_id": study["id"], "topic_id": topic["id"], "date": "2026-09-21",
            "duration_seconds": 1800, "entry_method": "manual",
        })
        self.assertEqual(session["objective_id"], objective["id"])

    def test_daily_result_accepts_multiple_reasons_and_reclassifies_unrealized_plan_once(self):
        study = self.study()
        topic = self.topic(study)
        planned = self.post("/api/planned", {
            "study_subject_id": study["id"], "topic_id": topic["id"],
            "scheduled_date": "2026-09-21", "start_time": "08:00", "planned_duration_minutes": 50,
        })
        saved = self.client.put("/api/daily-results/2026-09-21", json={
            "status": "not_completed", "reasons": ["fatigue", "unexpected"], "comment": "Dia difícil",
        })
        self.assertEqual(saved.status_code, 200, saved.get_json())
        self.assertEqual(set(saved.get_json()["reasons"]), {"fatigue", "unexpected"})
        self.assertEqual(self.client.get(f"/api/planned/{planned['id']}").get_json()["status"], "skipped")

    def test_closing_objective_can_release_manual_blocks_and_new_cycle_starts_clean(self):
        study = self.study()
        topic = self.topic(study)
        objective = self.client.get(f"/api/studies/{study['id']}/objectives").get_json()[0]
        self.post("/api/sessions", {
            "study_subject_id": study["id"], "topic_id": topic["id"], "objective_id": objective["id"],
            "date": "2026-09-21", "duration_seconds": 1800, "entry_method": "manual",
        })
        planned = self.post("/api/planned", {
            "study_subject_id": study["id"], "topic_id": topic["id"], "objective_id": objective["id"],
            "scheduled_date": "2026-09-22", "start_time": "08:00", "planned_duration_minutes": 50,
        })
        closed = self.post(f"/api/objectives/{objective['id']}/close", {"future_blocks_action": "redistribute"})
        self.assertEqual(closed["released_minutes"], 50)
        self.assertEqual(closed["next_action"], "redistribute")
        self.assertEqual(self.client.get(f"/api/planned/{planned['id']}").get_json()["status"], "cancelled")

        cycle = self.post(f"/api/studies/{study['id']}/objectives", {
            "objective_type": "review", "start_date": "2026-09-22", "deadline_date": "2026-09-23",
            "budget_minutes": 60, "budget_origin": "user",
        })
        self.assertEqual(cycle["cycle_number"], 2)
        self.availability()
        preview = self.post("/api/planning/preview", {
            "start": "2026-09-22", "days": 2, "selected_study_ids": [study["id"]],
            "intents": [{"type": "distribute_remaining"}],
        })
        ledger = preview["objectives"][0]
        self.assertEqual(ledger["objective_id"], cycle["id"])
        self.assertEqual(ledger["realized_seconds"], 0)
        self.assertEqual(ledger["remaining_minutes"], 60)

    def test_analytics_exposes_daily_reason_coverage_and_budget_history(self):
        study = self.study()
        self.topic(study)
        response = self.client.put("/api/daily-results/2026-09-21", json={
            "status": "not_completed", "reasons": ["fatigue", "plan_problem"],
        })
        self.assertEqual(response.status_code, 200, response.get_json())
        result = self.client.get("/api/analytics/detailed?start=2026-09-21&end=2026-09-21").get_json()
        self.assertEqual(result["daily_result_analysis"]["answered_days"], 1)
        self.assertEqual(result["daily_result_analysis"]["coverage_percent"], 100.0)
        self.assertEqual(result["daily_result_analysis"]["reason_day_counts"]["fatigue"], 1)
        self.assertTrue(any(row["study_subject_id"] == study["id"] for row in result["budget_history"]))


if __name__ == "__main__":
    unittest.main()
