import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from flask import Flask

from database import connection
from database.migrations import migrate
from routes.api import api


class SmartPlanningApiTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / "plano-smart.db"
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

    def formation(self, name="Formação teste"):
        response = self.client.post("/api/formations", json={"name": name})
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()

    def curriculum(self, formation, name="Cálculo I", **values):
        response = self.client.post(f"/api/formations/{formation['id']}/curriculum", json={
            "name": name, "academic_status": "available", **values,
        })
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()

    def activate(self, curriculum):
        response = self.client.post(f"/api/curriculum/{curriculum['id']}/add-study", json={})
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()

    def availability(self, weekday, start, end):
        response = self.client.post("/api/availability", json={"weekday": weekday, "start_time": start, "end_time": end})
        self.assertEqual(response.status_code, 200, response.get_json())

    def preview(self, start="2026-09-01", days=7):
        response = self.client.post("/api/planning/generate", json={"start": start, "days": days})
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()

    def monday_key(self, value):
        current = date.fromisoformat(value)
        return (current - timedelta(days=current.weekday())).isoformat()

    def set_now(self, value):
        self.clock.stop()
        self.clock = patch("services.core._local_now", return_value=value)
        self.clock.start()

    def test_curriculum_schedule_settings_keep_institutional_workload_separate_from_effort(self):
        formation = self.formation()
        subject = self.curriculum(
            formation, workload_minutes=3600, required_study_minutes=2400,
            start_date="2026-09-01", end_date="2026-12-01", deadline_date="2026-11-20",
            priority_base=5, preferred_block_minutes=75, allowed_weekdays=[0, 2, 4], minimum_grade=6,
        )
        settings = self.client.get(f"/api/curriculum/{subject['id']}/schedule-settings")
        self.assertEqual(settings.status_code, 200, settings.get_json())
        data = settings.get_json()["settings"]
        self.assertEqual(data["workload_minutes"], 3600)
        self.assertEqual(data["required_study_minutes"], 2400)
        self.assertEqual(data["deadline_date"], "2026-11-20")
        self.assertEqual(data["allowed_weekdays"], "[0,2,4]")
        invalid = self.client.patch(f"/api/curriculum/{subject['id']}", json={"start_date": "2026-12-01", "deadline_date": "2026-11-20"})
        self.assertEqual(invalid.status_code, 400, invalid.get_json())
        cleared = self.client.patch(f"/api/curriculum/{subject['id']}", json={
            "deadline_date": None, "required_study_minutes": None,
            "preferred_block_minutes": None, "allowed_weekdays": None, "minimum_grade": None,
        })
        self.assertEqual(cleared.status_code, 200, cleared.get_json())
        saved = self.client.get(f"/api/curriculum/{subject['id']}/schedule-settings").get_json()["settings"]
        self.assertIsNone(saved["deadline_date"])
        self.assertIsNone(saved["required_study_minutes"])
        self.assertIsNone(saved["preferred_block_minutes"])
        self.assertIsNone(saved["allowed_weekdays"])
        self.assertIsNone(saved["minimum_grade"])

    def test_content_and_evaluation_can_exist_before_current_study(self):
        subject = self.curriculum(self.formation(), start_date="2026-09-01", end_date="2026-10-01")
        content = self.client.post(f"/api/curriculum/{subject['id']}/contents", json={
            "name": "Limites laterais", "unit": "Unidade 1", "estimated_minutes": 90, "difficulty": 4,
        })
        self.assertEqual(content.status_code, 200, content.get_json())
        self.assertIsNone(content.get_json()["study_subject_id"])
        evaluation = self.client.post(f"/api/curriculum/{subject['id']}/evaluations", json={
            "title": "Prova 1", "type": "exam", "date": "2026-09-20", "weight": 2,
            "max_score": 10, "score": 8, "topic_ids": [content.get_json()["id"]],
        })
        self.assertEqual(evaluation.status_code, 200, evaluation.get_json())
        detail = self.client.get(f"/api/curriculum/{subject['id']}")
        self.assertEqual(detail.status_code, 200, detail.get_json())
        self.assertEqual(detail.get_json()["content_progress"]["total"], 1)
        self.assertEqual(detail.get_json()["evaluations"]["simple_average_percent"], 80.0)
        self.assertEqual(detail.get_json()["evaluations"]["weighted_average_percent"], 80.0)

    def test_planned_time_does_not_reduce_effort_but_real_session_does(self):
        subject = self.curriculum(self.formation(), required_study_minutes=120, deadline_date="2026-09-30")
        study = self.activate(subject)
        content = self.client.post(f"/api/curriculum/{subject['id']}/contents", json={"name": "Derivadas"}).get_json()
        block = self.client.post("/api/planned", json={
            "study_subject_id": study["id"], "topic_id": content["id"], "scheduled_date": "2026-09-02",
            "start_time": "07:00", "planned_duration_minutes": 30,
        })
        self.assertEqual(block.status_code, 200, block.get_json())
        before = self.client.get(f"/api/curriculum/{subject['id']}/schedule-settings").get_json()["effort"]
        self.assertEqual(before["real_minutes"], 0)
        self.assertEqual(before["remaining_minutes"], 120)
        self.assertEqual(before["future_planned_minutes"], 30)
        self.assertEqual(before["unallocated_minutes"], 90)
        session = self.client.post("/api/sessions", json={
            "study_subject_id": study["id"], "topic_id": content["id"], "date": "2026-09-01",
            "duration_seconds": 1800, "entry_method": "manual",
        })
        self.assertEqual(session.status_code, 200, session.get_json())
        after = self.client.get(f"/api/curriculum/{subject['id']}/schedule-settings").get_json()["effort"]
        self.assertEqual(after["real_minutes"], 30)
        self.assertEqual(after["remaining_minutes"], 90)

    def test_smart_generation_spreads_42_hours_across_available_days(self):
        formation = self.formation()
        subject = self.curriculum(
            formation, required_study_minutes=42 * 60, deadline_date="2026-10-12",
            preferred_block_minutes=60, priority_base=5,
        )
        self.activate(subject)
        for weekday in range(7): self.availability(weekday, "07:00", "08:00")
        preview = self.client.post("/api/planning/generate-smart", json={"start": "2026-09-01", "days": 42})
        self.assertEqual(preview.status_code, 200, preview.get_json())
        sessions = preview.get_json()["sessions"]
        self.assertGreater(len(sessions), 20)
        self.assertGreater(len({item["scheduled_date"] for item in sessions}), 20)
        self.assertEqual(sessions[0]["scheduled_date"], "2026-09-01")
        self.assertNotEqual(sessions[-1]["scheduled_date"], "2026-09-01")

    def test_multiple_windows_never_place_a_block_in_the_interval(self):
        subject = self.curriculum(self.formation(), required_study_minutes=360, deadline_date="2026-09-01", preferred_block_minutes=50)
        self.activate(subject)
        self.availability(1, "07:00", "12:00")
        self.availability(1, "13:30", "15:00")
        preview = self.client.post("/api/planning/generate-smart", json={"start": "2026-09-01", "days": 1})
        self.assertEqual(preview.status_code, 200, preview.get_json())
        self.assertTrue(preview.get_json()["sessions"])
        for item in preview.get_json()["sessions"]:
            start = int(item["start_time"][:2]) * 60 + int(item["start_time"][3:])
            self.assertFalse(12 * 60 <= start < 13 * 60 + 30)
            self.assertFalse(start < 12 * 60 and start + item["planned_duration_minutes"] > 12 * 60)

    def test_not_available_is_future_not_demand_and_parallel_minimum_is_allocated(self):
        formation = self.formation()
        future = self.curriculum(formation, "Matéria futura", academic_status="not_available", required_study_minutes=900, deadline_date="2026-09-10")
        parallel = self.client.post("/api/studies", json={
            "personal_name": "Programação", "minimum_weekly_minutes": 60, "weekly_goal_minutes": 90,
            "priority": 1,
        })
        self.assertEqual(parallel.status_code, 200, parallel.get_json())
        self.availability(1, "07:00", "09:00")
        preview = self.client.post("/api/planning/generate-smart", json={"start": "2026-09-01", "days": 1})
        self.assertEqual(preview.status_code, 200, preview.get_json())
        sessions = preview.get_json()["sessions"]
        self.assertTrue(any(item["study_subject_id"] == parallel.get_json()["id"] for item in sessions))
        self.assertFalse(any(item["subject_name"] == future["name"] for item in sessions))
        ideal = self.client.get("/api/planning/ideal?start=2026-09-01&end=2026-09-07")
        self.assertEqual(ideal.status_code, 200, ideal.get_json())
        self.assertIn(future["id"], {item["id"] for item in ideal.get_json()["future_subjects"]})

    def test_preview_diagnostics_explain_missing_current_study_and_future_subject(self):
        formation = self.formation()
        missing = self.curriculum(
            formation, "Sistemas Operacionais", academic_status="in_progress",
            required_study_minutes=180, deadline_date="2026-09-12",
        )
        future = self.curriculum(formation, "Tópicos Avançados", academic_status="not_available", start_date="2026-10-01")
        self.availability(1, "07:00", "09:00")
        preview = self.preview(days=7)
        diagnostics = preview["diagnostics"]
        by_curriculum = {item["curriculum_subject_id"]: item for item in diagnostics["items"]}
        self.assertEqual(by_curriculum[missing["id"]]["reason_codes"], ["current_study_missing"])
        self.assertEqual(by_curriculum[future["id"]]["state"], "future")
        self.assertEqual(by_curriculum[future["id"]]["reason_codes"], ["not_available_future"])
        self.assertEqual(diagnostics["summary"]["eligible"], 0)
        self.assertEqual(diagnostics["summary"]["future"], 1)
        self.assertFalse(preview["sessions"])

    def test_preview_diagnostics_explain_missing_goal_and_future_start(self):
        no_goal = self.client.post("/api/studies", json={"personal_name": "Leitura livre"})
        self.assertEqual(no_goal.status_code, 200, no_goal.get_json())
        subject = self.curriculum(
            self.formation(), "Compiladores", required_study_minutes=120,
            start_date="2026-09-08", deadline_date="2026-09-20", preferred_block_minutes=60,
        )
        study = self.activate(subject)
        self.availability(1, "07:00", "09:00")
        first_week = self.preview(days=7)
        by_study = {item["study_subject_id"]: item for item in first_week["diagnostics"]["items"]}
        self.assertEqual(by_study[no_goal.get_json()["id"]]["reason_codes"], ["missing_effort_or_goal"])
        self.assertEqual(by_study[study["id"]]["reason_codes"], ["starts_after_period"])
        self.assertFalse(first_week["sessions"])
        extended = self.preview(days=14)
        planned = [item for item in extended["sessions"] if item["study_subject_id"] == study["id"]]
        self.assertTrue(planned)
        self.assertTrue(all(item["scheduled_date"] >= "2026-09-08" for item in planned))

    def test_generation_rejects_past_start_and_does_not_create_past_blocks(self):
        response = self.client.post("/api/planning/generate", json={"start": "2026-08-31", "days": 7})
        self.assertEqual(response.status_code, 400, response.get_json())
        self.assertEqual(response.get_json()["code"], "planning_start_in_past")

    def test_paused_formation_is_diagnostic_not_planning_demand(self):
        formation = self.formation()
        subject = self.curriculum(formation, required_study_minutes=120, deadline_date="2026-09-12")
        self.activate(subject)
        paused = self.client.patch(f"/api/formations/{formation['id']}", json={"status": "paused"})
        self.assertEqual(paused.status_code, 200, paused.get_json())
        self.availability(1, "07:00", "09:00")
        preview = self.preview(days=7)
        reasons = {reason for item in preview["diagnostics"]["items"] for reason in item["reason_codes"]}
        self.assertIn("formation_not_active", reasons)
        self.assertEqual(preview["capacity"]["demand_minutes"], 0)
        self.assertFalse(preview["sessions"])

    def test_urgent_curriculum_precedes_parallel_minimum_when_capacity_is_insufficient(self):
        subject = self.curriculum(
            self.formation(), "Eletrônica", required_study_minutes=60,
            deadline_date="2026-09-01", preferred_block_minutes=60, priority_base=5,
        )
        curriculum_study = self.activate(subject)
        parallel = self.client.post("/api/studies", json={
            "personal_name": "Programação", "weekly_goal_minutes": 60,
            "minimum_weekly_minutes": 60, "preferred_block_minutes": 60, "priority": 1,
        })
        self.assertEqual(parallel.status_code, 200, parallel.get_json())
        self.availability(1, "07:00", "08:00")
        preview = self.preview(days=1)
        self.assertEqual(preview["sessions"][0]["study_subject_id"], curriculum_study["id"])
        self.assertFalse(any(item["study_subject_id"] == parallel.get_json()["id"] for item in preview["sessions"]))
        parallel_unmet = next(item for item in preview["unscheduled"] if item["id"] == parallel.get_json()["id"])
        self.assertEqual(parallel_unmet["code"], "minimum_weekly_unmet")

    def test_weekly_goal_is_repeated_over_a_fourteen_day_preview(self):
        study = self.client.post("/api/studies", json={
            "personal_name": "Inglês", "weekly_goal_minutes": 60, "preferred_block_minutes": 60,
        })
        self.assertEqual(study.status_code, 200, study.get_json())
        self.availability(1, "07:00", "08:00")
        preview = self.preview(days=14)
        minutes_by_week = {}
        for session in preview["sessions"]:
            if session["study_subject_id"] == study.get_json()["id"]:
                week = self.monday_key(session["scheduled_date"])
                minutes_by_week[week] = minutes_by_week.get(week, 0) + session["planned_duration_minutes"]
        self.assertEqual(minutes_by_week["2026-08-31"], 60)
        self.assertEqual(minutes_by_week["2026-09-07"], 60)

    def test_fase_b_flow_from_september_7_to_20_preserves_manual_and_today(self):
        self.set_now(datetime(2026, 9, 7, 6, 0, 0))
        preferences = self.client.put("/api/settings", json={
            "default_session_minutes": 60, "planning_break_minutes": 10,
            "minimum_session_minutes": 25, "maximum_session_minutes": 90,
        })
        self.assertEqual(preferences.status_code, 200, preferences.get_json())
        formation = self.formation("Engenharia")
        subject = self.curriculum(
            formation, "Circuitos", academic_status="in_progress", start_date="2026-09-07",
            required_study_minutes=300, deadline_date="2026-09-20", priority_base=5,
            preferred_block_minutes=60,
        )
        curriculum_study = self.activate(subject)
        parallel = self.client.post("/api/studies", json={
            "personal_name": "Programação paralela", "weekly_goal_minutes": 60,
            "minimum_weekly_minutes": 60, "preferred_block_minutes": 60, "priority": 1,
        })
        self.assertEqual(parallel.status_code, 200, parallel.get_json())
        self.availability(0, "07:00", "08:30")
        self.availability(0, "13:00", "14:30")
        for weekday in range(1, 5):
            self.availability(weekday, "07:00", "08:30")
        manual = self.client.post("/api/planned", json={
            "study_subject_id": curriculum_study["id"], "scheduled_date": "2026-09-07",
            "start_time": "07:00", "planned_duration_minutes": 30,
        })
        self.assertEqual(manual.status_code, 200, manual.get_json())

        preview = self.preview(start="2026-09-07", days=14)
        curriculum_sessions = [item for item in preview["sessions"] if item["study_subject_id"] == curriculum_study["id"]]
        self.assertTrue(curriculum_sessions)
        self.assertTrue(all("2026-09-07" <= item["scheduled_date"] <= "2026-09-20" for item in curriculum_sessions))
        self.assertGreaterEqual(len({item["scheduled_date"] for item in curriculum_sessions}), 2)
        self.assertLessEqual(sum(item["planned_duration_minutes"] for item in curriculum_sessions), 300)
        self.assertEqual(preview["sessions"][0]["study_subject_id"], curriculum_study["id"])

        intervals_by_day = {"2026-09-07": [(7 * 60, 7 * 60 + 30)]}
        for item in preview["sessions"]:
            start_minutes = int(item["start_time"][:2]) * 60 + int(item["start_time"][3:])
            intervals_by_day.setdefault(item["scheduled_date"], []).append((start_minutes, start_minutes + item["planned_duration_minutes"]))
        for intervals in intervals_by_day.values():
            intervals.sort()
            self.assertTrue(all(previous[1] <= current[0] for previous, current in zip(intervals, intervals[1:])))

        applied = self.client.post("/api/planning/apply", json={"sessions": preview["sessions"]})
        self.assertEqual(applied.status_code, 200, applied.get_json())
        self.assertTrue(applied.get_json()["created"])
        saved = self.client.get("/api/planned?start=2026-09-07&end=2026-09-20")
        self.assertEqual(saved.status_code, 200, saved.get_json())
        self.assertEqual(next(item for item in saved.get_json() if item["id"] == manual.get_json()["id"])["source"], "manual")
        today = self.client.get("/api/today")
        self.assertEqual(today.status_code, 200, today.get_json())
        self.assertEqual(today.get_json()["studied_minutes"], 0)
        self.assertTrue(any(item["study_subject_id"] == curriculum_study["id"] for item in today.get_json()["agenda"]))

    def test_manual_blocks_are_preserved_and_auto_application_is_idempotent(self):
        study = self.client.post("/api/studies", json={"personal_name": "Banco de Dados", "weekly_goal_minutes": 120}).get_json()
        self.availability(1, "07:00", "10:00")
        manual = self.client.post("/api/planned", json={
            "study_subject_id": study["id"], "scheduled_date": "2026-09-01", "start_time": "07:00", "planned_duration_minutes": 50,
        })
        self.assertEqual(manual.status_code, 200, manual.get_json())
        preview = self.client.post("/api/planning/generate-smart", json={"start": "2026-09-01", "days": 1}).get_json()
        self.assertTrue(preview["sessions"])
        applied = self.client.post("/api/planning/apply", json={"sessions": preview["sessions"]})
        self.assertEqual(applied.status_code, 200, applied.get_json())
        repeated = self.client.post("/api/planning/apply", json={"sessions": preview["sessions"]})
        self.assertEqual(repeated.status_code, 200, repeated.get_json())
        manual_row = self.client.get(f"/api/planned/{manual.get_json()['id']}")
        self.assertEqual(manual_row.status_code, 200, manual_row.get_json())
        self.assertEqual(manual_row.get_json()["source"], "manual")

    def test_overlap_is_rejected(self):
        study = self.client.post("/api/studies", json={"personal_name": "Redes"}).get_json()
        first = self.client.post("/api/planned", json={"study_subject_id": study["id"], "scheduled_date": "2026-09-01", "start_time": "08:00", "planned_duration_minutes": 60})
        self.assertEqual(first.status_code, 200, first.get_json())
        overlap = self.client.post("/api/planned", json={"study_subject_id": study["id"], "scheduled_date": "2026-09-01", "start_time": "08:30", "planned_duration_minutes": 50})
        self.assertEqual(overlap.status_code, 409, overlap.get_json())
        self.assertEqual(overlap.get_json()["code"], "planned_overlap")

    def test_parallel_minimum_is_reserved_again_in_the_next_week(self):
        study = self.client.post("/api/studies", json={
            "personal_name": "Programação", "weekly_goal_minutes": 60,
            "minimum_weekly_minutes": 60, "preferred_block_minutes": 50,
        }).get_json()
        self.availability(1, "07:00", "09:00")  # terça-feira
        preview = self.client.post("/api/planning/generate-smart", json={"start": "2026-09-01", "days": 8})
        self.assertEqual(preview.status_code, 200, preview.get_json())
        minutes_by_week = {}
        for session in preview.get_json()["sessions"]:
            if session["study_subject_id"] != study["id"]:
                continue
            week = session["scheduled_date"] if session["scheduled_date"] == "2026-09-01" else "2026-09-08"
            minutes_by_week[week] = minutes_by_week.get(week, 0) + session["planned_duration_minutes"]
        self.assertGreaterEqual(minutes_by_week.get("2026-09-01", 0), 60)
        self.assertGreaterEqual(minutes_by_week.get("2026-09-08", 0), 60)

    def test_completed_content_is_selected_only_for_an_active_review(self):
        subject = self.curriculum(
            self.formation(), "Sinais", academic_status="completed",
            required_study_minutes=60, deadline_date="2026-09-02",
        )
        content = self.client.post(f"/api/curriculum/{subject['id']}/contents", json={"name": "Transformada", "status": "completed"})
        self.assertEqual(content.status_code, 200, content.get_json())
        review = self.client.post(f"/api/curriculum/{subject['id']}/review", json={"status": "queued", "start_study": True})
        self.assertEqual(review.status_code, 200, review.get_json())
        self.availability(1, "07:00", "09:00")
        preview = self.client.post("/api/planning/generate-smart", json={"start": "2026-09-01", "days": 1})
        self.assertEqual(preview.status_code, 200, preview.get_json())
        planned = [item for item in preview.get_json()["sessions"] if item["subject_name"] == "Sinais"]
        self.assertTrue(planned)
        self.assertEqual(planned[0]["topic_id"], content.get_json()["id"])

    def test_direct_content_remains_the_same_source_after_activation(self):
        subject = self.curriculum(self.formation(), required_study_minutes=90, deadline_date="2026-09-30")
        content = self.client.post(f"/api/curriculum/{subject['id']}/contents", json={"name": "Vetores", "unit": "Base"}).get_json()
        study = self.activate(subject)
        detail = self.client.get(f"/api/studies/{study['id']}")
        self.assertEqual(detail.status_code, 200, detail.get_json())
        self.assertIn(content["id"], {item["id"] for item in detail.get_json()["contents"]})
        plan = self.client.post("/api/planned", json={
            "study_subject_id": study["id"], "topic_id": content["id"], "scheduled_date": "2026-09-02",
            "start_time": "07:00", "planned_duration_minutes": 45,
        })
        self.assertEqual(plan.status_code, 200, plan.get_json())
        session = self.client.post("/api/sessions", json={
            "study_subject_id": study["id"], "topic_id": content["id"], "date": "2026-09-01",
            "duration_seconds": 900, "entry_method": "manual",
        })
        self.assertEqual(session.status_code, 200, session.get_json())
        history = self.client.get(f"/api/contents/{content['id']}/history")
        self.assertEqual(history.status_code, 200, history.get_json())
        self.assertEqual(len(history.get_json()["sessions"]), 1)

    def test_today_uses_saved_agenda_then_suggests_another_item_in_free_slot(self):
        first = self.client.post("/api/studies", json={"personal_name": "Estruturas", "weekly_goal_minutes": 60}).get_json()
        second = self.client.post("/api/studies", json={"personal_name": "Algoritmos", "weekly_goal_minutes": 50, "priority": 5}).get_json()
        self.availability(1, "07:00", "09:00")
        agenda = self.client.post("/api/planned", json={
            "study_subject_id": first["id"], "scheduled_date": "2026-09-01", "start_time": "07:00", "planned_duration_minutes": 50,
        })
        self.assertEqual(agenda.status_code, 200, agenda.get_json())
        today = self.client.get("/api/today")
        self.assertEqual(today.status_code, 200, today.get_json())
        data = today.get_json()
        self.assertEqual(data["agenda"][0]["study_subject_id"], first["id"])
        self.assertEqual(data["suggestion"]["study_subject"]["id"], second["id"])
        self.assertEqual(data["suggestion"]["slot"]["start_time"], "07:50")

    def test_ideal_exposes_deficit_and_keeps_base_priority_unchanged(self):
        subject = self.curriculum(
            self.formation(), "Eletrônica", required_study_minutes=600,
            deadline_date="2026-09-02", priority_base=5,
        )
        self.activate(subject)
        self.availability(1, "07:00", "08:00")
        ideal = self.client.get("/api/planning/ideal?start=2026-09-01&end=2026-09-02")
        self.assertEqual(ideal.status_code, 200, ideal.get_json())
        item = next(row for row in ideal.get_json()["items"] if row["name"] == "Eletrônica")
        self.assertGreater(item["deficit_minutes"], 0)
        self.assertGreaterEqual(item["priority_effective"], 5)
        self.assertLessEqual(item["priority_effective"], 10)
        saved = self.client.get(f"/api/curriculum/{subject['id']}").get_json()["curriculum"]
        self.assertEqual(saved["priority_base"], 5)

    def test_analytics_is_operational_and_keeps_future_subjects_out_of_demand(self):
        formation = self.formation()
        future = self.curriculum(formation, "Futura", academic_status="not_available", required_study_minutes=500, start_date="2027-01-01")
        subject = self.curriculum(formation, "Cálculo", required_study_minutes=100, deadline_date="2026-09-20")
        content = self.client.post(f"/api/curriculum/{subject['id']}/contents", json={"name": "Integrais"}).get_json()
        evaluation = self.client.post(f"/api/curriculum/{subject['id']}/evaluations", json={
            "title": "Prova", "date": "2026-09-10", "max_score": 10, "score": 8,
            "topic_ids": [content["id"]],
        })
        self.assertEqual(evaluation.status_code, 200, evaluation.get_json())
        analytics = self.client.get("/api/analytics/workload?start=2026-08-26&end=2026-09-01")
        self.assertEqual(analytics.status_code, 200, analytics.get_json())
        data = analytics.get_json()
        self.assertNotIn("academic_progress", data)
        self.assertIn(future["id"], {item["id"] for item in data["ideal"]["future_subjects"]})
        self.assertFalse(any(item["name"] == "Futura" for item in data["ideal"]["items"]))
        self.assertEqual(data["grade_by_subject"][0]["simple_average_percent"], 80.0)

    def test_archived_content_can_be_restored_without_losing_its_identity(self):
        subject = self.curriculum(self.formation())
        content = self.client.post(f"/api/curriculum/{subject['id']}/contents", json={"name": "Matrizes"}).get_json()
        archived = self.client.post(f"/api/contents/{content['id']}/archive")
        self.assertEqual(archived.status_code, 200, archived.get_json())
        visible = self.client.get(f"/api/curriculum/{subject['id']}/contents")
        self.assertFalse(visible.get_json()["contents"])
        all_contents = self.client.get(f"/api/curriculum/{subject['id']}/contents?archived=1")
        self.assertIn(content["id"], {item["id"] for item in all_contents.get_json()["contents"]})
        restored = self.client.post(f"/api/contents/{content['id']}/restore")
        self.assertEqual(restored.status_code, 200, restored.get_json())
        self.assertEqual(restored.get_json()["id"], content["id"])


if __name__ == "__main__":
    unittest.main()
