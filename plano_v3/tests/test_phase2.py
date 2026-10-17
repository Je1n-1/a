from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch

from app import create_app
from tracker import db, sessions, timer
from upgrade import upgrade


class PhaseTwo(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "phase2.db"
        db.initialize(self.path)
        self.app = create_app(self.path)
        self.client = self.app.test_client()

    def at(self, stamp, route, payload, status=200):
        with (
            patch("tracker.timer.now", return_value=stamp),
            patch("tracker.sessions.now", return_value=stamp),
        ):
            response = self.client.post("/api" + route, json=payload)
        self.assertEqual(response.status_code, status, response.get_data(as_text=True))
        return response.json

    def start(self, stamp="2026-10-10T12:00:00+00:00"):
        return self.at(stamp, "/timer", {"operation_key": "start", "title": "Estudo de teste"})

    def count(self, table):
        with closing(db.connect(self.path)) as conn:
            return conn.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]

    def test_midnight_with_pause_preserves_every_second(self):
        t = self.start("2026-10-11T02:40:00+00:00")  # 23:40 São Paulo
        t = self.at(
            "2026-10-11T02:50:00+00:00", f"/timer/{t['id']}/pause", {"version": t["version"]}
        )
        t = self.at(
            "2026-10-11T03:10:00+00:00", f"/timer/{t['id']}/resume", {"version": t["version"]}
        )
        t = self.at(
            "2026-10-11T03:30:00+00:00", f"/timer/{t['id']}/finish", {"version": t["version"]}
        )
        self.assertEqual(
            (t["effective_seconds"], t["break_seconds"], t["total_seconds"]), (1800, 1200, 3000)
        )
        s = self.client.get(f"/api/sessions/{t['session_id']}").json
        self.assertEqual(
            s["daily_allocation"],
            [
                {"date": "2026-10-10", "effective_seconds": 600, "break_seconds": 600, "rest_seconds": 0},
                {"date": "2026-10-11", "effective_seconds": 1200, "break_seconds": 600, "rest_seconds": 0},
            ],
        )

    def test_half_open_midnight_and_historical_dst(self):
        self.assertEqual(
            list(sessions.split_interval("2026-10-11T02:59:59Z", "2026-10-11T03:00:00Z")),
            [("2026-10-10", 1)],
        )
        # São Paulo advanced its clock at midnight on this historical date.
        parts = list(sessions.split_interval("2018-11-04T02:59:59Z", "2018-11-05T02:00:01Z"))
        self.assertEqual(parts, [("2018-11-03", 1), ("2018-11-04", 82800), ("2018-11-05", 1)])

    def test_long_timer_requires_confirmation_and_full_is_idempotent(self):
        t = self.start()
        with patch("tracker.timer.now", return_value="2026-10-10T20:00:00+00:00"):
            state = self.client.get("/api/timer").json
        self.assertTrue(state["recovery_required"])
        self.assertEqual(state["version"], 1)  # Read-only GET does not mutate.
        self.at("2026-10-10T20:00:00+00:00", f"/timer/{t['id']}/finish", {"version": 1}, 409)
        payload = {"version": 1, "choice": "full", "operation_key": "recover-1"}
        t = self.at("2026-10-10T20:00:00+00:00", f"/timer/{t['id']}/recover", payload)
        self.assertEqual(t["status"], "paused")
        self.assertFalse(t["recovery_required"])
        again = self.at("2026-10-10T20:00:00+00:00", f"/timer/{t['id']}/recover", payload)
        self.assertEqual(again["version"], t["version"])
        self.assertEqual(self.count("timer_recoveries"), 1)
        t = self.at(
            "2026-10-10T20:05:00+00:00", f"/timer/{t['id']}/finish", {"version": t["version"]}
        )
        self.assertEqual((t["effective_seconds"], t["break_seconds"]), (28800, 300))

    def test_cutoff_preserves_closed_intervals_and_audits_adjustment(self):
        t = self.start()
        t = self.at("2026-10-10T12:10:00Z", f"/timer/{t['id']}/pause", {"version": 1})
        t = self.at("2026-10-10T12:15:00Z", f"/timer/{t['id']}/resume", {"version": t["version"]})
        # Simulated stamps normally use canonical UTC; accepted cutoff is canonicalized.
        t = self.at(
            "2026-10-10T21:00:00+00:00",
            f"/timer/{t['id']}/recover",
            {
                "version": t["version"],
                "choice": "cutoff",
                "cutoff_at": "2026-10-10T09:35:00",
                "operation_key": "cut",
            },
        )
        self.assertEqual(t["effective_seconds"], 1800)
        self.assertEqual(t["status"], "paused")
        with closing(db.connect(self.path)) as c:
            record = dict(c.execute("SELECT * FROM timer_recoveries").fetchone())
            self.assertEqual(record["accepted_effective_seconds"], 1800)
            self.assertGreater(record["previous_effective_seconds"], 1800)
        t = self.at(
            "2026-10-10T21:00:00+00:00", f"/timer/{t['id']}/finish", {"version": t["version"]}
        )
        self.assertEqual(t["total_seconds"], 9 * 3600)

    def test_invalid_recovery_does_not_mutate(self):
        t = self.start()
        for cutoff in ["bad", "2026-10-10T11:59:00Z", "2026-10-10T22:00:00Z"]:
            self.at(
                "2026-10-10T20:00:00+00:00",
                f"/timer/{t['id']}/recover",
                {"version": 1, "choice": "cutoff", "cutoff_at": cutoff, "operation_key": "bad"},
                400,
            )
        self.assertEqual(self.count("timer_recoveries"), 0)
        self.assertEqual(self.count("timer_intervals"), 1)

    def test_pause_does_not_bypass_long_review(self):
        t = self.start()
        t = self.at("2026-10-10T21:00:00+00:00", f"/timer/{t['id']}/pause", {"version": 1})
        self.assertTrue(t["recovery_required"])
        self.at(
            "2026-10-10T21:00:00+00:00", f"/timer/{t['id']}/resume", {"version": t["version"]}, 409
        )
        self.at("2026-10-10T21:00:00+00:00", f"/timer/{t['id']}/cancel", {"version": t["version"]})
        self.assertEqual(self.count("study_sessions"), 0)

    def test_clock_moves_backwards_and_zero_duration_are_rejected(self):
        t = self.start()
        self.at("2026-10-10T11:59:00+00:00", f"/timer/{t['id']}/pause", {"version": 1}, 409)
        self.at("2026-10-10T12:00:00+00:00", f"/timer/{t['id']}/finish", {"version": 1}, 400)
        self.assertEqual(self.count("timer_intervals"), 1)
        self.assertEqual(self.count("study_sessions"), 0)

    def concurrent(self, route, payloads, stamp):
        barrier = threading.Barrier(len(payloads))

        def send(payload):
            with self.app.test_client() as client:
                barrier.wait(timeout=5)
                r = client.post("/api" + route, json=payload)
                return r.status_code, r.json

        with (
            patch("tracker.timer.now", return_value=stamp),
            ThreadPoolExecutor(max_workers=len(payloads)) as pool,
        ):
            return list(pool.map(send, payloads))

    def test_real_concurrent_starts_and_finishes(self):
        results = self.concurrent(
            "/timer", [{"operation_key": "a"}, {"operation_key": "b"}], "2026-10-10T12:00:00+00:00"
        )
        self.assertEqual(sorted(r[0] for r in results), [200, 409])
        t = next(r[1] for r in results if r[0] == 200)
        results = self.concurrent(
            f"/timer/{t['id']}/finish",
            [{"version": 1}, {"version": 1}],
            "2026-10-10T12:30:00+00:00",
        )
        self.assertEqual([r[0] for r in results], [200, 200])
        self.assertEqual(results[0][1]["session_id"], results[1][1]["session_id"])
        self.assertEqual(self.count("study_sessions"), 1)

    def test_concurrent_pause_and_stale_resume(self):
        t = self.start()
        results = self.concurrent(
            f"/timer/{t['id']}/pause", [{"version": 1}, {"version": 1}], "2026-10-10T12:10:00+00:00"
        )
        self.assertEqual(sorted(r[0] for r in results), [200, 409])
        self.assertEqual(self.count("timer_intervals"), 2)
        self.at("2026-10-10T12:15:00+00:00", f"/timer/{t['id']}/resume", {"version": 1}, 409)

    def test_read_snapshot_is_consistent_while_another_tab_pauses(self):
        t = self.start()
        writing = threading.Event()

        def pause():
            with db.transaction(self.path) as conn:
                timer.transition(conn, t["id"], "pause", {"version": 1})
                writing.set()

        with (
            patch("tracker.timer.now", return_value="2026-10-10T12:30:00+00:00"),
            ThreadPoolExecutor(max_workers=1) as pool,
        ):
            with db.read_transaction(self.path) as conn:
                conn.execute("SELECT * FROM timers").fetchall()
                future = pool.submit(pause)
                self.assertTrue(writing.wait(5))
                state = timer.snapshot(conn, t["id"])
                self.assertEqual(
                    (state["status"], state["version"], state["open_interval"]["kind"]),
                    ("running", 1, "focus"),
                )
            future.result(timeout=5)
        self.assertEqual(self.client.get("/api/timer").json["status"], "paused")

    def test_manual_duration_retry_and_no_invented_timestamps(self):
        payload = {
            "operation_key": "manual",
            "mode": "duration",
            "date": "2026-10-09",
            "duration_seconds": 1801,
            "title": "Leitura",
            "note": "Uma nota",
        }
        s = self.at("2026-10-10T12:00:00+00:00", "/sessions/manual", payload)
        again = self.at("2026-10-10T12:00:00+00:00", "/sessions/manual", payload)
        self.assertEqual(again["id"], s["id"])
        self.assertIsNone(s["started_at"])
        self.assertEqual(s["source"], "manual")
        self.assertEqual(
            s["daily_allocation"],
            [{"date": "2026-10-09", "effective_seconds": 1801, "break_seconds": 0, "rest_seconds": 0}],
        )
        self.assertEqual(self.count("study_sessions"), 1)

    def test_manual_times_cross_midnight(self):
        payload = {
            "operation_key": "manual",
            "mode": "times",
            "started_at": "2026-10-09T23:50:00",
            "ended_at": "2026-10-10T00:20:00",
        }
        s = self.at("2026-10-10T12:00:00+00:00", "/sessions/manual", payload)
        self.assertEqual(s["effective_seconds"], 1800)
        self.assertEqual([d["effective_seconds"] for d in s["daily_allocation"]], [600, 1200])

    def test_manual_validation_and_archive(self):
        base = {
            "operation_key": "manual",
            "mode": "duration",
            "date": "2026-10-09",
            "duration_seconds": 100,
        }
        invalid = [
            {"duration_seconds": 0},
            {"duration_seconds": -1},
            {"duration_seconds": True},
            {"duration_seconds": 1.5},
            {"duration_seconds": 86401},
            {"date": "2026-10-11"},
            {"date": "invalid"},
            {"subject_id": True},
            {
                "mode": "times",
                "started_at": "2026-10-10T10:00:00",
                "ended_at": "2026-10-10T11:00:00",
            },
            {"mode": "times", "started_at": "2026-10-09", "ended_at": "2026-10-10"},
            {
                "mode": "times",
                "started_at": "2018-11-04T00:30:00",
                "ended_at": "2018-11-04T02:00:00",
            },
        ]
        for fields in invalid:
            self.at("2026-10-10T12:00:00+00:00", "/sessions/manual", {**base, **fields}, 400)
        c = self.client.post("/api/courses", json={"name": "Curso"}).json
        s = self.client.post(
            "/api/subjects", json={"course_id": c["id"], "name": "Disciplina"}
        ).json
        self.client.post(f"/api/subject/{s['id']}/archive", json={"archived": True})
        self.at(
            "2026-10-10T12:00:00+00:00", "/sessions/manual", {**base, "subject_id": s["id"]}, 409
        )
        self.assertEqual(self.count("study_sessions"), 0)

    def test_migration_of_populated_phase1_preserves_rows_and_sums(self):
        legacy = Path(self.temp.name) / "phase1.db"
        version, checksum, sql = db.versions()[0]
        with closing(sqlite3.connect(legacy)) as c:
            c.execute("PRAGMA foreign_keys=ON")
            c.execute("CREATE TABLE v3_migrations(version TEXT PRIMARY KEY,checksum TEXT NOT NULL)")
            c.executescript(sql)
            c.execute("INSERT INTO v3_migrations VALUES (?,?)", (version, checksum))
            c.execute("INSERT INTO courses(id,name,created_at) VALUES (1,'Preservar','2026-10-10')")
            c.execute(
                "INSERT INTO study_sessions(title,source,local_date,effective_seconds,created_at) VALUES ('Antiga','manual','2026-10-09',1800,'2026-10-10')"
            )
            c.commit()
        result = upgrade(legacy, Path(self.temp.name) / "backups")
        self.assertEqual(
            result["applied"], ["0002_timer_recovery", "0003_analytics", "0004_topics", "0005_scheduled_break", "0006_rest_time", "0007_projects"]
        )
        self.assertTrue(result["existing_rows_preserved"])
        with closing(sqlite3.connect(result["backup"])) as backup:
            self.assertEqual(backup.execute("SELECT COUNT(*) FROM v3_migrations").fetchone()[0], 1)
        self.assertEqual(db.initialize(legacy), [])
        with closing(db.connect(legacy)) as c:
            self.assertEqual(c.execute("SELECT name FROM courses").fetchone()[0], "Preservar")
            self.assertEqual(
                c.execute("SELECT SUM(effective_seconds) FROM study_sessions").fetchone()[0], 1800
            )
        self.assertEqual(db.diagnostics(legacy)["integrity"], "ok")


if __name__ == "__main__":
    unittest.main()
