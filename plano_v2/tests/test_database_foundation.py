import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from flask import Flask

from database import connection, migrations
from database.study_diagnostics import diagnose_studies
from routes.api import api


class DatabaseFoundationTest(unittest.TestCase):
    """Banco ativo, diagnóstico e reconciliação sem tocar no SQLite real."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / "plano-database-foundation.db"
        self.original_database_path = connection.DATABASE_PATH
        connection.DATABASE_PATH = self.database
        migrations.migrate(self.database)
        app = Flask(__name__)
        app.config["TESTING"] = True
        app.register_blueprint(api)
        self.client = app.test_client()

    def tearDown(self):
        connection.DATABASE_PATH = self.original_database_path
        self.temp.cleanup()

    def curriculum_in_progress_without_study(self):
        with connection.connect() as conn:
            formation_id = conn.execute(
                "INSERT INTO formacoes(name) VALUES ('Formação de diagnóstico')"
            ).lastrowid
            curriculum_id = conn.execute(
                """
                INSERT INTO disciplinas_grade(
                    formation_id,name,academic_status,workload_minutes,start_date,end_date
                ) VALUES (?, 'Disciplina antiga', 'in_progress', 1800, '2026-09-01', '2026-12-10')
                """,
                (formation_id,),
            ).lastrowid
        return int(formation_id), int(curriculum_id)

    def test_health_and_migration_status_use_the_single_overridden_database(self):
        health = connection.database_health()
        status = migrations.migration_status()

        self.assertEqual(Path(health["path"]), self.database.resolve())
        self.assertEqual(Path(status["database_path"]), self.database.resolve())
        self.assertEqual(health["integrity"], "ok")
        self.assertEqual(health["foreign_key_violations"], [])
        self.assertTrue(status["healthy"])
        self.assertEqual(status["current_version"], status["latest_available_version"])
        self.assertEqual(health["counts"]["formations"], 0)

    def test_migration_validation_rolls_back_an_unexpected_loss_of_preserved_rows(self):
        unsafe_database = Path(self.temp.name) / "unsafe-migration.db"
        all_migrations = migrations.available()
        first = [all_migrations[0]]
        unsafe = (2, "unsafe_preservation_test", "DELETE FROM formacoes;", "unsafe-checksum")
        with patch.object(migrations, "available", return_value=first):
            migrations.migrate(unsafe_database)
        with connection.connect(unsafe_database) as conn:
            conn.execute("INSERT INTO formacoes(name) VALUES ('Registro preservado')")

        with patch.object(migrations, "available", return_value=[*first, unsafe]):
            with self.assertRaisesRegex(RuntimeError, "reduziria registros preservados"):
                migrations.migrate(unsafe_database)
        with connection.connect(unsafe_database) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM formacoes").fetchone()[0], 1)

    def test_diagnosis_lists_legacy_missing_study_effort_deadline_and_topics(self):
        _, curriculum_id = self.curriculum_in_progress_without_study()

        response = self.client.get("/api/diagnostics/studies?date=2026-09-09")
        self.assertEqual(response.status_code, 200, response.get_json())
        payload = response.get_json()
        issue = next(
            row for row in payload["issues"]
            if row["kind"] == "in_progress_without_current_study" and row["curriculum_subject_id"] == curriculum_id
        )
        self.assertTrue(issue["suggested_values"]["create_current_study"])
        self.assertEqual(issue["suggested_values"]["required_study_minutes"], 1800)
        self.assertEqual(issue["suggested_values"]["deadline_date"], "2026-12-10")
        self.assertTrue(payload["safety"]["manual_blocks_preserved"])

    def test_reconciliation_is_preview_first_confirmed_and_idempotent(self):
        _, curriculum_id = self.curriculum_in_progress_without_study()
        request_data = {
            "items": [{
                "curriculum_subject_id": curriculum_id,
                "create_current_study": True,
                "start_date": "2026-09-09",
                "required_study_minutes": 2100,
                "deadline_date": "2026-12-20",
            }],
            "date": "2026-09-09",
        }

        preview = self.client.post("/api/diagnostics/studies", json=request_data)
        self.assertEqual(preview.status_code, 200, preview.get_json())
        self.assertFalse(preview.get_json()["applied"])
        with connection.connect() as conn:
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM materias_estudo WHERE curriculum_subject_id=?", (curriculum_id,)).fetchone()[0],
                0,
            )

        confirmed = self.client.post("/api/diagnostics/studies", json={**request_data, "confirm": True})
        self.assertEqual(confirmed.status_code, 200, confirmed.get_json())
        payload = confirmed.get_json()
        self.assertTrue(payload["applied"])
        self.assertEqual(len(payload["created_study_ids"]), 1)
        with connection.connect() as conn:
            current = conn.execute(
                "SELECT status,start_date,target_date FROM materias_estudo WHERE curriculum_subject_id=?",
                (curriculum_id,),
            ).fetchone()
            curriculum = conn.execute(
                "SELECT required_study_minutes,deadline_date FROM disciplinas_grade WHERE id=?",
                (curriculum_id,),
            ).fetchone()
        self.assertEqual(tuple(current), ("active", "2026-09-09", "2026-12-20"))
        self.assertEqual(tuple(curriculum), (2100, "2026-12-20"))

        repeated = self.client.post("/api/diagnostics/studies", json={**request_data, "confirm": True})
        self.assertEqual(repeated.status_code, 200, repeated.get_json())
        self.assertEqual(repeated.get_json()["created_study_ids"], [])
        with connection.connect() as conn:
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM materias_estudo WHERE curriculum_subject_id=?", (curriculum_id,)).fetchone()[0],
                1,
            )

    def test_past_manual_block_is_reported_but_never_reclassified_automatically(self):
        _, curriculum_id = self.curriculum_in_progress_without_study()
        created = self.client.post("/api/diagnostics/studies", json={
            "confirm": True,
            "date": "2026-09-09",
            "items": [{"curriculum_subject_id": curriculum_id, "create_current_study": True}],
        })
        self.assertEqual(created.status_code, 200, created.get_json())
        study_id = created.get_json()["created_study_ids"][0]
        with connection.connect() as conn:
            block_id = conn.execute(
                """
                INSERT INTO sessoes_planejadas(
                    study_subject_id,scheduled_date,start_time,planned_duration_minutes,status,source
                ) VALUES (?, '2026-09-08', '09:00', 50, 'planned', 'manual')
                """,
                (study_id,),
            ).lastrowid
            diagnosis = diagnose_studies(conn, "2026-09-09")
            block = next(row for row in diagnosis["issues"] if row["kind"] == "past_planned_block")
            self.assertEqual(block["source"], "manual")
            self.assertTrue(block["suggested_values"]["manual_block_preserved"])
            self.assertEqual(
                conn.execute("SELECT status FROM sessoes_planejadas WHERE id=?", (block_id,)).fetchone()[0],
                "planned",
            )

    def test_linked_canonical_study_is_not_reported_or_recreated_as_missing_current(self):
        with connection.connect() as conn:
            formation_id = conn.execute("INSERT INTO formacoes(name) VALUES ('Formação compartilhada')").lastrowid
            primary_id = conn.execute(
                "INSERT INTO disciplinas_grade(formation_id,name,academic_status) VALUES (?, 'Cálculo I', 'in_progress')",
                (formation_id,),
            ).lastrowid
            linked_id = conn.execute(
                "INSERT INTO disciplinas_grade(formation_id,name,academic_status) VALUES (?, 'Cálculo I equivalente', 'in_progress')",
                (formation_id,),
            ).lastrowid
            canonical_study_id = conn.execute(
                "INSERT INTO materias_estudo(origin,curriculum_subject_id,status) VALUES ('curriculum', ?, 'active')",
                (primary_id,),
            ).lastrowid
            conn.execute(
                "INSERT INTO curriculum_study_links(curriculum_subject_id,canonical_study_id) VALUES (?,?)",
                (linked_id, canonical_study_id),
            )

            diagnosis = diagnose_studies(conn, "2026-09-09")
            self.assertFalse(any(
                row["kind"] == "in_progress_without_current_study" and row["curriculum_subject_id"] == linked_id
                for row in diagnosis["issues"]
            ))

        response = self.client.post("/api/diagnostics/studies", json={
            "confirm": True,
            "date": "2026-09-09",
            "items": [{"curriculum_subject_id": linked_id, "create_current_study": True}],
        })
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()["created_study_ids"], [])
        with connection.connect() as conn:
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM materias_estudo WHERE curriculum_subject_id=?", (linked_id,)).fetchone()[0],
                0,
            )

    def test_combined_diagnostic_endpoint_exposes_no_data_content(self):
        response = self.client.get("/api/diagnostics")
        self.assertEqual(response.status_code, 200, response.get_json())
        payload = response.get_json()
        self.assertEqual(payload["database"]["integrity"], "ok")
        self.assertIn("current_version", payload["migrations"])
        self.assertIn("issues", payload["legacy_studies"])


if __name__ == "__main__":
    unittest.main()
