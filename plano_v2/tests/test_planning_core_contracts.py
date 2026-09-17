"""Contratos do núcleo de planejamento introduzidos após a base legada.

Os casos usam um SQLite temporário.  Em particular, eles não abrem nem
executam migrations sobre ``instance/plano.db``.
"""
from __future__ import annotations

import tempfile
import unittest
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from flask import Flask

from database import connection
from database.migrations import migrate
from routes.api import api


class PlanningCoreContractsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / "planning-core.db"
        self.original_database_path = connection.DATABASE_PATH
        connection.DATABASE_PATH = self.database
        migrate(self.database)
        app = Flask(__name__)
        app.config["TESTING"] = True
        app.register_blueprint(api)
        self.client = app.test_client()
        self.clock = patch("services.core._local_now", return_value=datetime(2026, 9, 1, 6, 30, 0))
        self.clock.start()

    def tearDown(self):
        self.clock.stop()
        connection.DATABASE_PATH = self.original_database_path
        self.temp.cleanup()

    def formation(self, name="Engenharia"):
        response = self.client.post("/api/formations", json={"name": name})
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()

    def curriculum(self, formation, name="Disciplina", **values):
        response = self.client.post(
            f"/api/formations/{formation['id']}/curriculum",
            json={"name": name, "academic_status": "available", **values},
        )
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()

    def start(self, subject, **values):
        response = self.client.post(f"/api/curriculum/{subject['id']}/start", json=values)
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()

    def availability(self, weekday, start_time, end_time):
        response = self.client.post(
            "/api/availability",
            json={"weekday": weekday, "start_time": start_time, "end_time": end_time},
        )
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()

    def test_start_not_available_is_atomic_and_returns_normalized_planning_item(self):
        formation = self.formation()
        subject = self.curriculum(
            formation,
            "Sistemas Operacionais",
            academic_status="not_available",
            workload_minutes=1800,
        )

        result = self.start(subject, start_date="2026-09-01")

        self.assertTrue(result["created"])
        self.assertEqual(result["curriculum"]["academic_status"], "in_progress")
        self.assertEqual(result["study"]["status"], "active")
        self.assertTrue(result["profile"]["effort_is_provisional"])
        self.assertTrue(result["profile"]["deadline_is_provisional"])
        self.assertEqual(result["planning_item"]["canonical_subject_key"], f"curriculum:{subject['id']}")
        self.assertEqual(result["planning_item"]["current_study_id"], result["study"]["id"])
        self.assertEqual(result["planning_item"]["academic_status"], "in_progress")
        self.assertEqual(result["planning_item"]["personal_effort_minutes"], 1800)
        self.assertIn("topics", result["planning_item"])
        self.assertIn("planning_blockers", result["planning_item"])

        invalid = self.curriculum(formation, "Disciplina com rollback", academic_status="not_available")
        rejected = self.client.post(
            f"/api/curriculum/{invalid['id']}/start",
            json={"first_topic_id": 999999},
        )
        self.assertEqual(rejected.status_code, 404, rejected.get_json())
        restored = self.client.get(f"/api/curriculum/{invalid['id']}")
        self.assertEqual(restored.status_code, 200, restored.get_json())
        self.assertEqual(restored.get_json()["curriculum"]["academic_status"], "not_available")
        studies = self.client.get("/api/studies").get_json()
        self.assertFalse(any(row.get("curriculum_subject_id") == invalid["id"] for row in studies))

    def test_date_interval_resolves_capacity_after_pauses_and_reset_is_scoped(self):
        created = self.client.post(
            "/api/availability/intervals",
            json={
                "start_date": "2026-09-02", "end_date": "2026-09-02",
                "kind": "replace", "start_time": "14:00", "end_time": "17:30",
            },
        )
        self.assertEqual(created.status_code, 200, created.get_json())
        rule_id = created.get_json()["id"]

        day = self.client.get("/api/availability/days/2026-09-02")
        self.assertEqual(day.status_code, 200, day.get_json())
        self.assertEqual(day.get_json()["windows"], [[14 * 60, 17 * 60 + 30]])
        self.assertFalse(day.get_json()["uses_weekly_default"])

        capacity = self.client.get("/api/planning/capacity?start=2026-09-02&end=2026-09-02")
        self.assertEqual(capacity.status_code, 200, capacity.get_json())
        payload = capacity.get_json()
        self.assertEqual(payload["gross_capacity_minutes"], 210)
        self.assertEqual(payload["net_free_minutes"], 180)
        self.assertEqual(payload["capacity_by_day"][0]["break_minutes"], 10)

        blackout = self.client.post(
            "/api/availability/intervals",
            json={
                "start_date": "2026-09-02", "end_date": "2026-09-02",
                "kind": "unavailable", "all_day": True,
            },
        )
        self.assertEqual(blackout.status_code, 200, blackout.get_json())
        self.assertEqual(self.client.get("/api/availability/days/2026-09-02").get_json()["windows"], [])

        reset = self.client.post("/api/availability/days/2026-09-02/reset")
        self.assertEqual(reset.status_code, 200, reset.get_json())
        self.assertEqual(reset.get_json()["removed_exceptions"], 2)
        self.assertTrue(reset.get_json()["weekly_restored"])
        remaining_rules = self.client.get("/api/availability/intervals")
        self.assertEqual(remaining_rules.status_code, 200, remaining_rules.get_json())
        self.assertFalse(any(rule["id"] == rule_id for rule in remaining_rules.get_json()))

    def test_shared_risk_counts_the_calendar_once(self):
        formation = self.formation()
        first = self.curriculum(formation, "Circuitos", required_study_minutes=150, deadline_date="2026-09-01")
        second = self.curriculum(formation, "Cálculo", required_study_minutes=150, deadline_date="2026-09-01")
        self.start(first)
        self.start(second)
        self.availability(1, "07:00", "10:30")

        response = self.client.get("/api/planning/capacity?start=2026-09-01&end=2026-09-01")
        self.assertEqual(response.status_code, 200, response.get_json())
        joint = response.get_json()["joint_risk"]
        self.assertEqual(joint["demand_minutes"], 300)
        self.assertEqual(joint["capacity_minutes"], 180)
        self.assertEqual(joint["deficit_minutes"], 120)
        self.assertEqual(joint["status"], "impossible")
        self.assertEqual(len(joint["at_risk_item_ids"]), 2)

    def test_long_deadline_effort_is_paced_even_when_each_day_has_excess_capacity(self):
        subject = self.curriculum(
            self.formation(),
            "Algoritmos",
            required_study_minutes=42 * 60,
            deadline_date="2026-10-12",
            preferred_block_minutes=60,
        )
        self.start(subject)
        for weekday in range(7):
            self.availability(weekday, "07:00", "15:00")

        preview = self.client.post("/api/planning/generate-smart", json={"start": "2026-09-01", "days": 42})
        self.assertEqual(preview.status_code, 200, preview.get_json())
        sessions = preview.get_json()["sessions"]
        by_day = defaultdict(int)
        for session in sessions:
            by_day[session["scheduled_date"]] += session["planned_duration_minutes"]
        self.assertEqual(len(by_day), 42)
        self.assertEqual(set(by_day.values()), {60})

    def test_past_unrealized_block_is_not_treated_as_future_coverage_and_auto_block_can_be_fixed(self):
        created = self.client.post(
            "/api/studies",
            json={"personal_name": "Estudo paralelo", "required_study_minutes": 120, "target_date": "2026-09-10"},
        )
        self.assertEqual(created.status_code, 200, created.get_json())
        study = created.get_json()
        past = self.client.post(
            "/api/planned",
            json={
                "study_subject_id": study["id"], "scheduled_date": "2026-08-31",
                "start_time": "08:00", "planned_duration_minutes": 50,
            },
        )
        self.assertEqual(past.status_code, 200, past.get_json())

        items = self.client.get("/api/planning/items?start=2026-09-01&end=2026-09-07")
        self.assertEqual(items.status_code, 200, items.get_json())
        item = next(row for row in items.get_json()["items"] if row["id"] == study["id"])
        self.assertEqual(item["time_future_planned_minutes"], 0)
        self.assertEqual(item["time_unallocated_minutes"], 120)
        capacity = self.client.get("/api/planning/capacity?start=2026-08-31&end=2026-09-01")
        self.assertEqual(capacity.status_code, 200, capacity.get_json())
        self.assertEqual(capacity.get_json()["past_unrealized_minutes"], 50)

        auto = self.client.post(
            "/api/planning/apply",
            json={"sessions": [{
                "study_subject_id": study["id"], "scheduled_date": "2026-09-02",
                "start_time": "08:00", "planned_duration_minutes": 50,
                "selection_reason": "proposta automática",
            }]},
        )
        self.assertEqual(auto.status_code, 200, auto.get_json())
        automatic = auto.get_json()["created"][0]
        fixed = self.client.patch(f"/api/planned/{automatic['id']}", json={"source": "manual"})
        self.assertEqual(fixed.status_code, 200, fixed.get_json())
        self.assertEqual(fixed.get_json()["id"], automatic["id"])
        self.assertEqual(fixed.get_json()["source"], "manual")
        reversed_source = self.client.patch(f"/api/planned/{automatic['id']}", json={"source": "automatic"})
        self.assertEqual(reversed_source.status_code, 400, reversed_source.get_json())
        self.assertEqual(reversed_source.get_json()["code"], "planned_source_invalid")

        restored = self.client.patch(
            f"/api/planned/{automatic['id']}",
            json={"source": "automatic", "restore_automatic_source": True},
        )
        self.assertEqual(restored.status_code, 200, restored.get_json())
        self.assertEqual(restored.get_json()["source"], "automatic")


if __name__ == "__main__":
    unittest.main()
