import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from flask import Flask

from database import connection, migrations
from routes.api import api


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class TopicsAndFocusPersistenceApiTest(unittest.TestCase):
    """Contratos da migration 0008 e do fluxo tópico → foco → sessão real.

    Cada caso usa um SQLite temporário. A suíte nunca abre nem altera o banco
    real em ``instance/``.
    """

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / "plano-topics-focus.db"
        self.original_database_path = connection.DATABASE_PATH
        connection.DATABASE_PATH = self.database
        migrations.migrate(self.database)
        app = Flask(__name__)
        app.config["TESTING"] = True
        app.register_blueprint(api)
        self.client = app.test_client()
        self.clock = patch("services.core._local_now")
        self.mock_now = self.clock.start()
        self.set_now(datetime(2026, 9, 1, 7, 0, 0))

    def tearDown(self):
        self.clock.stop()
        connection.DATABASE_PATH = self.original_database_path
        self.temp.cleanup()

    def set_now(self, value):
        self.mock_now.return_value = value

    def formation(self, name="Engenharia de Computação"):
        response = self.client.post("/api/formations", json={"name": name})
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()

    def curriculum(self, formation, name="Circuitos Elétricos I", **values):
        response = self.client.post(
            f"/api/formations/{formation['id']}/curriculum",
            json={"name": name, "academic_status": "available", **values},
        )
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()

    def activate(self, curriculum):
        response = self.client.post(f"/api/curriculum/{curriculum['id']}/add-study", json={})
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()

    def content(self, curriculum, name, **values):
        response = self.client.post(
            f"/api/curriculum/{curriculum['id']}/contents",
            json={"name": name, **values},
        )
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()

    def personal_study_with_topic(self, name="Estudo livre", topic_name="Tópico de foco"):
        study = self.client.post("/api/studies", json={"personal_name": name})
        self.assertEqual(study.status_code, 200, study.get_json())
        topic = self.client.post(f"/api/studies/{study.get_json()['id']}/topics", json={"name": topic_name})
        self.assertEqual(topic.status_code, 200, topic.get_json())
        return study.get_json(), topic.get_json()

    def manual_block(self, study, topic, *, date="2026-09-02", start_time="09:00", minutes=50):
        response = self.client.post(
            "/api/planned",
            json={
                "study_subject_id": study["id"],
                "topic_id": topic["id"],
                "scheduled_date": date,
                "start_time": start_time,
                "planned_duration_minutes": minutes,
            },
        )
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()["source"], "manual")
        return response.get_json()

    def automatic_block(self, study, topic, *, date="2026-09-02", start_time="09:00", minutes=50):
        """Cria um bloco pela mesma rota usada para aplicar uma prévia."""
        response = self.client.post(
            "/api/planning/apply",
            json={
                "sessions": [{
                    "study_subject_id": study["id"],
                    "topic_id": topic["id"],
                    "scheduled_date": date,
                    "start_time": start_time,
                    "planned_duration_minutes": minutes,
                    "selection_reason": "teste de replanejamento",
                }],
            },
        )
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(len(response.get_json()["created"]), 1, response.get_json())
        block = response.get_json()["created"][0]
        self.assertEqual(block["source"], "automatic")
        return block

    def start_focus(self, study, topic=None, **values):
        payload = {"study_subject_id": study["id"], **values}
        if topic is not None:
            payload["topic_id"] = topic["id"]
        response = self.client.post("/api/focus/sessions", json=payload)
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()

    def test_migration_0008_preserves_legacy_topic_ids_and_references(self):
        """A reconstrução de topicos não pode soltar sessões nem blocos legados."""
        legacy = Path(self.temp.name) / "legacy-v7.db"
        available = migrations.available()
        until_v7 = [item for item in available if item[0] <= 7]

        with patch.object(migrations, "available", return_value=until_v7):
            self.assertEqual(migrations.migrate(legacy), list(range(1, 8)))

        conn = sqlite3.connect(legacy)
        try:
            study_id = conn.execute(
                "INSERT INTO materias_estudo(origin,personal_name) VALUES ('personal','Estudo legado')"
            ).lastrowid
            topic_id = conn.execute(
                "INSERT INTO topicos(study_subject_id,name,status,mastery,manual_mastery,sort_order) "
                "VALUES (?,?,?,?,?,?)",
                (study_id, "Tópico legado", "completed", 3, 3, 4),
            ).lastrowid
            planned_id = conn.execute(
                "INSERT INTO sessoes_planejadas(study_subject_id,topic_id,scheduled_date,start_time,planned_duration_minutes) "
                "VALUES (?,?,?,?,?)",
                (study_id, topic_id, "2026-09-01", "08:00", 50),
            ).lastrowid
            study_session_id = conn.execute(
                "INSERT INTO sessoes_estudo(study_subject_id,topic_id,date,duration_seconds,entry_method) "
                "VALUES (?,?,?,?,?)",
                (study_id, topic_id, "2026-09-01", 600, "manual"),
            ).lastrowid
            conn.commit()
        finally:
            conn.close()

        with patch.object(migrations, "available", return_value=available):
            self.assertEqual(migrations.migrate(legacy), [8])

        conn = sqlite3.connect(legacy)
        try:
            topic = conn.execute(
                "SELECT id,status,effort_weight,observations,review_requested,sort_order FROM topicos WHERE id=?",
                (topic_id,),
            ).fetchone()
            self.assertEqual(topic, (topic_id, "completed", 2, None, 0, 4))
            self.assertEqual(
                conn.execute("SELECT topic_id FROM sessoes_planejadas WHERE id=?", (planned_id,)).fetchone()[0],
                topic_id,
            )
            self.assertEqual(
                conn.execute("SELECT topic_id FROM sessoes_estudo WHERE id=?", (study_session_id,)).fetchone()[0],
                topic_id,
            )
            self.assertTrue(
                conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='sessoes_foco'").fetchone()
            )
            self.assertTrue(
                conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='topic_dependencies'").fetchone()
            )
            self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])
        finally:
            conn.close()

    def test_seven_topics_distribute_forty_two_hours_without_creating_extra_demand(self):
        subject = self.curriculum(
            self.formation(),
            required_study_minutes=42 * 60,
            deadline_date="2026-10-01",
        )
        topics = [self.content(subject, f"Unidade {index}", sort_order=index) for index in range(1, 8)]

        preview = self.client.post(
            f"/api/curriculum/{subject['id']}/contents/distribution",
            json={"mode": "proportional"},
        )
        self.assertEqual(preview.status_code, 200, preview.get_json())
        proposed = preview.get_json()
        self.assertFalse(proposed["applied"])
        self.assertEqual(proposed["required_study_minutes"], 2520)
        self.assertEqual(proposed["distributed_minutes"], 2520)
        self.assertTrue(all(row["estimated_minutes"] == 360 for row in proposed["proposed_estimates"]))

        applied = self.client.post(
            f"/api/curriculum/{subject['id']}/contents/distribution",
            json={"mode": "proportional", "apply": True},
        )
        self.assertEqual(applied.status_code, 200, applied.get_json())
        summary = applied.get_json()["summary"]
        self.assertEqual(summary["distributed_minutes"], 2520)
        self.assertEqual(summary["undistributed_minutes"], 0)
        self.assertEqual({row["id"] for row in summary["topics"]}, {row["id"] for row in topics})
        self.assertTrue(all(row["estimated_minutes"] == 360 for row in summary["topics"]))

    def test_generator_prefers_in_progress_then_unlocked_dependency(self):
        subject = self.curriculum(
            self.formation(),
            required_study_minutes=300,
            deadline_date="2026-09-15",
        )
        blocked_prerequisite = self.content(subject, "Base pausada", sort_order=0, status="paused", estimated_minutes=60)
        blocked = self.content(
            subject,
            "Tópico bloqueado",
            sort_order=1,
            estimated_minutes=60,
            prerequisite_topic_ids=[blocked_prerequisite["id"]],
        )
        ready_prerequisite = self.content(subject, "Base concluída", sort_order=2, status="completed")
        ready = self.content(
            subject,
            "Tópico liberado",
            sort_order=3,
            estimated_minutes=60,
            prerequisite_topic_ids=[ready_prerequisite["id"]],
        )
        in_progress = self.content(subject, "Tópico em andamento", sort_order=9, status="in_progress", estimated_minutes=60)
        self.activate(subject)

        dependencies = self.client.get(f"/api/topics/{ready['id']}/dependencies")
        self.assertEqual(dependencies.status_code, 200, dependencies.get_json())
        self.assertEqual(dependencies.get_json()["prerequisite_topic_ids"], [ready_prerequisite["id"]])

        availability = self.client.post(
            "/api/availability",
            json={"weekday": 1, "start_time": "08:00", "end_time": "09:00"},
        )
        self.assertEqual(availability.status_code, 200, availability.get_json())
        first = self.client.post("/api/planning/generate-smart", json={"start": "2026-09-01", "days": 1})
        self.assertEqual(first.status_code, 200, first.get_json())
        first_sessions = first.get_json()["sessions"]
        self.assertTrue(first_sessions)
        self.assertEqual(first_sessions[0]["topic_id"], in_progress["id"])
        self.assertIn("tópico em andamento", first_sessions[0]["reason"])

        completed = self.client.patch(f"/api/contents/{in_progress['id']}", json={"status": "completed"})
        self.assertEqual(completed.status_code, 200, completed.get_json())
        second = self.client.post("/api/planning/generate-smart", json={"start": "2026-09-01", "days": 1})
        self.assertEqual(second.status_code, 200, second.get_json())
        second_sessions = second.get_json()["sessions"]
        self.assertTrue(second_sessions)
        self.assertEqual(second_sessions[0]["topic_id"], ready["id"])
        self.assertNotIn(blocked["id"], [item["topic_id"] for item in second_sessions])
        self.assertIn("pré-requisitos concluídos", second_sessions[0]["reason"])

    def test_topic_estimates_cannot_exceed_subject_effort(self):
        subject = self.curriculum(self.formation(), required_study_minutes=120, deadline_date="2026-10-01")
        first = self.content(subject, "Primeira parte", estimated_minutes=90)
        self.assertEqual(first["estimated_minutes"], 90)

        overflow = self.client.post(
            f"/api/curriculum/{subject['id']}/contents",
            json={"name": "Segunda parte", "estimated_minutes": 40},
        )
        self.assertEqual(overflow.status_code, 409, overflow.get_json())
        self.assertEqual(overflow.get_json()["code"], "topic_effort_overflow")
        summary = self.client.get(f"/api/curriculum/{subject['id']}/contents/distribution")
        self.assertEqual(summary.status_code, 200, summary.get_json())
        self.assertEqual(summary.get_json()["distributed_minutes"], 90)
        self.assertEqual(len(summary.get_json()["topics"]), 1)

    def test_focus_is_persisted_and_pause_resume_are_idempotent(self):
        study, topic = self.personal_study_with_topic()
        started = self.start_focus(study, topic)
        session = started["session"]
        self.assertFalse(started["recovered"])
        self.assertEqual(session["status"], "running")
        self.assertEqual(self.client.get("/api/focus/active").get_json()["id"], session["id"])

        self.set_now(datetime(2026, 9, 1, 7, 5, 0))
        paused = self.client.post(f"/api/focus/sessions/{session['id']}/pause", json={"version": session["version"]})
        self.assertEqual(paused.status_code, 200, paused.get_json())
        paused_data = paused.get_json()
        self.assertEqual(paused_data["status"], "paused")
        self.assertEqual(paused_data["accumulated_seconds"], 300)

        repeated_pause = self.client.post(f"/api/focus/sessions/{session['id']}/pause", json={"version": paused_data["version"]})
        self.assertEqual(repeated_pause.status_code, 200, repeated_pause.get_json())
        self.assertEqual(repeated_pause.get_json()["accumulated_seconds"], 300)
        self.assertEqual(repeated_pause.get_json()["version"], paused_data["version"])

        self.set_now(datetime(2026, 9, 1, 7, 30, 0))
        resumed = self.client.post(f"/api/focus/sessions/{session['id']}/resume", json={"version": paused_data["version"]})
        self.assertEqual(resumed.status_code, 200, resumed.get_json())
        resumed_data = resumed.get_json()
        self.assertEqual(resumed_data["status"], "running")

        self.set_now(datetime(2026, 9, 1, 7, 40, 0))
        reloaded = self.client.get(f"/api/focus/sessions/{session['id']}")
        self.assertEqual(reloaded.status_code, 200, reloaded.get_json())
        self.assertEqual(reloaded.get_json()["elapsed_seconds"], 900)

    def test_focus_rejects_a_second_active_session(self):
        first_study, first_topic = self.personal_study_with_topic("Primeiro", "Primeiro tópico")
        second_study, second_topic = self.personal_study_with_topic("Segundo", "Segundo tópico")
        started = self.start_focus(first_study, first_topic)["session"]

        conflict = self.client.post(
            "/api/focus/sessions",
            json={"study_subject_id": second_study["id"], "topic_id": second_topic["id"]},
        )
        self.assertEqual(conflict.status_code, 409, conflict.get_json())
        self.assertEqual(conflict.get_json()["code"], "focus_session_already_active")
        self.assertEqual(conflict.get_json()["details"]["active_session"]["id"], started["id"])

        cancelled = self.client.post(f"/api/focus/sessions/{started['id']}/cancel", json={"version": started["version"]})
        self.assertEqual(cancelled.status_code, 200, cancelled.get_json())
        self.assertEqual(cancelled.get_json()["status"], "cancelled")
        self.assertEqual(self.start_focus(second_study, second_topic)["session"]["status"], "running")

    def test_focus_finish_is_idempotent_and_creates_one_real_session(self):
        study, topic = self.personal_study_with_topic("Foco idempotente", "Leis de Kirchhoff")
        planned = self.client.post(
            "/api/planned",
            json={
                "study_subject_id": study["id"],
                "topic_id": topic["id"],
                "scheduled_date": "2026-09-01",
                "start_time": "08:00",
                "planned_duration_minutes": 50,
            },
        )
        self.assertEqual(planned.status_code, 200, planned.get_json())
        started = self.client.post("/api/focus/sessions", json={"planned_session_id": planned.get_json()["id"]})
        self.assertEqual(started.status_code, 200, started.get_json())
        focus = started.get_json()["session"]

        self.set_now(datetime(2026, 9, 1, 7, 10, 0))
        finished = self.client.post(
            f"/api/focus/sessions/{focus['id']}/finish",
            json={
                "version": focus["version"],
                "topic_outcome": "continue",
                "note": {"title": "Sessão", "content_markdown": "Anotação persistida"},
            },
        )
        self.assertEqual(finished.status_code, 200, finished.get_json())
        payload = finished.get_json()
        self.assertEqual(payload["session"]["status"], "completed")
        self.assertIsNotNone(payload["study_session"])
        self.assertEqual(payload["study_session"]["topic_id"], topic["id"])
        self.assertEqual(payload["note"]["status"], "final")

        repeated = self.client.post(f"/api/focus/sessions/{focus['id']}/finish", json={})
        self.assertEqual(repeated.status_code, 200, repeated.get_json())
        self.assertTrue(repeated.get_json()["idempotent"])
        self.assertEqual(repeated.get_json()["study_session"]["id"], payload["study_session"]["id"])
        history = self.client.get("/api/sessions?start=2026-09-01&end=2026-09-01")
        self.assertEqual(history.status_code, 200, history.get_json())
        self.assertEqual([row["id"] for row in history.get_json()], [payload["study_session"]["id"]])
        self.assertEqual(self.client.get(f"/api/planned/{planned.get_json()['id']}").get_json()["status"], "completed")

    def test_planned_block_cannot_be_completed_without_a_real_study_session(self):
        """O status do bloco não pode reduzir demanda sem estudo registrado."""
        study, topic = self.personal_study_with_topic("Conclusão de bloco", "Tópico planejado")
        block = self.manual_block(study, topic)

        rejected = self.client.patch(f"/api/planned/{block['id']}", json={"status": "completed"})

        self.assertEqual(rejected.status_code, 409, rejected.get_json())
        self.assertEqual(rejected.get_json()["code"], "planned_completion_requires_session")
        detail = self.client.get(f"/api/planned/{block['id']}")
        self.assertEqual(detail.status_code, 200, detail.get_json())
        self.assertEqual(detail.get_json()["status"], "planned")

    def test_long_running_focus_requires_recovery_before_resume(self):
        study, topic = self.personal_study_with_topic("Recuperação", "Tópico longo")
        settings = self.client.put("/api/settings", json={"focus_recovery_minutes": 15})
        self.assertEqual(settings.status_code, 200, settings.get_json())
        focus = self.start_focus(study, topic)["session"]

        self.set_now(datetime(2026, 9, 1, 7, 16, 0))
        recovered = self.client.get(f"/api/focus/sessions/{focus['id']}")
        self.assertEqual(recovered.status_code, 200, recovered.get_json())
        recovery = recovered.get_json()
        self.assertEqual(recovery["status"], "recovery_required")
        self.assertTrue(recovery["recovery_required"])
        self.assertGreaterEqual(recovery["accumulated_seconds"], 16 * 60)

        denied = self.client.post(f"/api/focus/sessions/{focus['id']}/resume", json={"version": recovery["version"]})
        self.assertEqual(denied.status_code, 409, denied.get_json())
        self.assertEqual(denied.get_json()["code"], "focus_recovery_required")

        accepted = self.client.post(
            f"/api/focus/sessions/{focus['id']}/recover",
            json={"version": recovery["version"], "choice": "actual", "duration_seconds": 600},
        )
        self.assertEqual(accepted.status_code, 200, accepted.get_json())
        self.assertEqual(accepted.get_json()["status"], "paused")
        self.assertEqual(accepted.get_json()["accumulated_seconds"], 600)

    def test_completing_topic_with_future_automatic_blocks_requires_an_explicit_action(self):
        study, topic = self.personal_study_with_topic("Conclusão explícita", "Tópico atual")
        automatic = self.automatic_block(study, topic)
        manual = self.manual_block(study, topic, start_time="10:00")
        focus = self.start_focus(study, topic)["session"]

        self.set_now(datetime(2026, 9, 1, 7, 10, 0))
        rejected = self.client.post(
            f"/api/focus/sessions/{focus['id']}/finish",
            json={"version": focus["version"], "topic_outcome": "completed"},
        )
        self.assertEqual(rejected.status_code, 409, rejected.get_json())
        self.assertEqual(rejected.get_json()["code"], "future_topic_blocks_need_resolution")
        details = rejected.get_json()["details"]
        self.assertEqual([row["id"] for row in details["automatic_blocks"]], [automatic["id"]])
        self.assertEqual([row["id"] for row in details["manual_blocks"]], [manual["id"]])
        self.assertEqual(details["allowed_actions"], ["replan", "next_topic", "review"])

        # A validação ocorre antes de persistir a sessão real ou alterar blocos.
        self.assertEqual(self.client.get(f"/api/planned/{automatic['id']}").get_json()["status"], "planned")
        self.assertEqual(self.client.get(f"/api/planned/{manual['id']}").get_json()["status"], "planned")
        self.assertEqual(self.client.get(f"/api/focus/sessions/{focus['id']}").get_json()["status"], "running")
        history = self.client.get("/api/sessions?start=2026-09-01&end=2026-09-01")
        self.assertEqual(history.status_code, 200, history.get_json())
        self.assertEqual(history.get_json(), [])

    def test_direct_topic_completion_requires_resolution_and_preserves_manual_block(self):
        """A edição do tópico tem as mesmas proteções do encerramento no foco."""
        study, topic = self.personal_study_with_topic("Conclusão direta", "Tópico com agenda")
        automatic = self.automatic_block(study, topic)
        manual = self.manual_block(study, topic, start_time="10:00")

        rejected = self.client.patch(f"/api/topics/{topic['id']}", json={"status": "completed"})
        self.assertEqual(rejected.status_code, 409, rejected.get_json())
        self.assertEqual(rejected.get_json()["code"], "future_topic_blocks_need_resolution")
        self.assertEqual(self.client.get(f"/api/planned/{automatic['id']}").get_json()["status"], "planned")
        self.assertEqual(self.client.get(f"/api/planned/{manual['id']}").get_json()["status"], "planned")

        resolved = self.client.patch(
            f"/api/topics/{topic['id']}",
            json={"status": "completed", "future_blocks_action": "replan"},
        )
        self.assertEqual(resolved.status_code, 200, resolved.get_json())
        self.assertEqual(resolved.get_json()["status"], "completed")
        self.assertEqual(resolved.get_json()["future_blocks"]["action"], "replan")
        self.assertEqual(resolved.get_json()["future_blocks"]["automatic_changed"], 1)
        self.assertEqual(resolved.get_json()["future_blocks"]["manual_preserved"], 1)
        self.assertEqual(self.client.get(f"/api/planned/{automatic['id']}").get_json()["status"], "cancelled")
        self.assertEqual(self.client.get(f"/api/planned/{manual['id']}").get_json()["status"], "planned")

    def test_curriculum_planning_opt_out_blocks_automatic_generation_until_reenabled(self):
        formation = self.formation("Formação com opt-out")
        subject = self.curriculum(
            formation,
            "Disciplina opcional no plano",
            academic_status="in_progress",
            required_study_minutes=50,
            deadline_date="2026-09-10",
        )
        study = self.activate(subject)
        availability = self.client.post(
            "/api/availability",
            json={"weekday": 1, "start_time": "08:00", "end_time": "09:00"},
        )
        self.assertEqual(availability.status_code, 200, availability.get_json())

        disabled = self.client.patch(f"/api/curriculum/{subject['id']}", json={"planning_enabled": False})
        self.assertEqual(disabled.status_code, 200, disabled.get_json())
        self.assertEqual(disabled.get_json()["planning_opt_out"], 1)
        blocked = self.client.post("/api/planning/generate-smart", json={"start": "2026-09-01", "days": 1})
        self.assertEqual(blocked.status_code, 200, blocked.get_json())
        self.assertEqual(blocked.get_json()["sessions"], [])
        ideal = self.client.get("/api/planning/ideal?start=2026-09-01&end=2026-09-10")
        self.assertEqual(ideal.status_code, 200, ideal.get_json())
        item = next(row for row in ideal.get_json()["items"] if row["study_subject_id"] == study["id"])
        self.assertEqual(item["planning_state"], "planning_disabled")

        enabled = self.client.patch(f"/api/curriculum/{subject['id']}", json={"planning_enabled": True})
        self.assertEqual(enabled.status_code, 200, enabled.get_json())
        self.assertEqual(enabled.get_json()["planning_opt_out"], 0)
        generated = self.client.post("/api/planning/generate-smart", json={"start": "2026-09-01", "days": 1})
        self.assertEqual(generated.status_code, 200, generated.get_json())
        sessions = generated.get_json()["sessions"]
        self.assertTrue(sessions, generated.get_json())
        self.assertEqual(sessions[0]["study_subject_id"], study["id"])

    def test_today_recognizes_free_time_and_daily_limits_without_filling_it(self):
        """Carga futura viável não pode virar uma falsa obrigação de hoje."""
        response = self.client.post("/api/studies", json={
            "personal_name": "Leitura paralela", "required_study_minutes": 120,
            "target_date": "2026-09-10",
        })
        self.assertEqual(response.status_code, 200, response.get_json())
        available = self.client.post("/api/availability", json={
            "weekday": 1, "start_time": "08:00", "end_time": "12:00",
        })
        self.assertEqual(available.status_code, 200, available.get_json())
        settings = self.client.put("/api/settings", json={
            "daily_max_study_minutes": 120, "minimum_rest_minutes": 30,
            "suggest_during_free_time": False, "free_time_preference": "preserve",
        })
        self.assertEqual(settings.status_code, 200, settings.get_json())

        capacity = self.client.get("/api/planning/capacity?start=2026-09-01&end=2026-09-01")
        self.assertEqual(capacity.status_code, 200, capacity.get_json())
        self.assertEqual(capacity.get_json()["capacity_minutes"], 120)
        self.assertEqual(capacity.get_json()["free_minutes"], 120)

        today = self.client.get("/api/today")
        self.assertEqual(today.status_code, 200, today.get_json())
        self.assertTrue(today.get_json()["on_track"], today.get_json())
        self.assertEqual(today.get_json()["suggestion"], None)
        self.assertIn("Manter o horário livre", today.get_json()["free_time_options"])

    def test_disallowed_curriculum_states_reject_manual_and_focus_access(self):
        """Estados acadêmicos não elegíveis não podem ser contornados por APIs manuais."""
        rejected_states = {
            "not_available": "curriculum_not_studyable",
            "locked": "curriculum_not_studyable",
            "exempted": "curriculum_not_studyable",
            "failed": "curriculum_not_studyable",
            "completed": "curriculum_completed_review_only",
        }
        for index, (academic_status, expected_code) in enumerate(rejected_states.items(), start=1):
            with self.subTest(academic_status=academic_status):
                formation = self.formation(f"Formação de acesso {index}")
                subject = self.curriculum(
                    formation,
                    f"Disciplina de acesso {index}",
                    required_study_minutes=60,
                    deadline_date="2026-09-10",
                )
                topic = self.content(subject, "Tópico protegido", estimated_minutes=60)
                study = self.activate(subject)
                changed = self.client.post(
                    f"/api/curriculum/{subject['id']}/status",
                    json={"academic_status": academic_status},
                )
                self.assertEqual(changed.status_code, 200, changed.get_json())

                manual_block = self.client.post(
                    "/api/planned",
                    json={
                        "study_subject_id": study["id"], "topic_id": topic["id"],
                        "scheduled_date": f"2026-09-{index + 1:02d}", "start_time": "09:00",
                        "planned_duration_minutes": 30,
                    },
                )
                self.assertEqual(manual_block.status_code, 409, manual_block.get_json())
                self.assertEqual(manual_block.get_json()["code"], expected_code)

                manual_session = self.client.post(
                    "/api/sessions",
                    json={
                        "study_subject_id": study["id"], "topic_id": topic["id"],
                        "date": "2026-09-01", "duration_seconds": 30 * 60,
                        "entry_method": "manual",
                    },
                )
                self.assertEqual(manual_session.status_code, 409, manual_session.get_json())
                self.assertEqual(manual_session.get_json()["code"], expected_code)

                focus = self.client.post(
                    "/api/focus/sessions",
                    json={"study_subject_id": study["id"], "topic_id": topic["id"]},
                )
                self.assertEqual(focus.status_code, 409, focus.get_json())
                self.assertEqual(focus.get_json()["code"], expected_code)
                self.assertIsNone(self.client.get("/api/focus/active").get_json())

    def test_replan_cancels_only_future_automatic_blocks_and_preserves_manual_ones(self):
        study, topic = self.personal_study_with_topic("Replanejar", "Tópico concluído")
        automatic = self.automatic_block(study, topic)
        manual = self.manual_block(study, topic, start_time="10:00")
        focus = self.start_focus(study, topic)["session"]

        self.set_now(datetime(2026, 9, 1, 7, 10, 0))
        finished = self.client.post(
            f"/api/focus/sessions/{focus['id']}/finish",
            json={
                "version": focus["version"],
                "topic_outcome": "completed",
                "future_blocks_action": "replan",
            },
        )
        self.assertEqual(finished.status_code, 200, finished.get_json())
        future_blocks = finished.get_json()["future_blocks"]
        self.assertEqual(future_blocks["action"], "replan")
        self.assertEqual(future_blocks["automatic_changed"], 1)
        self.assertEqual(future_blocks["manual_preserved"], 1)

        automatic_detail = self.client.get(f"/api/planned/{automatic['id']}")
        manual_detail = self.client.get(f"/api/planned/{manual['id']}")
        self.assertEqual(automatic_detail.status_code, 200, automatic_detail.get_json())
        self.assertEqual(manual_detail.status_code, 200, manual_detail.get_json())
        self.assertEqual(automatic_detail.get_json()["source"], "automatic")
        self.assertEqual(automatic_detail.get_json()["status"], "cancelled")
        self.assertEqual(manual_detail.get_json()["source"], "manual")
        self.assertEqual(manual_detail.get_json()["status"], "planned")
        self.assertEqual(manual_detail.get_json()["topic_id"], topic["id"])

    def test_next_topic_reassociates_only_future_automatic_blocks(self):
        study, current_topic = self.personal_study_with_topic("Avançar tópico", "Fundamentos")
        next_topic_response = self.client.post(
            f"/api/studies/{study['id']}/topics",
            json={"name": "Próximo conteúdo", "sort_order": 1},
        )
        self.assertEqual(next_topic_response.status_code, 200, next_topic_response.get_json())
        next_topic = next_topic_response.get_json()
        automatic = self.automatic_block(study, current_topic)
        manual = self.manual_block(study, current_topic, start_time="10:00")
        focus = self.start_focus(study, current_topic)["session"]

        self.set_now(datetime(2026, 9, 1, 7, 10, 0))
        finished = self.client.post(
            f"/api/focus/sessions/{focus['id']}/finish",
            json={
                "version": focus["version"],
                "topic_outcome": "advance",
                "future_blocks_action": "next_topic",
            },
        )
        self.assertEqual(finished.status_code, 200, finished.get_json())
        payload = finished.get_json()
        self.assertEqual(payload["future_blocks"]["action"], "next_topic")
        self.assertEqual(payload["future_blocks"]["automatic_changed"], 1)
        self.assertEqual(payload["future_blocks"]["manual_preserved"], 1)
        self.assertEqual(payload["next_topic"]["id"], next_topic["id"])

        automatic_detail = self.client.get(f"/api/planned/{automatic['id']}").get_json()
        manual_detail = self.client.get(f"/api/planned/{manual['id']}").get_json()
        self.assertEqual(automatic_detail["status"], "planned")
        self.assertEqual(automatic_detail["source"], "automatic")
        self.assertEqual(automatic_detail["topic_id"], next_topic["id"])
        self.assertIn("avançado após conclusão", automatic_detail["selection_reason"])
        self.assertEqual(manual_detail["status"], "planned")
        self.assertEqual(manual_detail["source"], "manual")
        self.assertEqual(manual_detail["topic_id"], current_topic["id"])

    def test_planned_detail_separates_block_status_from_topic_status_and_progress(self):
        study_response = self.client.post(
            "/api/studies",
            json={"personal_name": "Métricas do bloco", "required_study_minutes": 60},
        )
        self.assertEqual(study_response.status_code, 200, study_response.get_json())
        study = study_response.get_json()
        topic_response = self.client.post(
            f"/api/studies/{study['id']}/topics",
            json={"name": "Tópico em andamento", "status": "in_progress", "estimated_minutes": 60},
        )
        self.assertEqual(topic_response.status_code, 200, topic_response.get_json())
        topic = topic_response.get_json()
        block = self.manual_block(study, topic)
        session = self.client.post(
            "/api/sessions",
            json={
                "study_subject_id": study["id"],
                "topic_id": topic["id"],
                "date": "2026-09-01",
                "duration_seconds": 30 * 60,
                "entry_method": "manual",
            },
        )
        self.assertEqual(session.status_code, 200, session.get_json())

        detail = self.client.get(f"/api/planned/{block['id']}")
        self.assertEqual(detail.status_code, 200, detail.get_json())
        data = detail.get_json()
        self.assertEqual(data["status"], "planned")
        self.assertEqual(data["topic_status"], "in_progress")
        self.assertEqual(data["topic_real_minutes"], 30)
        self.assertEqual(data["topic_remaining_minutes"], 30)
        self.assertEqual(data["topic_future_planned_minutes"], 50)
        self.assertEqual(data["topic_progress_percent"], 50.0)

    def test_early_completion_credit_reduces_demand_but_never_in_review_mode(self):
        formation = self.formation("Formação de crédito")
        subject = self.curriculum(
            formation,
            "Disciplina com folga",
            required_study_minutes=120,
            deadline_date="2026-09-15",
        )
        completed = self.content(subject, "Tópico concluído cedo", status="completed", estimated_minutes=60)
        self.content(subject, "Tópico restante", estimated_minutes=60)
        study = self.activate(subject)
        session = self.client.post(
            "/api/sessions",
            json={
                "study_subject_id": study["id"],
                "topic_id": completed["id"],
                "date": "2026-09-01",
                "duration_seconds": 30 * 60,
                "entry_method": "manual",
            },
        )
        self.assertEqual(session.status_code, 200, session.get_json())

        normal = self.client.get("/api/planning/ideal?start=2026-09-01&end=2026-09-15")
        self.assertEqual(normal.status_code, 200, normal.get_json())
        normal_item = next(item for item in normal.get_json()["items"] if item["study_subject_id"] == study["id"])
        self.assertFalse(normal_item["review_mode"])
        self.assertEqual(normal_item["real_minutes"], 30)
        self.assertEqual(normal_item["planning_completed_credit_minutes"], 30)
        self.assertEqual(normal_item["planning_effective_completed_minutes"], 60)
        self.assertEqual(normal_item["remaining_minutes"], 60)

        review = self.client.post(
            f"/api/curriculum/{subject['id']}/review",
            json={"status": "queued"},
        )
        self.assertEqual(review.status_code, 200, review.get_json())
        curriculum_completed = self.client.post(
            f"/api/curriculum/{subject['id']}/status",
            json={"academic_status": "completed"},
        )
        self.assertEqual(curriculum_completed.status_code, 200, curriculum_completed.get_json())

        in_review = self.client.get("/api/planning/ideal?start=2026-09-01&end=2026-09-15")
        self.assertEqual(in_review.status_code, 200, in_review.get_json())
        review_item = next(item for item in in_review.get_json()["items"] if item["study_subject_id"] == study["id"])
        self.assertTrue(review_item["review_mode"])
        self.assertEqual(review_item["real_minutes"], 30)
        self.assertEqual(review_item["planning_completed_credit_minutes"], 0)
        self.assertEqual(review_item["planning_effective_completed_minutes"], 30)
        self.assertEqual(review_item["remaining_minutes"], 90)


if __name__ == "__main__":
    unittest.main()
