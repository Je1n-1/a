import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from flask import Flask

from database import connection
from database.migrations import migrate
from routes.api import api
from services import smart_planning
from services.core import _collective_planning_risk, _effective_block_preference


class PlanningDistributionRegressionTest(unittest.TestCase):
    def _deadline_item(self, *, item_id=1, demand=600, preferred=60, days=6, deferred=0):
        start = date(2026, 9, 1)
        return {
            "id": item_id,
            "study_subject_id": item_id,
            "name": f"Disciplina {item_id}",
            "kind": "curriculum",
            "is_schedulable": True,
            "required_study_minutes": demand + deferred,
            "remaining_minutes": demand + deferred,
            "unallocated_minutes": demand + deferred,
            "demand_in_period_minutes": demand,
            "deferred_beyond_preview_minutes": deferred,
            "available_days_until_deadline": days,
            "available_days_in_period": days,
            "effective_start_date": start.isoformat(),
            "deadline_date": (start + timedelta(days=days - 1)).isoformat(),
            "priority_base": 3,
            "preferred_block_minutes": preferred,
            "contents": [],
        }

    def _minutes_by_day(self, sessions):
        values = {}
        for session in sessions:
            values[session["scheduled_date"]] = values.get(session["scheduled_date"], 0) + session["planned_duration_minutes"]
        return values

    def test_deadline_total_is_exact_and_evenly_spread_over_equal_days(self):
        start = date(2026, 9, 1)
        end = start + timedelta(days=5)
        windows = {(start + timedelta(days=offset)).isoformat(): [(8 * 60, 13 * 60)] for offset in range(6)}

        result = smart_planning.distribute([self._deadline_item()], windows, start, end)

        self.assertEqual(sum(item["planned_duration_minutes"] for item in result["sessions"]), 600)
        self.assertEqual(list(self._minutes_by_day(result["sessions"]).values()), [100] * 6)
        self.assertEqual(result["unscheduled"], [])

    def test_short_preview_defers_future_demand_without_reporting_capacity_shortage(self):
        start = date(2026, 9, 1)
        end = start + timedelta(days=6)
        windows = {(start + timedelta(days=offset)).isoformat(): [(8 * 60, 9 * 60)] for offset in range(7)}
        item = self._deadline_item(demand=420, preferred=60, days=42, deferred=2100)
        item["deadline_date"] = (start + timedelta(days=41)).isoformat()
        item["available_days_until_deadline"] = 42

        result = smart_planning.distribute([item], windows, start, end)

        self.assertEqual(sum(entry["planned_duration_minutes"] for entry in result["sessions"]), 420)
        self.assertEqual(result["unscheduled"], [])
        allocated = result["items"][0]
        self.assertEqual(allocated["scheduled_in_preview_minutes"], 420)
        self.assertEqual(allocated["deferred_beyond_preview_minutes"], 2100)
        self.assertEqual(allocated["unallocated_due_to_capacity_minutes"], 0)

    def test_subject_block_preference_is_used_without_changing_other_subjects(self):
        start = date(2026, 9, 1)
        items = [
            self._deadline_item(item_id=1, demand=90, preferred=90, days=1),
            self._deadline_item(item_id=2, demand=60, preferred=60, days=1),
            self._deadline_item(item_id=3, demand=30, preferred=30, days=1),
        ]
        for item in items:
            item["deadline_date"] = start.isoformat()
        result = smart_planning.distribute(items, {start.isoformat(): [(8 * 60, 13 * 60)]}, start, start)

        by_subject = {}
        for session in result["sessions"]:
            by_subject.setdefault(session["study_subject_id"], []).append(session["planned_duration_minutes"])
        self.assertEqual(by_subject[1], [90])
        self.assertEqual(by_subject[2], [60])
        self.assertEqual(by_subject[3], [30])

    def test_daily_targets_waterfill_low_capacity_days_without_losing_minutes(self):
        targets = smart_planning.build_daily_targets(
            600,
            {
                "2026-09-01": 50,
                "2026-09-02": 300,
                "2026-09-03": 300,
                "2026-09-04": 300,
                "2026-09-05": 300,
                "2026-09-06": 300,
            },
        )
        self.assertEqual(sum(targets.values()), 600)
        self.assertEqual(targets["2026-09-01"], 50)
        other_days = [targets[key] for key in sorted(targets) if key != "2026-09-01"]
        self.assertLessEqual(max(other_days) - min(other_days), 1)

    def test_collective_risk_uses_only_the_requested_period(self):
        result = _collective_planning_risk(
            [{"id": 1, "is_schedulable": True, "demand_in_period_minutes": 120, "deadline_date": "2026-09-01"}],
            [
                {"date": "2026-09-01", "net_free_minutes": 60},
                {"date": "2026-10-01", "net_free_minutes": 10000},
            ],
            date(2026, 9, 1),
            date(2026, 9, 1),
        )
        self.assertEqual(result["capacity_minutes"], 60)
        self.assertEqual(result["deficit_minutes"], 60)
        self.assertEqual(result["status"], "impossible")

    def test_current_study_preference_has_precedence_over_curriculum_and_global(self):
        self.assertEqual(_effective_block_preference(
            {"preferred_block_minutes": 60, "curriculum_preferred_block_minutes": 90}, 1, 50,
        ), (60, "current_study"))
        self.assertEqual(_effective_block_preference(
            {"preferred_block_minutes": None, "curriculum_preferred_block_minutes": 90}, 1, 50,
        ), (90, "curriculum"))
        self.assertEqual(_effective_block_preference(
            {"preferred_block_minutes": None, "curriculum_preferred_block_minutes": None}, 1, 50,
        ), (50, "global_default"))


class PlanningPreviewApiRegressionTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / "planning-preview.db"
        self.original_database_path = connection.DATABASE_PATH
        connection.DATABASE_PATH = self.database
        migrate(self.database)
        app = Flask(__name__)
        app.config["TESTING"] = True
        app.register_blueprint(api)
        self.client = app.test_client()
        self.clock = patch("services.core._local_now", return_value=datetime(2026, 9, 1, 6, 0, 0))
        self.clock.start()

    def tearDown(self):
        self.clock.stop()
        connection.DATABASE_PATH = self.original_database_path
        self.temp.cleanup()

    def test_preview_reports_deferred_future_demand_separately_from_capacity_shortage(self):
        formation = self.client.post("/api/formations", json={"name": "Engenharia"}).get_json()
        curriculum = self.client.post(f"/api/formations/{formation['id']}/curriculum", json={
            "name": "Circuitos", "academic_status": "available", "required_study_minutes": 42 * 60,
            "deadline_date": "2026-10-12", "preferred_block_minutes": 60,
        }).get_json()
        study = self.client.post(f"/api/curriculum/{curriculum['id']}/add-study", json={}).get_json()
        for weekday in range(7):
            response = self.client.post("/api/availability", json={
                "weekday": weekday, "start_time": "07:00", "end_time": "08:00",
            })
            self.assertEqual(response.status_code, 200, response.get_json())

        preview = self.client.post("/api/planning/generate", json={"start": "2026-09-01", "days": 7})
        self.assertEqual(preview.status_code, 200, preview.get_json())
        data = preview.get_json()
        item = next(value for value in data["items"] if value["study_subject_id"] == study["id"])
        self.assertEqual(sum(value["planned_duration_minutes"] for value in data["sessions"]), 420)
        self.assertEqual(item["demand_mode"], "deadline_total")
        self.assertEqual(item["scheduled_in_preview_minutes"], 420)
        self.assertEqual(item["deferred_beyond_preview_minutes"], 2100)
        self.assertEqual(item["unallocated_due_to_capacity_minutes"], 0)
        self.assertEqual(item["effective_block_minutes"], 60)
        self.assertEqual(data["allocation"], {
            "scheduled_in_preview_minutes": 420,
            "deferred_beyond_preview_minutes": 2100,
            "unallocated_due_to_capacity_minutes": 0,
        })
        self.assertEqual(data["unscheduled"], [])

    def test_block_duration_is_validated_at_the_api_boundary(self):
        too_short = self.client.post("/api/studies", json={
            "personal_name": "SQL", "weekly_goal_minutes": 60, "preferred_block_minutes": 14,
        })
        self.assertEqual(too_short.status_code, 400, too_short.get_json())
        too_long = self.client.post("/api/studies", json={
            "personal_name": "Python", "weekly_goal_minutes": 60, "preferred_block_minutes": 241,
        })
        self.assertEqual(too_long.status_code, 400, too_long.get_json())
        accepted = self.client.post("/api/studies", json={
            "personal_name": "Git", "weekly_goal_minutes": 60, "preferred_block_minutes": 90,
        })
        self.assertEqual(accepted.status_code, 200, accepted.get_json())
        self.assertEqual(accepted.get_json()["preferred_block_minutes"], 90)


if __name__ == "__main__":
    unittest.main()
