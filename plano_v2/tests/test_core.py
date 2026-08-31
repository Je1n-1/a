import tempfile
import unittest
from pathlib import Path

from database.connection import connect
from database.migrations import migrate
from services import core


class CoreFlowTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "test.db"
        migrate(self.db)

    def tearDown(self):
        self.temp.cleanup()

    def test_curriculum_study_session_and_reviews(self):
        with connect(self.db) as conn:
            formation = core.create_formation(conn, {"name": "Curso teste"})
            curriculum = core.create_curriculum(conn, formation["id"], {"name": "Matemática", "academic_status": "available"})
            study = core.add_curriculum_study(conn, curriculum["id"], {"weekly_goal_minutes": 120})
            topic = core.create_topic(conn, study["id"], {"name": "Funções"})
            session = core.create_session(conn, {"study_subject_id": study["id"], "topic_id": topic["id"], "duration_seconds": 1800, "mastery_after": 3})
            self.assertEqual(session["duration_seconds"], 1800)
            self.assertEqual(len(core.reviews(conn)), 1)
            first_review = core.reviews(conn)[0]
            self.assertEqual(first_review["review_stage"], "d1")
            core.complete_review(conn, first_review["id"], "good")
            self.assertEqual(core.reviews(conn)[0]["review_stage"], "d7")
            self.assertEqual(core.subject_detail(conn, study["id"])["ungrouped_topics"][0]["mastery"], 3)

    def test_curriculum_cannot_duplicate_and_availability_cannot_overlap(self):
        with connect(self.db) as conn:
            formation = core.create_formation(conn, {"name": "Curso teste"})
            core.create_curriculum(conn, formation["id"], {"name": "Física"})
            with self.assertRaises(core.DomainError): core.create_curriculum(conn, formation["id"], {"name": "física"})
            core.set_availability(conn, {"weekday": 0, "start_time": "19:00", "end_time": "21:00"})
            with self.assertRaises(core.DomainError): core.set_availability(conn, {"weekday": 0, "start_time": "20:00", "end_time": "22:00"})

    def test_plan_respects_available_slots(self):
        with connect(self.db) as conn:
            study = core.create_personal_study(conn, {"personal_name": "Python", "priority": 5, "weekly_goal_minutes": 100})
            core.create_topic(conn, study["id"], {"name": "Funções"})
            today = __import__("datetime").date.today()
            core.set_availability(conn, {"weekday": today.weekday(), "start_time": "19:00", "end_time": "20:40"})
            proposal = core.generate_plan(conn, today.isoformat())
            self.assertEqual(len(proposal["sessions"]), 1)
            self.assertTrue(all(item["study_subject_id"] == study["id"] for item in proposal["sessions"]))

    def test_plan_ignores_subject_without_goal_and_counts_existing_plan(self):
        with connect(self.db) as conn:
            start = "2026-08-31"
            untargeted = core.create_personal_study(conn, {"personal_name": "Sem meta", "priority": 5})
            targeted = core.create_personal_study(conn, {"personal_name": "Com meta", "weekly_goal_minutes": 100})
            core.create_topic(conn, untargeted["id"], {"name": "Livre"})
            topic = core.create_topic(conn, targeted["id"], {"name": "Meta"})
            core.set_availability(conn, {"weekday": 0, "start_time": "06:00", "end_time": "10:00"})
            core.create_planned(conn, {"study_subject_id": targeted["id"], "topic_id": topic["id"], "scheduled_date": start, "start_time": "06:00", "planned_duration_minutes": 100})
            proposal = core.generate_plan(conn, start)
            self.assertEqual(proposal["sessions"], [])
            self.assertEqual(proposal["skipped_without_goal"], ["Sem meta"])

    def test_session_completes_plan_and_mastery_returns_to_manual_base(self):
        with connect(self.db) as conn:
            study = core.create_personal_study(conn, {"personal_name": "Banco"})
            topic = core.create_topic(conn, study["id"], {"name": "Índices", "mastery": 2})
            planned = core.create_planned(conn, {"study_subject_id": study["id"], "topic_id": topic["id"], "scheduled_date": "2026-08-31", "start_time": "10:00", "planned_duration_minutes": 50})
            session = core.create_session(conn, {"study_subject_id": study["id"], "topic_id": topic["id"], "planned_session_id": planned["id"], "duration_seconds": 1800, "mastery_after": 4})
            self.assertEqual(core.planned_detail(conn, planned["id"])["status"], "completed")
            self.assertEqual(core.subject_detail(conn, study["id"])["ungrouped_topics"][0]["status"], "in_progress")
            core.delete_session(conn, session["id"])
            self.assertEqual(core.subject_detail(conn, study["id"])["ungrouped_topics"][0]["mastery"], 2)

    def test_new_academic_attempt_preserves_history_and_increments_number(self):
        with connect(self.db) as conn:
            formation = core.create_formation(conn, {"name": "Curso"})
            curriculum = core.create_curriculum(conn, formation["id"], {"name": "Cálculo", "academic_status": "available"})
            first = core.add_curriculum_study(conn, curriculum["id"], {})
            core.finish_study(conn, first["id"], "failed")
            retry = core.new_academic_attempt(conn, first["id"])
            self.assertEqual(retry["attempt_number"], 2)
            self.assertEqual(core._get(conn, "disciplinas_grade", curriculum["id"])["academic_status"], "in_progress")

    def test_batch_availability_exception_and_explicit_topic_completion(self):
        with connect(self.db) as conn:
            study = core.create_personal_study(conn, {"personal_name": "Circuitos", "weekly_goal_minutes": 300})
            topic = core.create_topic(conn, study["id"], {"name": "Lei de Ohm"})
            result = core.set_availability_batch(conn, {"weekdays": [0, 1, 2, 3, 4, 5], "start_time": "06:00", "end_time": "11:45", "mode": "replace"})
            self.assertEqual(len(result["items"]), 6)
            core.set_availability_exception(conn, {"date": "2026-08-31", "start_time": "08:00", "end_time": "09:00", "kind": "unavailable"})
            proposal = core.generate_plan(conn, "2026-08-31")
            monday = [item for item in proposal["sessions"] if item["scheduled_date"] == "2026-08-31"]
            self.assertTrue(all(not (item["start_time"] < "09:00" and item["start_time"] >= "08:00") for item in monday))
            session = core.create_session(conn, {"study_subject_id": study["id"], "topic_id": topic["id"], "duration_seconds": 1800, "mastery_after": 4, "topic_completed": True, "notes": "Exercícios e revisão."})
            self.assertTrue(session["topic_completed"])
            self.assertEqual(core.subject_detail(conn, study["id"])["ungrouped_topics"][0]["status"], "completed")

    def test_planned_block_can_be_edited_cancelled_and_rescheduled(self):
        with connect(self.db) as conn:
            study = core.create_personal_study(conn, {"personal_name": "Algoritmos"})
            topic = core.create_topic(conn, study["id"], {"name": "Grafos"})
            block = core.create_planned(conn, {"study_subject_id": study["id"], "topic_id": topic["id"], "scheduled_date": "2026-08-31", "start_time": "10:00", "planned_duration_minutes": 90})
            edited = core.update_planned(conn, block["id"], {"start_time": "10:15", "planned_duration_minutes": 75})
            self.assertEqual(edited["start_time"], "10:15")
            moved = core.reschedule_planned(conn, block["id"], {"scheduled_date": "2026-09-01", "start_time": "18:00", "planned_duration_minutes": 75})
            self.assertEqual(moved["previous"]["status"], "rescheduled")
            self.assertEqual(moved["rescheduled"]["scheduled_date"], "2026-09-01")

    def test_project_tasks_drive_real_progress(self):
        with connect(self.db) as conn:
            project = core.create_project(conn, {"name": "Projeto teste", "objective": "Validar CRUD"})
            task = core.add_project_task(conn, project["id"], {"name": "Primeira tarefa"})
            core.update_project_task(conn, task["id"], {"status": "completed"})
            listed = core.projects(conn)
            self.assertEqual(listed[0]["task_count"], 1)
            self.assertEqual(listed[0]["completed_tasks"], 1)
