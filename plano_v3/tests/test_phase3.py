from contextlib import closing
import csv
import io
from pathlib import Path
import sqlite3
import hashlib
import tempfile
import unittest
from unittest.mock import patch

from app import create_app
from tracker import analytics, db, timer
from upgrade import upgrade

STAMP = "2026-10-10T18:00:00+00:00"


class PhaseThree(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "analytics.db"
        db.initialize(self.path)
        self.client = create_app(self.path).test_client()
        self.sequence = 0
        self.course = self.client.post("/api/courses", json={"name": "Engenharia"}).json["id"]
        self.subject = self.client.post(
            "/api/subjects", json={"name": "Circuitos", "course_id": self.course}
        ).json["id"]
        self.other_course = self.client.post("/api/courses", json={"name": "Computação"}).json["id"]
        self.other = self.client.post(
            "/api/subjects", json={"name": "Circuitos", "course_id": self.other_course}
        ).json["id"]

    def manual(self, seconds=1800, **kwargs):
        self.sequence += 1
        payload = {
            "operation_key": str(self.sequence),
            "mode": "duration",
            "date": "2026-10-09",
            "duration_seconds": seconds,
            "subject_id": self.subject,
            **kwargs,
        }
        with patch("tracker.sessions.now", return_value=STAMP):
            r = self.client.post("/api/sessions/manual", json=payload)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json

    def report(self, query="start=2026-10-01&end=2026-10-10"):
        with patch("tracker.analytics.now", return_value=STAMP):
            r = self.client.get("/api/analytics?" + query)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json

    def reconcile(self, query, expected, count):
        data = self.report(query)
        self.assertEqual(data["summary"]["period"]["effective_seconds"], expected)
        self.assertEqual(data["history"]["total"], count)
        self.assertEqual(sum(d["effective_seconds"] for d in data["by_day"]), expected)
        self.assertEqual(sum(d["effective_seconds"] for d in data["by_subject"]), expected)
        rows = []
        for page in range(1, data["history"]["pages"] + 1):
            rows.extend(self.report(query + "&page=" + str(page))["history"]["rows"])
        self.assertEqual(sum(r["effective_seconds"] for r in rows), expected)
        self.assertEqual(len({r["id"] for r in rows}), count)
        csv_response = self.client.get("/api/analytics/export.csv?" + query)
        self.assertEqual(csv_response.status_code, 200)
        self.assertTrue(csv_response.data.startswith(b"\xef\xbb\xbf"))
        exported = list(
            csv.DictReader(io.StringIO(csv_response.data.decode("utf-8-sig")), delimiter=";")
        )
        self.assertEqual(len(exported), count)
        self.assertEqual(sum(int(r["Líquido no período (s)"]) for r in exported), expected)
        return data

    def test_empty_and_invalid_filters(self):
        data = self.reconcile("start=2026-10-01&end=2026-10-10", 0, 0)
        self.assertEqual(len(data["by_day"]), 10)
        self.assertEqual(len(self.report("start=9999-12-31&end=9999-12-31")["by_day"]), 1)
        for query in [
            "start=x",
            "start=2026-10-10&end=2026-10-01",
            "course_id=1%20OR%201=1",
            "page=-1",
            "page_size=101",
            "subject_id=nan",
            "start=1900-01-01&end=2026-10-10",
        ]:
            self.assertEqual(self.client.get("/api/analytics?" + query).status_code, 400)
            self.assertEqual(self.client.get("/api/analytics/export.csv?" + query).status_code, 400)

    def test_more_than_100_and_page_boundary_export_has_all(self):
        for i in range(123):
            self.manual(seconds=61 + i)
        data = self.reconcile(
            "start=2026-10-09&end=2026-10-09&page_size=20", sum(61 + i for i in range(123)), 123
        )
        self.assertEqual(data["history"]["pages"], 7)
        self.assertEqual(
            self.report("start=2026-10-09&end=2026-10-09&page=999")["history"]["page"], 7
        )

    def test_course_subject_free_archived_and_cards_have_defined_ranges(self):
        self.manual(600)
        self.manual(900, subject_id=self.other)
        self.manual(60, subject_id=None)
        self.manual(300, date="2026-10-10")
        self.manual(120, date="2026-10-02")
        self.client.post(f"/api/course/{self.course}/archive", json={"archived": True})
        data = self.reconcile(f"start=2026-10-09&end=2026-10-09&course_id={self.course}", 600, 1)
        self.assertEqual(data["summary"]["today"]["effective_seconds"], 300)
        self.assertEqual(data["summary"]["week"]["effective_seconds"], 900)
        self.assertEqual(data["summary"]["month"]["effective_seconds"], 1020)
        with patch("tracker.analytics.now", return_value=STAMP):
            quick = self.client.get("/api/sessions/summary").json
        self.assertEqual(quick["today"]["effective_seconds"], 300)
        self.assertEqual(quick["week"]["effective_seconds"], 1860)
        self.reconcile(f"start=2026-10-09&end=2026-10-09&subject_id={self.other}", 900, 1)
        self.reconcile("start=2026-10-09&end=2026-10-09&subject_id=free", 60, 1)
        combined = self.report()
        self.assertEqual(len(combined["by_subject"]), 3)
        self.assertEqual(len([r for r in combined["by_subject"] if r["name"] == "Circuitos"]), 2)

    def seed_midnight_timer(self):
        with db.transaction(self.path) as c:
            with patch("tracker.timer.now", return_value="2026-10-10T02:40:00+00:00"):
                t = timer.start(c, {"subject_id": self.subject, "operation_key": "night"})
            for stamp, action in [
                ("2026-10-10T02:50:00+00:00", "pause"),
                ("2026-10-10T03:10:00+00:00", "resume"),
                ("2026-10-10T03:30:00+00:00", "finish"),
            ]:
                with patch("tracker.timer.now", return_value=stamp):
                    t = timer.transition(c, t["id"], action, {"version": t["version"]})
            return t["session_id"]

    def test_partial_midnight_filter_reconciles_liquid_and_breaks(self):
        self.seed_midnight_timer()
        self.manual(
            123, mode="times", started_at="2026-10-09T23:59:59", ended_at="2026-10-10T00:00:02"
        )
        before = self.reconcile("start=2026-10-09&end=2026-10-09", 601, 2)
        after = self.reconcile("start=2026-10-10&end=2026-10-10", 1202, 2)
        full = self.reconcile("start=2026-10-09&end=2026-10-10", 1803, 2)
        self.assertEqual(before["summary"]["period"]["break_seconds"], 600)
        self.assertEqual(after["summary"]["period"]["break_seconds"], 600)
        self.assertEqual(full["summary"]["period"]["break_seconds"], 1200)
        self.assertEqual(full["history"]["rows"][1]["total_effective_seconds"], 1800)

    def correction(self, ident, payload, status=200):
        with patch("tracker.corrections.now", return_value=STAMP):
            r = self.client.patch(f"/api/sessions/{ident}", json=payload)
        self.assertEqual(r.status_code, status, r.text)
        return r.json

    def test_correction_rebuilds_all_outputs_audits_and_is_idempotent(self):
        ident = self.seed_midnight_timer()
        payload = {
            "version": 1,
            "operation_key": "correction",
            "reason": "Relógio esquecido",
            "mode": "duration",
            "date": "2026-10-08",
            "duration_seconds": 907,
            "note": "Corrigida",
        }
        fixed = self.correction(ident, payload)
        self.assertEqual(fixed["correction_version"], 2)
        self.assertEqual(fixed["source"], "timer")
        self.assertIsNone(fixed["started_at"])
        self.correction(ident, payload)
        audit = self.client.get(f"/api/sessions/{ident}/corrections").json
        self.assertEqual(len(audit), 1)
        self.assertEqual(audit[0]["old_values"]["break_seconds"], 1200)
        self.assertEqual(audit[0]["new_values"]["effective_seconds"], 907)
        self.reconcile("start=2026-10-08&end=2026-10-08", 907, 1)
        self.reconcile("start=2026-10-09&end=2026-10-10", 0, 0)
        self.correction(ident, {**payload, "operation_key": "stale"}, 409)
        self.assertEqual(db.diagnostics(self.path)["integrity"], "ok")

    def test_note_only_keeps_pause_and_new_times_reallocate(self):
        ident = self.seed_midnight_timer()
        self.correction(
            ident,
            {
                "version": 1,
                "operation_key": "note",
                "reason": "Detalhar conteúdo",
                "note": "Lei de Ohm",
            },
        )
        self.reconcile("start=2026-10-09&end=2026-10-10", 1800, 1)
        self.correction(
            ident,
            {
                "version": 2,
                "operation_key": "time",
                "reason": "Ajustar horários",
                "mode": "times",
                "started_at": "2026-10-07T23:50:00",
                "ended_at": "2026-10-08T00:10:00",
                "subject_id": self.other,
            },
        )
        self.reconcile(f"start=2026-10-08&end=2026-10-08&course_id={self.other_course}", 600, 1)

    def test_invalid_correction_rolls_back_and_cannot_touch_other_session(self):
        s = self.manual()
        other = self.manual()
        payload = {
            "version": 1,
            "operation_key": "fix",
            "reason": "Ajuste",
            "mode": "duration",
            "date": "2026-10-09",
            "duration_seconds": 1200,
        }
        for fields in [
            {"reason": ""},
            {"duration_seconds": -1},
            {"date": "2026-11-01"},
            {"subject_id": True},
        ]:
            self.correction(s["id"], {**payload, **fields}, 400)
        self.assertEqual(
            self.client.get(f"/api/sessions/{s['id']}").json["effective_seconds"], 1800
        )
        self.assertEqual(self.client.get(f"/api/sessions/{s['id']}/corrections").json, [])
        self.correction(s["id"], payload)
        self.correction(other["id"], payload, 409)

    def test_csv_accents_quotes_newlines_and_formula_neutralization(self):
        self.manual(
            61, subject_id=None, title='=HYPERLINK("x")', note=' \t+SUM(1;2)\nAção "elétrica"'
        )
        r = self.client.get("/api/analytics/export.csv?start=2026-10-09&end=2026-10-09")
        parsed = list(csv.DictReader(io.StringIO(r.data.decode("utf-8-sig")), delimiter=";"))[0]
        self.assertTrue(parsed["Disciplina/estudo"].startswith("'="))
        self.assertTrue(parsed["Nota"].startswith("'+"))
        self.assertIn('Ação "elétrica"', parsed["Nota"])
        self.assertEqual(parsed["Líquido no período (s)"], "61")
        self.assertIn("attachment", r.headers["Content-Disposition"])

    def test_queries_do_not_grow_per_session_and_pagination_is_sql(self):
        for _ in range(35):
            self.manual(60)
        with db.read_transaction(self.path) as c:
            queries = []
            c.set_trace_callback(queries.append)
            data = analytics.report(c, {"start": "2026-10-09", "end": "2026-10-09"})
        self.assertEqual(len(data["history"]["rows"]), 20)
        self.assertEqual(len(queries), 10)  # 4 totals, 4 groupings, 1 history, rollback.
        self.assertTrue(any("LIMIT 20 OFFSET 0" in q for q in queries))

    def test_migration_backfills_legacy_timer_and_rejects_inconsistent_history(self):
        old = Path(self.temp.name) / "old.db"
        with patch("tracker.db.versions", return_value=db.versions()[:2]):
            db.initialize(old)
        with closing(sqlite3.connect(old)) as c:
            c.execute(
                "INSERT INTO timers(id,title,status,started_at,ended_at,operation_key) VALUES (1,'Antigo','completed','2026-10-10T02:50:00+00:00','2026-10-10T03:10:00+00:00','old')"
            )
            c.execute(
                "INSERT INTO timer_intervals(timer_id,kind,started_at,ended_at) VALUES (1,'focus','2026-10-10T02:50:00+00:00','2026-10-10T03:10:00+00:00')"
            )
            c.execute(
                "INSERT INTO study_sessions(timer_id,title,source,started_at,ended_at,local_date,effective_seconds,created_at) VALUES (1,'Antigo','timer','2026-10-10T02:50:00+00:00','2026-10-10T03:10:00+00:00','2026-10-09',1200,?)",
                (STAMP,),
            )
            c.commit()
        result = upgrade(old, Path(self.temp.name) / "backup")
        self.assertEqual(result["applied"], ["0003_analytics", "0004_topics", "0005_scheduled_break", "0006_rest_time"])
        with db.read_transaction(old) as c:
            self.assertEqual(
                [
                    r[0]
                    for r in c.execute(
                        "SELECT effective_seconds FROM session_days ORDER BY local_date"
                    )
                ],
                [600, 600],
            )
        # A mismatching legacy total must abort the copy rehearsal before touching the original.
        bad = Path(result["backup"])
        with closing(sqlite3.connect(bad)) as c:
            c.execute("UPDATE study_sessions SET effective_seconds=1201")
            c.commit()
        digest = hashlib.sha256(bad.read_bytes()).hexdigest()
        with self.assertRaisesRegex(RuntimeError, "Rateio"):
            upgrade(bad, Path(self.temp.name) / "failed-rehearsal")
        self.assertEqual(hashlib.sha256(bad.read_bytes()).hexdigest(), digest)
        with db.transaction(old) as c:
            c.execute("DELETE FROM session_days")
        with self.assertRaisesRegex(RuntimeError, "Rateio"):
            create_app(old)


if __name__ == "__main__":
    unittest.main()
