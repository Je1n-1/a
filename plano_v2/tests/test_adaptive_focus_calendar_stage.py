import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from flask import Flask

from database import connection
from database.migrations import migrate
from routes.api import api
from routes.calendar import calendar_api
from routes.pages import pages
from services import google_calendar


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class AdaptiveFocusCalendarStageTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / "adaptive-stage.db"
        self.previous = connection.DATABASE_PATH
        connection.DATABASE_PATH = self.database
        migrate(self.database)
        self.clock = patch("services.core._local_now", return_value=datetime(2026, 9, 21, 9, 0))
        self.clock.start()
        app = Flask(
            __name__,
            template_folder=str(PROJECT_ROOT / "templates"),
            static_folder=str(PROJECT_ROOT / "static"),
        )
        app.config["TESTING"] = True
        app.register_blueprint(pages)
        app.register_blueprint(api)
        app.register_blueprint(calendar_api)
        self.client = app.test_client()

    def tearDown(self):
        self.clock.stop()
        connection.DATABASE_PATH = self.previous
        self.temp.cleanup()

    def post(self, url, payload=None, expected=200):
        response = self.client.post(url, json=payload or {})
        self.assertEqual(response.status_code, expected, response.get_json())
        return response.get_json()

    def study(self, name="Cálculo"):
        return self.post("/api/studies", {
            "personal_name": name,
            "difficulty": "unknown",
            "mastery_level": "unknown",
            "start_date": "2026-09-21",
            "target_date": "2026-10-18",
            "allowed_weekdays": [0, 1, 2, 3, 4, 5],
            "idempotency_key": f"study-{name}",
        })

    def test_simplified_registration_is_idempotent_and_keeps_unknowns_provisional(self):
        first = self.study()
        second = self.post("/api/studies", {
            "personal_name": "Cálculo",
            "difficulty": "unknown", "mastery_level": "unknown",
            "start_date": "2026-09-21", "target_date": "2026-10-18",
            "allowed_weekdays": [0, 1, 2, 3, 4, 5], "idempotency_key": "study-Cálculo",
        })
        self.assertEqual(first["id"], second["id"])
        recommendation = self.client.get(f"/api/studies/{first['id']}/recommendation").get_json()
        self.assertTrue(recommendation["is_estimate"])
        self.assertEqual(recommendation["confidence"], "initial")
        self.assertIn("domínio ainda desconhecido", recommendation["factors"])
        with connection.connect() as conn:
            row = conn.execute("SELECT COUNT(*) FROM materias_estudo").fetchone()[0]
            baselines = conn.execute("SELECT COUNT(*) FROM study_plan_baselines").fetchone()[0]
        self.assertEqual((row, baselines), (1, 1))

    def test_three_consistent_observations_adjust_once_and_decision_is_idempotent(self):
        study = self.study("Física")
        initial = self.client.get(f"/api/studies/{study['id']}/recommendation").get_json()
        adjustments = []
        for index in range(3):
            result = self.post(f"/api/studies/{study['id']}/observations", {
                "kind": "mastery", "raw_value": "still_difficult",
                "observed_at": f"2026-09-21T23:0{index + 1}:00-03:00",
                "idempotency_key": f"observation-{index}",
            })
            adjustments.append(result["adjustment_applied"])
        self.assertEqual(adjustments, [False, False, True])
        history = self.client.get(f"/api/studies/{study['id']}/recommendations").get_json()
        self.assertGreaterEqual(len(history), 2)
        latest = history[-1]
        self.assertGreater(latest["recommended_daily_minutes"], initial["recommended_daily_minutes"])
        payload = {"action": "accepted", "idempotency_key": "accept-fisica"}
        first = self.post(f"/api/studies/{study['id']}/recommendations/{latest['id']}/decision", payload)
        second = self.post(f"/api/studies/{study['id']}/recommendations/{latest['id']}/decision", payload)
        self.assertFalse(first["idempotent"])
        self.assertTrue(second["idempotent"])

    def test_retroactive_break_recalculates_exactly_once_and_can_be_deleted_with_session(self):
        study = self.study("Química")
        session = self.post("/api/sessions", {
            "study_subject_id": study["id"], "date": "2026-09-21",
            "started_at": "2026-09-21T08:00:00-03:00",
            "ended_at": "2026-09-21T09:15:00-03:00",
            "duration_seconds": 4500,
        })
        correction = {
            "duration_seconds": 900, "reason": "rest",
            "idempotency_key": "forgotten-break-1",
        }
        first = self.post(f"/api/sessions/{session['id']}/breaks", correction)
        second = self.post(f"/api/sessions/{session['id']}/breaks", correction)
        self.assertEqual(first["session"]["duration_seconds"], 3600)
        self.assertEqual(first["session"]["pause_seconds"], 900)
        self.assertTrue(second["idempotent"])
        detail = self.client.get(f"/api/sessions/{session['id']}").get_json()
        self.assertEqual((len(detail["breaks"]), len(detail["corrections"])), (1, 1))
        deleted = self.client.delete(f"/api/sessions/{session['id']}")
        self.assertEqual(deleted.status_code, 200, deleted.get_json())

    def test_midnight_splits_focus_and_pause_without_changing_totals(self):
        study = self.study("História")
        session = self.post("/api/sessions", {
            "study_subject_id": study["id"], "date": "2026-09-21",
            "started_at": "2026-09-21T23:50:00-03:00",
            "ended_at": "2026-09-22T00:20:00-03:00",
            "duration_seconds": 1800,
        })
        self.post(f"/api/sessions/{session['id']}/breaks", {
            "started_at": "2026-09-21T23:58:00-03:00",
            "ended_at": "2026-09-22T00:03:00-03:00",
            "reason": "water_food", "idempotency_key": "midnight-break",
        })
        analytics = self.client.get("/api/analytics/detailed?start=2026-09-21&end=2026-09-22").get_json()
        self.assertEqual(analytics["totals"]["focus_seconds"], 1500)
        self.assertEqual(analytics["totals"]["pause_seconds"], 300)
        daily = {item["date"]: item for item in analytics["daily"]}
        self.assertEqual(daily["2026-09-21"]["pause_seconds"], 120)
        self.assertEqual(daily["2026-09-22"]["pause_seconds"], 180)
        self.assertEqual(sum(item["focus_seconds"] for item in daily.values()), 1500)

    def test_focus_sequence_records_sixty_minutes_of_focus_and_fifteen_of_breaks(self):
        study = self.study("Lógica")

        def at(hour, minute):
            return patch("services.core._local_now", return_value=datetime(2026, 9, 21, hour, minute))

        with at(8, 0):
            focus = self.post("/api/focus/sessions", {"study_subject_id": study["id"]})["session"]
        with at(8, 25):
            self.post(f"/api/focus/sessions/{focus['id']}/pause", {"reason": "rest"})
        with at(8, 30):
            self.post(f"/api/focus/sessions/{focus['id']}/resume")
        with at(8, 50):
            self.post(f"/api/focus/sessions/{focus['id']}/pause", {"reason": "water_food"})
        with at(9, 0):
            self.post(f"/api/focus/sessions/{focus['id']}/resume")
        with at(9, 15):
            completed = self.post(f"/api/focus/sessions/{focus['id']}/finish", {})
        self.assertEqual(completed["study_session"]["duration_seconds"], 3600)
        self.assertEqual(completed["pause_summary"]["pause_seconds"], 900)
        self.assertEqual(len(completed["pause_summary"]["breaks"]), 2)
        detail = self.client.get(f"/api/sessions/{completed['study_session']['id']}").get_json()
        self.assertEqual(detail["pause_seconds"], 900)

    def test_versioned_plan_rejects_stale_preview_and_repeated_apply_is_safe(self):
        study = self.study("Banco de Dados")
        self.post(f"/api/studies/{study['id']}/topics", {"name": "Transações"})
        changed = self.client.patch(f"/api/studies/{study['id']}", json={"required_study_minutes": 120})
        self.assertEqual(changed.status_code, 200, changed.get_json())
        self.post("/api/availability", {"weekday": 0, "start_time": "08:00", "end_time": "12:00"})
        preview = self.post("/api/planning/preview", {"start": "2026-09-21", "days": 1})
        self.assertTrue(preview["preview_token"])
        self.post("/api/availability", {"weekday": 0, "start_time": "13:00", "end_time": "14:00"})
        stale = self.client.post("/api/planning/apply-versioned", json={
            "preview_token": preview["preview_token"], "idempotency_key": "stale-apply",
        })
        self.assertEqual(stale.status_code, 409, stale.get_json())
        fresh = self.post("/api/planning/preview", {"start": "2026-09-21", "days": 1})
        payload = {"preview_token": fresh["preview_token"], "idempotency_key": "fresh-apply"}
        first = self.post("/api/planning/apply-versioned", payload)
        second = self.post("/api/planning/apply-versioned", payload)
        self.assertTrue(first["created"])
        self.assertFalse(first["idempotent"])
        self.assertTrue(second["idempotent"])
        self.assertEqual([item["id"] for item in first["created"]], [item["id"] for item in second["created"]])
        self.assertTrue(all(item["study_subject_id"] == study["id"] for item in first["created"]))

    def test_global_weekly_and_per_subject_daily_caps_limit_new_proposals(self):
        study = self.study("Estatística")
        self.post(f"/api/studies/{study['id']}/topics", {"name": "Probabilidade"})
        changed = self.client.patch(f"/api/studies/{study['id']}", json={"required_study_minutes": 900})
        self.assertEqual(changed.status_code, 200, changed.get_json())
        settings = self.client.put("/api/settings", json={
            "daily_max_study_minutes": 600,
            "weekly_max_study_minutes": 180,
            "subject_daily_max_minutes": 60,
            "planning_break_minutes": 0,
        })
        self.assertEqual(settings.status_code, 200, settings.get_json())
        for weekday in (0, 1, 2):
            self.post("/api/availability", {"weekday": weekday, "start_time": "08:00", "end_time": "12:00"})
        preview = self.post("/api/planning/preview", {"start": "2026-09-21", "days": 3})
        per_day = {}
        for block in preview["sessions"]:
            per_day[block["scheduled_date"]] = per_day.get(block["scheduled_date"], 0) + block["planned_duration_minutes"]
        self.assertTrue(preview["sessions"])
        self.assertLessEqual(sum(per_day.values()), 180)
        # O teto semanal continua global. O antigo teto oculto por matéria não
        # transforma disponibilidade em obrigação no motor interativo.
        self.assertTrue(all(minutes <= 180 for minutes in per_day.values()))
        self.assertTrue(all(row["weekly_limit_minutes"] == 180 for row in preview["capacity"]["capacity_by_day"]))

    def test_google_outbox_is_idempotent_and_updates_then_deletes_managed_event(self):
        study = self.study("Redes")
        with connection.connect() as conn:
            run = conn.execute("""
                INSERT INTO planning_runs(preview_token,status,policy_version,horizon_start,horizon_end,input_fingerprint)
                VALUES ('google-preview','applied','collective-v2','2026-09-21','2026-09-21','hash')
            """).lastrowid
            planned = conn.execute("""
                INSERT INTO sessoes_planejadas(
                  study_subject_id,scheduled_date,start_time,planned_duration_minutes,status,source,plan_run_id
                ) VALUES (?, '2026-09-21','10:00',50,'planned','automatic',?)
            """, (study["id"], run)).lastrowid
            conn.execute("UPDATE calendar_integrations SET status='connected',encrypted_credentials='protected-test' WHERE provider='google'")

        class FakeTransport:
            def __init__(self):
                self.upserts = []
                self.deletes = []

            def upsert(self, calendar_id, external_id, payload):
                self.upserts.append((calendar_id, external_id, payload))
                return {"id": external_id or "remote-1", "etag": f"etag-{len(self.upserts)}"}

            def delete(self, calendar_id, external_id):
                self.deletes.append((calendar_id, external_id))

        fake = FakeTransport()
        with connection.connect() as conn:
            first = google_calendar.sync_pending(conn, fake)
            second = google_calendar.sync_pending(conn, fake)
            conn.execute("UPDATE sessoes_planejadas SET start_time='11:00' WHERE id=?", (planned,))
            updated = google_calendar.sync_pending(conn, fake)
            conn.execute("UPDATE sessoes_planejadas SET status='cancelled' WHERE id=?", (planned,))
            deleted = google_calendar.sync_pending(conn, fake)
            mapping = conn.execute("SELECT * FROM external_calendar_events WHERE planned_session_id=?", (planned,)).fetchone()
        self.assertEqual((first["synced"], second["processed"], updated["synced"], deleted["deleted"]), (1, 0, 1, 1))
        self.assertEqual([call[1] for call in fake.upserts], [None, "remote-1"])
        self.assertEqual(fake.deletes, [("primary", "remote-1")])
        self.assertEqual(mapping["sync_status"], "deleted")

    def test_direct_page_routes_and_google_status_work_without_credentials(self):
        study = self.study("Português")
        for path in (
            "/subjects", "/subjects/new", f"/subjects/{study['id']}",
            f"/subjects/{study['id']}/contents", f"/subjects/{study['id']}/settings",
            "/settings/study", "/settings/availability", "/settings/integrations",
        ):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, path)
        status = self.client.get("/api/calendar/google/status")
        self.assertEqual(status.status_code, 200, status.get_json())
        self.assertFalse(status.get_json()["connected"])
        self.assertEqual(status.get_json()["local_fallback"], "/api/calendar.ics")


if __name__ == "__main__":
    unittest.main()
