import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from flask import Flask

from database import connection
from database.migrations import migrate
from routes.calendar import calendar_api


class CalendarFeedTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / "calendar-feed.db"
        self.previous = connection.DATABASE_PATH
        connection.DATABASE_PATH = self.database
        migrate(self.database)
        self.clock = patch("services.core._local_now", return_value=datetime(2026, 9, 9, 10, 0))
        self.clock.start()
        app = Flask(__name__)
        app.config["TESTING"] = True
        app.register_blueprint(calendar_api)
        self.client = app.test_client()
        with connection.connect() as conn:
            formation = conn.execute("INSERT INTO formacoes(name) VALUES ('Eletrotécnica')").lastrowid
            subject = conn.execute(
                "INSERT INTO disciplinas_grade(formation_id,name,academic_status) VALUES (?,?,'in_progress')",
                (formation, "Circuitos"),
            ).lastrowid
            study = conn.execute(
                "INSERT INTO materias_estudo(origin,curriculum_subject_id,status) VALUES ('curriculum',?,'active')",
                (subject,),
            ).lastrowid
            conn.execute(
                """
                INSERT INTO sessoes_planejadas(study_subject_id,scheduled_date,start_time,planned_duration_minutes,status,source)
                VALUES (?, '2026-09-10', '13:13', 50, 'planned', 'automatic')
                """,
                (study,),
            )
            conn.execute(
                """
                INSERT INTO sessoes_planejadas(study_subject_id,scheduled_date,start_time,planned_duration_minutes,status,source)
                VALUES (?, '2026-09-10', '15:00', 50, 'cancelled', 'automatic')
                """,
                (study,),
            )

    def tearDown(self):
        self.clock.stop()
        connection.DATABASE_PATH = self.previous
        self.temp.cleanup()

    def test_exports_active_blocks_only(self):
        response = self.client.get("/api/calendar.ics?start=2026-09-09&end=2026-09-11")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "text/calendar")
        payload = response.get_data(as_text=True)
        self.assertIn("SUMMARY:Circuitos", payload)
        self.assertIn("DTSTART;TZID=America/Sao_Paulo:20260910T131300", payload)
        self.assertEqual(payload.count("BEGIN:VEVENT"), 1)


if __name__ == "__main__":
    unittest.main()
