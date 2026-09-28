"""Cenários de aceitação da jornada curricular → planejamento → foco.

Estes testes exercitam somente contratos HTTP públicos contra um SQLite
temporário. Eles mantêm o relógio congelado em America/Sao_Paulo para impedir
que a data UTC da máquina altere o resultado de "Hoje" ou do planejamento.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from flask import Flask

from config import LOCAL_TIMEZONE, TIMEZONE
from database import connection, migrations
from routes.api import api


class PlanningAcceptanceContractTest(unittest.TestCase):
    """Aceitação de fluxos essenciais sem tocar no banco real da aplicação."""

    sao_paulo = LOCAL_TIMEZONE

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / "acceptance-planning.db"
        self.original_database_path = connection.DATABASE_PATH
        connection.DATABASE_PATH = self.database
        migrations.migrate(self.database)

        self.app = Flask(__name__)
        self.app.config["TESTING"] = True
        self.app.register_blueprint(api)
        self.client = self.app.test_client()

        # Quarta-feira de manhã no Brasil. Não há dependência do relógio UTC
        # do servidor de testes, inclusive quando avaliamos o restante do dia.
        self.now = datetime(2026, 9, 9, 10, 30, tzinfo=self.sao_paulo)
        self.clock = patch("services.core._local_now", side_effect=lambda: self.now)
        self.clock.start()

    def tearDown(self):
        self.clock.stop()
        connection.DATABASE_PATH = self.original_database_path
        self.temp.cleanup()

    def set_now(self, value: datetime):
        self.assertEqual(value.tzinfo, self.sao_paulo)
        self.now = value

    def formation(self, name="Engenharia de Computação"):
        response = self.client.post("/api/formations", json={"name": name})
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()

    def curriculum(self, formation, name="Sistemas Operacionais", **values):
        response = self.client.post(
            f"/api/formations/{formation['id']}/curriculum",
            json={"name": name, "academic_status": "not_available", **values},
        )
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()

    def weekly_availability(self, weekday, start_time, end_time):
        response = self.client.post(
            "/api/availability",
            json={"weekday": weekday, "start_time": start_time, "end_time": end_time},
        )
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()

    def start_curriculum(self, curriculum, **values):
        response = self.client.post(f"/api/curriculum/{curriculum['id']}/start", json=values)
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()

    def personal_study(self, name="Estudo paralelo", **values):
        response = self.client.post("/api/studies", json={"personal_name": name, **values})
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()

    def topic(self, study, name="Tópico principal"):
        response = self.client.post(f"/api/studies/{study['id']}/topics", json={"name": name})
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()

    def planned(self, study, topic, date, start_time, minutes=50):
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
        return response.get_json()

    def test_not_available_is_searchable_but_not_a_demand_until_started_with_provisional_profile(self):
        self.assertEqual(TIMEZONE, "America/Sao_Paulo")
        formation = self.formation()
        subject = self.curriculum(formation, "Sistemas Operacionais")
        self.weekly_availability(2, "10:00", "12:00")

        # A disciplina futura continua encontrável na grade/pesquisa, mas não
        # aparece como sessão proposta nem como demanda obrigatória.
        search = self.client.get("/api/search?q=sistemas%20operacionais")
        self.assertEqual(search.status_code, 200, search.get_json())
        self.assertIn(subject["id"], {row["id"] for row in search.get_json()["curriculum"]})
        preview = self.client.post(
            "/api/planning/generate-smart",
            json={"start": "2026-09-09", "days": 1},
        )
        self.assertEqual(preview.status_code, 200, preview.get_json())
        self.assertFalse(preview.get_json()["sessions"])
        future = next(
            row for row in preview.get_json()["diagnostics"]["items"]
            if row.get("curriculum_subject_id") == subject["id"]
        )
        self.assertEqual(future["state"], "future")
        self.assertEqual(future["reason_codes"], ["not_available_future"])

        started = self.start_curriculum(subject)
        self.assertTrue(started["created"])
        self.assertEqual(started["curriculum"]["academic_status"], "in_progress")
        self.assertEqual(started["study"]["status"], "active")
        self.assertTrue(started["profile"]["effort_is_provisional"])
        self.assertTrue(started["profile"]["deadline_is_provisional"])
        self.assertGreater(started["profile"]["required_study_minutes"], 0)
        self.assertEqual(started["profile"]["start_date"], "2026-09-09")

        # A mesma fonte canônica alimenta Planejamento, Estudos atuais e Hoje.
        studies = self.client.get("/api/studies?visibility=all")
        self.assertEqual(studies.status_code, 200, studies.get_json())
        self.assertIn(started["study"]["id"], {row["id"] for row in studies.get_json()})
        items = self.client.get("/api/planning/items?start=2026-09-09&end=2026-11-04")
        self.assertEqual(items.status_code, 200, items.get_json())
        item = next(row for row in items.get_json()["items"] if row["current_study_id"] == started["study"]["id"])
        self.assertEqual(item["subject_id"], subject["id"])
        self.assertEqual(item["canonical_subject_id"], subject["id"])
        self.assertEqual(item["academic_status"], "in_progress")
        self.assertTrue(item["eligible_for_planning"])
        self.assertTrue(item["effort_is_provisional"])
        self.assertTrue(item["deadline_is_provisional"])
        self.assertEqual(item["time_remaining_minutes"], started["profile"]["required_study_minutes"])

        today = self.client.get("/api/today")
        self.assertEqual(today.status_code, 200, today.get_json())
        self.assertEqual(today.get_json()["date"], "2026-09-09")
        self.assertEqual(today.get_json()["capacity_minutes"], 90)
        recommendation = self.client.get("/api/recommendation")
        self.assertEqual(recommendation.status_code, 200, recommendation.get_json())
        self.assertEqual(recommendation.get_json()["study_subject"]["id"], started["study"]["id"])

    def test_reopening_preserves_explicit_profile_and_normalized_planning_dto(self):
        subject = self.curriculum(self.formation(), "Banco de Dados", workload_minutes=3600)
        started = self.start_curriculum(
            subject,
            start_date="2026-09-09",
            target_date="2026-11-30",  # alias público aceito pelo início compacto
            required_study_minutes=2520,
            priority=4,
            preferred_block_minutes=75,
            allowed_weekdays=[0, 2, 4],
        )
        self.assertFalse(started["profile"]["effort_is_provisional"])
        self.assertFalse(started["profile"]["deadline_is_provisional"])

        reopened = self.client.get(f"/api/curriculum/{subject['id']}/schedule-settings")
        self.assertEqual(reopened.status_code, 200, reopened.get_json())
        persisted = reopened.get_json()["curriculum"]
        self.assertEqual(persisted["required_study_minutes"], 2520)
        self.assertEqual(persisted["deadline_date"], "2026-11-30")
        self.assertEqual(persisted["priority_base"], 4)
        self.assertEqual(persisted["preferred_block_minutes"], 75)
        self.assertEqual(json.loads(persisted["allowed_weekdays"]), [0, 2, 4])

        # Repetir o início não cria outro estudo nem troca os campos já salvos.
        repeated = self.start_curriculum(subject)
        self.assertFalse(repeated["created"])
        self.assertTrue(repeated["reused"])
        self.assertEqual(repeated["study"]["id"], started["study"]["id"])
        self.assertEqual(repeated["profile"]["required_study_minutes"], 2520)
        self.assertEqual(repeated["profile"]["deadline_date"], "2026-11-30")

        planning = self.client.get("/api/planning/items?start=2026-09-09&end=2026-11-30")
        self.assertEqual(planning.status_code, 200, planning.get_json())
        item = next(row for row in planning.get_json()["items"] if row["current_study_id"] == started["study"]["id"])
        for field in (
            "subject_id", "current_study_id", "canonical_subject_id", "origin", "formations",
            "academic_status", "study_status", "curricular_workload_minutes", "estimated_effort_minutes",
            "time_real_minutes", "time_remaining_minutes", "time_future_planned_minutes",
            "time_unallocated_minutes", "start_date", "deadline_date", "priority_base",
            "priority_effective", "preferred_block_minutes", "allowed_weekdays", "topics",
            "evaluations", "eligible_for_planning", "planning_blockers",
        ):
            self.assertIn(field, item)
        self.assertEqual(item["estimated_effort_minutes"], 2520)
        self.assertEqual(item["deadline_date"], "2026-11-30")
        self.assertEqual(item["allowed_weekdays"], [0, 2, 4])

    def test_availability_supports_weekly_default_date_replacement_and_date_ranges(self):
        # Quarta recorrente 14:00–17:30; a alteração de hoje deve substituí-la
        # sem apagar a regra semanal de origem.
        self.weekly_availability(2, "14:00", "17:30")
        baseline = self.client.get("/api/availability/days/2026-09-09")
        self.assertEqual(baseline.status_code, 200, baseline.get_json())
        self.assertEqual(baseline.get_json()["windows"], [[840, 1050]])

        replaced = self.client.post("/api/availability/intervals", json={
            "start_date": "2026-09-09", "end_date": "2026-09-09",
            "start_time": "19:00", "end_time": "21:00", "kind": "replace",
        })
        self.assertEqual(replaced.status_code, 200, replaced.get_json())
        added = self.client.post("/api/availability/intervals", json={
            "start_date": "2026-09-09", "end_date": "2026-09-09",
            "start_time": "13:00", "end_time": "14:00", "kind": "available",
        })
        self.assertEqual(added.status_code, 200, added.get_json())
        changed_today = self.client.get("/api/availability/days/2026-09-09")
        self.assertEqual(changed_today.status_code, 200, changed_today.get_json())
        self.assertEqual(changed_today.get_json()["windows"], [[780, 840], [1140, 1260]])
        self.assertFalse(changed_today.get_json()["uses_weekly_default"])

        # Uma regra de intervalo é herdada por dias sem recorrência; ela não se
        # confunde com uma exceção criada só para a data atual.
        ranged = self.client.post("/api/availability/intervals", json={
            "start_date": "2026-09-10", "end_date": "2026-09-20",
            "start_time": "19:00", "end_time": "20:00", "kind": "available",
        })
        self.assertEqual(ranged.status_code, 200, ranged.get_json())
        inherited = self.client.get("/api/availability/days/2026-09-15")
        self.assertEqual(inherited.status_code, 200, inherited.get_json())
        self.assertEqual(inherited.get_json()["windows"], [[1140, 1200]])

        reset = self.client.post("/api/availability/days/2026-09-09/reset")
        self.assertEqual(reset.status_code, 200, reset.get_json())
        self.assertTrue(reset.get_json()["weekly_restored"])
        restored = self.client.get("/api/availability/days/2026-09-09")
        self.assertEqual(restored.status_code, 200, restored.get_json())
        self.assertEqual(restored.get_json()["windows"], [[840, 1050]])

    def test_capacity_is_net_of_breaks_for_a_three_and_half_hour_window(self):
        saved = self.client.put("/api/settings", json={
            "default_session_minutes": 50,
            "planning_break_minutes": 10,
            "minimum_session_minutes": 25,
            "maximum_session_minutes": 120,
        })
        self.assertEqual(saved.status_code, 200, saved.get_json())
        self.weekly_availability(2, "14:00", "17:30")

        capacity = self.client.get("/api/planning/capacity?start=2026-09-09&end=2026-09-09")
        self.assertEqual(capacity.status_code, 200, capacity.get_json())
        values = capacity.get_json()
        self.assertEqual(values["gross_capacity_minutes"], 210)
        self.assertEqual(values["capacity_minutes"], 210)
        # 50 + 10 + 50 + 10 + 50 + 10 + 30: a última pausa não é inventada.
        self.assertEqual(values["net_capacity_minutes"], 180)
        self.assertEqual(values["net_free_minutes"], 180)
        self.assertEqual(values["capacity_by_day"][0]["break_minutes"], 10)

    def test_forty_two_hours_are_spread_without_duplicate_automatic_blocks_and_manual_is_preserved(self):
        subject = self.curriculum(self.formation(), "Algoritmos")
        started = self.start_curriculum(
            subject,
            start_date="2026-09-09",
            deadline_date="2026-10-20",  # 42 dias incluindo a data inicial
            required_study_minutes=42 * 60,
            preferred_block_minutes=60,
        )
        study = started["study"]
        topic = self.topic(study, "Estruturas de dados")
        for weekday in range(7):
            self.weekly_availability(weekday, "14:00", "15:00")

        manual = self.planned(study, topic, "2026-09-09", "14:00", 60)
        self.assertEqual(manual["source"], "manual")
        preview = self.client.post(
            "/api/planning/generate-smart",
            json={"start": "2026-09-09", "days": 42},
        )
        self.assertEqual(preview.status_code, 200, preview.get_json())
        proposals = preview.get_json()["sessions"]
        self.assertEqual(len(proposals), 41)
        self.assertEqual(sum(row["planned_duration_minutes"] for row in proposals), 41 * 60)
        self.assertEqual(len({row["scheduled_date"] for row in proposals}), 41)
        self.assertNotIn("2026-09-09", {row["scheduled_date"] for row in proposals})

        first_apply = self.client.post("/api/planning/apply", json={"sessions": proposals})
        self.assertEqual(first_apply.status_code, 200, first_apply.get_json())
        self.assertEqual(len(first_apply.get_json()["created"]), 41)
        self.assertTrue(first_apply.get_json()["preserved_manual_blocks"])
        second_apply = self.client.post("/api/planning/apply", json={"sessions": proposals})
        self.assertEqual(second_apply.status_code, 200, second_apply.get_json())
        self.assertEqual(second_apply.get_json()["created"], [])
        self.assertEqual(len(second_apply.get_json()["existing"]), 41)

        saved = self.client.get("/api/planned?start=2026-09-09&end=2026-10-20")
        self.assertEqual(saved.status_code, 200, saved.get_json())
        blocks = saved.get_json()
        self.assertEqual(len(blocks), 42)
        self.assertEqual(sum(row["planned_duration_minutes"] for row in blocks), 42 * 60)
        self.assertEqual(len({row["scheduled_date"] for row in blocks}), 42)
        preserved = next(row for row in blocks if row["id"] == manual["id"])
        self.assertEqual(preserved["source"], "manual")

        # Uma nova prévia reconhece a cobertura existente em vez de repetir o
        # plano ou apagar o bloco que o usuário criou manualmente.
        repeated_preview = self.client.post(
            "/api/planning/generate-smart",
            json={"start": "2026-09-09", "days": 42},
        )
        self.assertEqual(repeated_preview.status_code, 200, repeated_preview.get_json())
        self.assertEqual(repeated_preview.get_json()["sessions"], [])
        self.assertEqual(self.client.get(f"/api/planned/{manual['id']}").get_json()["source"], "manual")

    def test_past_block_is_not_future_allocation_and_focus_finish_is_visible_to_other_api_consumers(self):
        study = self.personal_study(
            "Leitura técnica",
            required_study_minutes=120,
            start_date="2026-09-08",
            target_date="2026-09-20",
            preferred_block_minutes=50,
        )
        topic = self.topic(study, "Concorrência")
        past = self.planned(study, topic, "2026-09-08", "14:00", 50)

        before = self.client.get("/api/planning/items?start=2026-09-09&end=2026-09-20")
        self.assertEqual(before.status_code, 200, before.get_json())
        item_before = next(row for row in before.get_json()["items"] if row["current_study_id"] == study["id"])
        self.assertEqual(item_before["time_future_planned_minutes"], 0)
        capacity = self.client.get("/api/planning/capacity?start=2026-09-08&end=2026-09-09")
        self.assertEqual(capacity.status_code, 200, capacity.get_json())
        self.assertEqual(capacity.get_json()["planned_minutes"], 0)
        self.assertEqual(capacity.get_json()["past_unrealized_minutes"], 50)
        self.assertIn(past["id"], capacity.get_json()["past_unrealized_blocks"])

        current = self.planned(study, topic, "2026-09-09", "14:00", 50)
        started = self.client.post("/api/focus/sessions", json={"planned_session_id": current["id"]})
        self.assertEqual(started.status_code, 200, started.get_json())
        focus = started.get_json()["session"]
        self.assertEqual(focus["status"], "running")

        # Outra aba/cliente recebe a mesma sessão persistida, em vez de abrir
        # um segundo cronômetro local independente.
        second_client = self.app.test_client()
        observed = second_client.get("/api/focus/active")
        self.assertEqual(observed.status_code, 200, observed.get_json())
        self.assertEqual(observed.get_json()["id"], focus["id"])

        self.set_now(datetime(2026, 9, 9, 10, 50, tzinfo=self.sao_paulo))
        finished = second_client.post(
            f"/api/focus/sessions/{focus['id']}/finish",
            json={"version": focus["version"], "topic_outcome": "continue"},
        )
        self.assertEqual(finished.status_code, 200, finished.get_json())
        self.assertEqual(finished.get_json()["study_session"]["duration_seconds"], 20 * 60)
        self.assertIsNone(self.client.get("/api/focus/active").get_json())

        # Planejamento, Hoje, Histórico e Análises leem o mesmo estado salvo.
        self.assertEqual(self.client.get(f"/api/planned/{current['id']}").get_json()["status"], "completed")
        history = self.client.get("/api/sessions?start=2026-09-09&end=2026-09-09")
        self.assertEqual(history.status_code, 200, history.get_json())
        self.assertEqual(history.get_json()[0]["id"], finished.get_json()["study_session"]["id"])
        after = self.client.get("/api/planning/items?start=2026-09-09&end=2026-09-20")
        self.assertEqual(after.status_code, 200, after.get_json())
        item_after = next(row for row in after.get_json()["items"] if row["current_study_id"] == study["id"])
        self.assertEqual(item_after["time_real_minutes"], 20)
        self.assertEqual(item_after["time_future_planned_minutes"], 0)
        today = self.client.get("/api/today")
        self.assertEqual(today.status_code, 200, today.get_json())
        self.assertEqual(today.get_json()["studied_minutes"], 20)
        analytics = self.client.get("/api/analytics")
        self.assertEqual(analytics.status_code, 200, analytics.get_json())
        self.assertEqual(analytics.get_json()["today_seconds"], 20 * 60)
        self.assertEqual(analytics.get_json()["completed_planned_without_real_session"], 0)


if __name__ == "__main__":
    unittest.main()
