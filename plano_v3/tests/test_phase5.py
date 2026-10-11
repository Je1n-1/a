"""Backup, recuperação e regressão do cronograma; somente bases temporárias."""

from contextlib import closing
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from app import create_app
from tracker import db, storage
from tracker.grade_parser import _schedule_pdf


def content(path):
    with closing(sqlite3.connect(path)) as conn:
        names = [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
        ]
        return {
            name: conn.execute(f'SELECT * FROM "{name}" ORDER BY rowid').fetchall()
            for name in names
        }


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "data" / "test.db"
        db.initialize(self.path)
        self.client = create_app(self.path).test_client()
        self.client.post(
            "/api/sessions/manual",
            json={
                "operation_key": "test",
                "title": "Leitura",
                "mode": "duration",
                "date": "2026-10-09",
                "duration_seconds": 1800,
            },
        )

    def test_live_backup_recovery_exact_rows_and_active_unchanged(self):
        timer = self.client.post(
            "/api/timer", json={"operation_key": "active", "title": "Em estudo"}
        ).json
        before = content(self.path)
        response = self.client.post("/api/backups", json={"confirmed": True})
        self.assertEqual(response.status_code, 200)
        payload = response.data
        response.close()
        diagnostic = self.client.get("/api/diagnostics").json
        saved = Path(diagnostic["last_backup"]["path"])
        self.assertTrue(diagnostic["last_backup"]["available"])
        self.assertEqual(payload, saved.read_bytes())
        self.assertEqual(content(saved), before)
        restored = self.client.post(
            "/api/backups/recover",
            data={"confirmed": "true", "file": (io.BytesIO(payload), "backup.db")},
        )
        self.assertEqual(restored.status_code, 200, restored.text)
        self.assertFalse(restored.json["active_database_changed"])
        self.assertEqual(content(Path(restored.json["path"])), before)
        self.assertEqual(restored.json["effective_seconds"], 1800)
        self.assertEqual(content(self.path), before)
        self.assertEqual(self.client.get("/api/timer").json["id"], timer["id"])
        self.assertEqual(db.diagnostics(restored.json["path"])["integrity"], "ok")

    def test_uncommitted_transaction_is_not_in_backup(self):
        with closing(sqlite3.connect(self.path)) as writer:
            writer.execute(
                "INSERT INTO courses(name,created_at) VALUES ('Não confirmado','2026-10-10')"
            )
            target = self.root / "backup.db"
            storage.create_backup(self.path, target)
            self.assertEqual(content(target)["courses"], [])
            writer.rollback()

    def test_requires_confirmation_and_rejects_cross_origin(self):
        self.assertEqual(self.client.post("/api/backups", json={}).status_code, 400)
        self.assertEqual(self.client.post("/api/backups/recover", data={}).status_code, 400)
        self.assertEqual(
            self.client.post(
                "/api/backups", json={"confirmed": True}, headers={"Origin": "https://example.org"}
            ).status_code,
            403,
        )
        self.assertEqual(list(self.root.rglob("plano-*.db")), [])

    def test_invalid_legacy_and_inconsistent_copies_are_rejected(self):
        active_hash = hashlib.sha256(self.path.read_bytes()).hexdigest()
        legacy = self.root / "legacy.db"
        with closing(sqlite3.connect(legacy)) as conn:
            conn.execute("CREATE TABLE old(id INTEGER)")
            conn.commit()
        broken = self.root / "broken.db"
        storage.copy_database(self.path, broken)
        with closing(sqlite3.connect(broken)) as conn:
            conn.execute("DELETE FROM session_days")
            conn.commit()
        for payload in (b"not sqlite", legacy.read_bytes(), broken.read_bytes()):
            response = self.client.post(
                "/api/backups/recover",
                data={"confirmed": "true", "file": (io.BytesIO(payload), "backup.db")},
            )
            self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(list((self.root / "recovered").glob("*.db")), [])
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(), active_hash)

    def test_no_overwrite_failed_copy_and_metadata_recovery(self):
        target = self.root / "backup.db"
        storage.create_backup(self.path, target)
        saved = target.read_bytes()
        with self.assertRaises(FileExistsError):
            storage.create_backup(self.path, target)
        self.assertEqual(target.read_bytes(), saved)
        with self.assertRaises(Exception):
            storage.copy_database(self.path, self.path)
        with patch("tracker.storage.MAX_BACKUP_BYTES", 8):
            with self.assertRaisesRegex(Exception, "64 MB"):
                storage.recover_copy(self.path, io.BytesIO(saved))
        metadata = storage.metadata_path(self.path)
        metadata.write_text("{bad json", encoding="utf-8")
        self.assertIsNone(storage.last_backup(self.path))
        self.assertEqual(content(self.path)["study_sessions"], content(target)["study_sessions"])

    def test_backup_metadata_survives_application_restart(self):
        storage.create_backup(self.path, self.root / "saved.db")
        previous = self.client.get("/api/diagnostics").json["last_backup"]
        current = create_app(self.path).test_client().get("/api/diagnostics").json["last_backup"]
        self.assertEqual(previous, current)
        self.assertIsNotNone(current["created_at"])
        metadata = json.loads(storage.metadata_path(self.path).read_text(encoding="utf-8"))
        self.assertEqual(metadata["database"], str(self.path.resolve()))


class ScheduleRegression(unittest.TestCase):
    def test_glued_pdf_rows_preserve_both_subjects_and_workloads(self):
        result = _schedule_pdf(
            "INTRODUTÓRIO\nIntrodução à Tecnologia 40 40 0 10 06/04/2026 - seg. 15/05/2026 - sex.Saúde e Segurança no Trabalho 12 12 0 3 06/04/2026 - seg. 15/05/2026 - sex."
        )
        self.assertEqual(
            [(r["name"], r["workload_minutes"]) for r in result["items"]],
            [("Introdução à Tecnologia", 2400), ("Saúde e Segurança no Trabalho", 720)],
        )
        self.assertEqual(result["summary"]["recognized"], 2)
