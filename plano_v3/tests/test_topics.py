"""Tópicos, revisão manual e compatibilidade; somente bancos temporários."""

from contextlib import closing
import csv
import io
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from app import create_app
from tracker import db
from upgrade import contents, upgrade, verify_preserved


class TopicFlows(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "study.db"
        db.initialize(self.path)
        self.client = create_app(self.path).test_client()
        self.course = self.post("/courses", {"name": "Engenharia"})["id"]
        self.subject = self.post("/subjects", {"course_id": self.course, "name": "Programação"})[
            "id"
        ]
        self.other = self.post("/subjects", {"course_id": self.course, "name": "Circuitos"})["id"]

    def post(self, route, data, status=200):
        response = self.client.post("/api" + route, json=data)
        self.assertEqual(response.status_code, status, response.text)
        return response.json

    def edit(self, route, data, status=200):
        response = self.client.patch("/api" + route, json=data)
        self.assertEqual(response.status_code, status, response.text)
        return response.json

    def topic(self):
        return self.post("/topics", {"subject_id": self.subject, "name": "Ponteiros em C"})

    def timer_at(self, stamp, route, values, status=200):
        with patch("tracker.timer.now", return_value="2026-10-10T" + stamp + "+00:00"):
            return self.post(route, values, status)

    def manual(self, token, topic=None, kind="study", seconds=900):
        return self.post(
            "/sessions/manual",
            {
                "operation_key": token,
                "subject_id": self.subject,
                "topic_id": topic,
                "session_kind": kind,
                "mode": "duration",
                "date": "2026-10-09",
                "duration_seconds": seconds,
            },
        )

    def test_start_pause_resume_finish_and_result_are_atomic_and_idempotent(self):
        t = self.timer_at(
            "12:00:00",
            "/timer",
            {
                "subject_id": self.subject,
                "new_topic_name": "Ponteiros em C",
                "operation_key": "first",
            },
        )
        again = self.timer_at(
            "12:00:05",
            "/timer",
            {
                "subject_id": self.subject,
                "new_topic_name": "Ponteiros em C",
                "operation_key": "first",
            },
        )
        self.assertEqual(t["id"], again["id"])
        self.assertEqual(len(self.client.get("/api/topics").json), 1)
        paused = self.timer_at("12:10:00", f"/timer/{t['id']}/pause", {"version": t["version"]})
        resumed = self.timer_at(
            "12:12:00", f"/timer/{t['id']}/resume", {"version": paused["version"]}
        )
        values = {
            "version": resumed["version"],
            "note": "Exercícios",
            "topic_result": {"version": 1, "completed": True, "needs_review": True},
        }
        done = self.timer_at("12:20:00", f"/timer/{t['id']}/finish", values)
        self.assertEqual((done["effective_seconds"], done["break_seconds"]), (1080, 120))
        repeat = self.timer_at("12:21:00", f"/timer/{t['id']}/finish", values)
        self.assertEqual(repeat["session_id"], done["session_id"])
        topic = self.client.get("/api/topics").json[0]
        self.assertEqual(
            (topic["completed"], topic["needs_review"], topic["version"], topic["sessions"]),
            (1, 1, 2, 1),
        )
        session = self.client.get(f"/api/sessions/{done['session_id']}").json
        self.assertEqual(
            (session["topic_name"], session["session_kind"]), ("Ponteiros em C", "study")
        )
        self.assertEqual(db.diagnostics(self.path)["integrity"], "ok")

    def test_review_preserves_completion_until_explicit_review_result(self):
        topic = self.topic()
        topic = self.edit(
            f"/topics/{topic['id']}", {"version": 1, "completed": True, "needs_review": True}
        )
        self.manual("review", topic["id"], "review")
        pending = self.client.get("/api/topics?review=1").json
        self.assertEqual(len(pending), 1)
        saved = self.edit(
            f"/topics/{topic['id']}", {"version": topic["version"], "needs_review": False}
        )
        self.assertEqual((saved["completed"], saved["needs_review"]), (1, 0))
        self.assertEqual(self.client.get("/api/topics?review=1").json, [])
        self.assertEqual(self.client.get("/api/sessions/recent").json[0]["session_kind"], "review")

    def test_invalid_links_and_failed_inline_creation_roll_back(self):
        topic = self.topic()
        self.post(
            "/timer",
            {"operation_key": "invalid", "subject_id": self.other, "topic_id": topic["id"]},
            400,
        )
        self.post(
            "/timer",
            {"operation_key": "invalid", "subject_id": self.subject, "session_kind": "review"},
            400,
        )
        self.post("/timer", {"operation_key": "invalid", "new_topic_name": "Avulso"}, 400)
        self.post(
            "/timer",
            {
                "operation_key": "invalid",
                "subject_id": self.subject,
                "new_topic_name": "Outro",
                "session_kind": "invalid",
            },
            400,
        )
        self.assertIsNone(self.client.get("/api/timer").json)
        self.assertEqual(len(self.client.get("/api/topics").json), 1)
        same = self.post("/topics", {"subject_id": self.subject, "name": "PONTEIROS EM C"})
        self.assertEqual(same["id"], topic["id"])

    def test_stale_topic_prevents_partial_finish_and_can_be_retried(self):
        topic = self.topic()
        t = self.timer_at(
            "12:00:00",
            "/timer",
            {"operation_key": "s", "subject_id": self.subject, "topic_id": topic["id"]},
        )
        self.edit(f"/topics/{topic['id']}", {"version": 1, "completed": True})
        self.timer_at(
            "12:10:00",
            f"/timer/{t['id']}/finish",
            {"version": 1, "topic_result": {"version": 1, "needs_review": True}},
            409,
        )
        self.assertEqual(self.client.get("/api/timer").json["status"], "running")
        self.assertEqual(self.client.get("/api/sessions/recent").json, [])
        done = self.timer_at(
            "12:10:00",
            f"/timer/{t['id']}/finish",
            {"version": 1, "topic_result": {"version": 2, "needs_review": True}},
        )
        self.assertEqual(done["effective_seconds"], 600)

    def test_topic_status_conflicts_and_invalid_booleans_do_not_save(self):
        topic = self.topic()
        self.edit(f"/topics/{topic['id']}", {"version": 1, "completed": "false"}, 400)
        self.edit(f"/topics/{topic['id']}", {"version": 1, "completed": True})
        self.edit(f"/topics/{topic['id']}", {"version": 1, "needs_review": True}, 409)
        current = self.client.get("/api/topics").json[0]
        self.assertEqual((current["completed"], current["needs_review"]), (1, 0))

    def test_retry_token_cannot_change_topic_or_kind(self):
        topic = self.topic()
        values = {"operation_key": "same", "subject_id": self.subject, "topic_id": topic["id"]}
        self.timer_at("12:00:00", "/timer", values)
        self.timer_at("12:00:05", "/timer", {**values, "session_kind": "review"}, 409)
        self.timer_at("12:00:05", "/timer", {**values, "topic_id": None}, 409)

    def test_topic_survives_recovery_and_new_app(self):
        topic = self.topic()
        t = self.timer_at(
            "00:00:00",
            "/timer",
            {
                "operation_key": "long",
                "subject_id": self.subject,
                "topic_id": topic["id"],
                "session_kind": "review",
            },
        )
        self.client = create_app(self.path).test_client()
        self.timer_at("09:00:00", f"/timer/{t['id']}/finish", {"version": 1}, 409)
        recovered = self.timer_at(
            "09:00:00",
            f"/timer/{t['id']}/recover",
            {
                "version": 1,
                "operation_key": "recover",
                "choice": "cutoff",
                "cutoff_at": "2026-10-10T01:00:00+00:00",
            },
        )
        done = self.timer_at(
            "09:00:00", f"/timer/{t['id']}/finish", {"version": recovered["version"]}
        )
        self.assertEqual(
            (done["topic_id"], done["session_kind"], done["effective_seconds"]),
            (topic["id"], "review", 3600),
        )

    def test_totals_filters_csv_and_missing_topic_reconcile(self):
        topic = self.topic()
        self.manual("one", topic["id"], seconds=900)
        self.manual("two", topic["id"], "review", 600)
        self.manual("none", seconds=300)
        query = "?start=2026-10-09&end=2026-10-09"
        result = self.client.get("/api/analytics" + query).json
        for group in ("by_day", "by_subject", "by_course", "by_topic"):
            self.assertEqual(sum(r["effective_seconds"] for r in result[group]), 1800)
        filtered = self.client.get("/api/analytics" + query + f"&topic_id={topic['id']}").json
        self.assertEqual(filtered["summary"]["period"]["effective_seconds"], 1500)
        self.assertEqual(
            self.client.get("/api/analytics" + query + "&topic_id=none").json["history"]["total"], 1
        )
        csv_text = self.client.get(
            "/api/analytics/export.csv" + query + f"&topic_id={topic['id']}"
        ).data.decode("utf-8-sig")
        rows = list(csv.DictReader(io.StringIO(csv_text), delimiter=";"))
        self.assertEqual({r["Tipo de sessão"] for r in rows}, {"study", "review"})
        self.assertEqual(sum(int(r["Líquido no período (s)"]) for r in rows), 1500)

    def test_corrections_require_explicit_relink_and_preserve_audit(self):
        topic = self.topic()
        s = self.manual("one", topic["id"])
        values = {
            "operation_key": "correction",
            "version": 1,
            "reason": "Disciplina errada",
            "subject_id": self.other,
        }
        self.edit(f"/sessions/{s['id']}", values, 400)
        fixed = self.edit(f"/sessions/{s['id']}", {**values, "topic_id": None})
        self.assertIsNone(fixed["topic_id"])
        audit = self.client.get(f"/api/sessions/{s['id']}/corrections").json
        self.assertEqual(audit[0]["old_values"]["topic_name"], "Ponteiros em C")
        self.assertEqual(fixed["effective_seconds"], 900)

    def test_migration_and_old_backup_preserve_populated_history(self):
        old = Path(self.temp.name) / "old.db"
        with patch("tracker.db.versions", return_value=db.versions()[:3]):
            db.initialize(old)
        with closing(sqlite3.connect(old)) as conn:
            conn.execute(
                "INSERT INTO study_sessions(title,source,local_date,effective_seconds,created_at) VALUES ('Antiga','manual','2026-10-09',600,'2026-10-09')"
            )
            conn.execute("INSERT INTO session_days VALUES (1,'2026-10-09',600,0)")
            conn.commit()
        before = contents(old)
        old_bytes = old.read_bytes()
        result = upgrade(old, Path(self.temp.name) / "backups")
        verify_preserved(old, before)
        self.assertEqual(result["applied"], ["0004_topics", "0005_scheduled_break", "0006_rest_time"])
        previous = create_app(old).test_client().get("/api/sessions/1").json
        self.assertIsNone(previous["topic_id"])
        self.assertIsNone(previous["session_kind"])
        active_before = contents(self.path)
        response = self.client.post(
            "/api/backups/recover",
            data={"confirmed": "true", "file": (io.BytesIO(old_bytes), "old.db")},
        )
        self.assertEqual(response.status_code, 200, response.text)
        verify_preserved(Path(response.json["path"]), before)
        self.assertEqual(contents(self.path), active_before)
