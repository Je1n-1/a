import unittest

from services.calendar_export import calendar_ics


class CalendarExportTest(unittest.TestCase):
    def test_exports_timed_block_with_stable_uid_and_escaped_content(self):
        payload = calendar_ics([{
            "id": 42,
            "scheduled_date": "2026-09-09",
            "start_time": "13:13",
            "planned_duration_minutes": 50,
            "subject_name": "Circuitos, I",
            "topic_name": "Leis; de Kirchhoff",
            "formation_name": "Eletrotécnica",
            "selection_reason": "Prazo próximo",
        }], timezone="America/Sao_Paulo")
        self.assertTrue(payload.startswith("BEGIN:VCALENDAR\r\n"))
        self.assertIn("UID:planned-42@plano.local", payload)
        self.assertIn("SUMMARY:Circuitos\\, I — Leis\\; de Kirchhoff", payload)
        self.assertIn("DTSTART;TZID=America/Sao_Paulo:20260909T131300", payload)
        self.assertIn("DTEND;TZID=America/Sao_Paulo:20260909T140300", payload)
        self.assertTrue(payload.endswith("END:VCALENDAR\r\n"))

    def test_exports_block_without_hour_as_all_day_event(self):
        payload = calendar_ics([{
            "id": 7, "scheduled_date": "2026-09-09", "planned_duration_minutes": 30,
            "subject_name": "Leitura",
        }], timezone="America/Sao_Paulo")
        self.assertIn("DTSTART;VALUE=DATE:20260909", payload)
        self.assertIn("DTEND;VALUE=DATE:20260910", payload)


if __name__ == "__main__":
    unittest.main()
