"""Contrato do carregamento consolidado, sobre banco temporário."""

from pathlib import Path
import tempfile
import unittest

from app import create_app
from tracker import db


class TodayOverview(unittest.TestCase):
    def test_overview_matches_existing_contracts_and_omits_optional_catalog(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.db"
            db.initialize(path)
            client = create_app(path).test_client()
            course = client.post("/api/courses", json={"name": "Teste isolado"}).json
            client.post("/api/subjects", json={"course_id": course["id"], "name": "Matéria"})
            client.post(
                "/api/sessions/manual",
                json={
                    "operation_key": "phase4",
                    "mode": "duration",
                    "date": "2026-10-09",
                    "duration_seconds": 1800,
                    "title": "Leitura",
                },
            )
            data = client.get("/api/today").json
            for key, route in {
                "courses": "/courses",
                "subjects": "/subjects",
                "timer": "/timer",
                "recent": "/sessions/recent",
                "summary": "/sessions/summary",
            }.items():
                self.assertEqual(data[key], client.get("/api" + route).json)
            self.assertEqual(len(data["recent"]), 1)
            compact = client.get("/api/today?catalog=0").json
            self.assertEqual(set(compact), {"timer", "recent", "summary"})
            self.assertEqual(compact, {key: data[key] for key in compact})
