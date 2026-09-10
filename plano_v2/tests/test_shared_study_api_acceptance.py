"""Aceitação HTTP do vínculo explícito de uma disciplina compartilhada.

O teste usa somente a API pública, com SQLite descartável. Ele garante que a
equivalência não seja aplicada por semelhança sem confirmação e que o estudo
canônico continue preservado quando uma das formações é arquivada.
"""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from flask import Flask

from database import connection, migrations
from routes.api import api


class SharedStudyApiAcceptanceTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / "shared-study-api.db"
        self.original_database_path = connection.DATABASE_PATH
        connection.DATABASE_PATH = self.database
        migrations.migrate(self.database)

        self.app = Flask(__name__)
        self.app.config["TESTING"] = True
        self.app.register_blueprint(api)
        self.client = self.app.test_client()
        self.now = datetime(2026, 9, 9, 10, 30, tzinfo=ZoneInfo("America/Sao_Paulo"))
        self.clock = patch("services.core._local_now", side_effect=lambda: self.now)
        self.clock.start()

    def tearDown(self):
        self.clock.stop()
        connection.DATABASE_PATH = self.original_database_path
        self.temp.cleanup()

    def formation(self, name):
        response = self.client.post("/api/formations", json={"name": name})
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()

    def curriculum(self, formation, **overrides):
        response = self.client.post(
            f"/api/formations/{formation['id']}/curriculum",
            json={
                "name": "Cálculo I",
                "code": "MAT101",
                "workload_minutes": 3600,
                "academic_status": "not_available",
                **overrides,
            },
        )
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()

    def start(self, subject, **overrides):
        response = self.client.post(
            f"/api/curriculum/{subject['id']}/start",
            json={
                "start_date": "2026-09-09",
                "required_study_minutes": 240,
                "deadline_date": "2026-09-20",
                **overrides,
            },
        )
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()

    def test_shared_study_preview_merge_unlink_and_formation_archive_preserve_canonical_data(self):
        formation_a = self.formation("Engenharia de Computação")
        formation_b = self.formation("Engenharia Elétrica")
        subject_a = self.curriculum(formation_a, deadline_date="2026-09-20")
        subject_b = self.curriculum(formation_b, deadline_date="2026-09-16")
        started_a = self.start(subject_a, deadline_date="2026-09-20")
        started_b = self.start(subject_b, deadline_date="2026-09-16")
        canonical_study_id = started_a["study"]["id"]
        duplicate_study_id = started_b["study"]["id"]

        # GET somente sugere equivalência; não cria vínculo de modo implícito.
        initial = self.client.get(f"/api/curriculum/{subject_b['id']}/shared-study")
        self.assertEqual(initial.status_code, 200, initial.get_json())
        payload = initial.get_json()
        self.assertEqual(payload["link"]["kind"], "own")
        self.assertEqual(payload["link"]["study"]["id"], duplicate_study_id)
        self.assertFalse(payload["automatic_linking"])
        candidate = next(item for item in payload["candidates"] if item["curriculum_subject_id"] == subject_a["id"])
        self.assertEqual(candidate["canonical_study_id"], canonical_study_id)

        # POST sem confirmação é apenas a prévia da união: não arquiva nem
        # move o estudo próprio de B antes da escolha explícita.
        preview = self.client.post(
            f"/api/curriculum/{subject_b['id']}/shared-study",
            json={"canonical_study_id": canonical_study_id},
        )
        self.assertEqual(preview.status_code, 200, preview.get_json())
        self.assertFalse(preview.get_json()["applied"])
        self.assertTrue(preview.get_json()["requires_confirmation"])
        self.assertTrue(preview.get_json()["preview"]["requires_merge"])
        self.assertEqual(preview.get_json()["preview"]["source_current_studies"][0]["id"], duplicate_study_id)

        linked = self.client.post(
            f"/api/curriculum/{subject_b['id']}/shared-study",
            json={
                "canonical_study_id": canonical_study_id,
                "confirm": True,
                "merge_existing_study": True,
                "link_note": "Equivalência confirmada pelo usuário",
            },
        )
        self.assertEqual(linked.status_code, 200, linked.get_json())
        self.assertTrue(linked.get_json()["applied"])
        self.assertEqual(linked.get_json()["canonical_study_id"], canonical_study_id)
        self.assertTrue(linked.get_json()["academic_states_remain_independent"])
        self.assertEqual(linked.get_json()["merged"][0]["study_subject_id"], duplicate_study_id)

        state_b = self.client.get(f"/api/curriculum/{subject_b['id']}/shared-study")
        self.assertEqual(state_b.status_code, 200, state_b.get_json())
        self.assertEqual(state_b.get_json()["link"]["kind"], "linked")
        self.assertEqual(state_b.get_json()["link"]["study"]["id"], canonical_study_id)
        self.assertEqual(state_b.get_json()["link"]["study"]["status"], "active")

        # O estado acadêmico pertence à ocorrência curricular, não ao estudo
        # canônico. B pode ficar "disponível" sem alterar A, que permanece em
        # andamento e compartilha o mesmo progresso pessoal.
        changed_b = self.client.post(
            f"/api/curriculum/{subject_b['id']}/status",
            json={"academic_status": "available"},
        )
        self.assertEqual(changed_b.status_code, 200, changed_b.get_json())
        state_a = self.client.get(f"/api/curriculum/{subject_a['id']}")
        state_b_detail = self.client.get(f"/api/curriculum/{subject_b['id']}")
        self.assertEqual(state_a.status_code, 200, state_a.get_json())
        self.assertEqual(state_b_detail.status_code, 200, state_b_detail.get_json())
        self.assertEqual(state_a.get_json()["curriculum"]["academic_status"], "in_progress")
        self.assertEqual(state_b_detail.get_json()["curriculum"]["academic_status"], "available")

        # A agenda deve conter uma única demanda canônica, mesmo havendo duas
        # ocorrências curriculares vinculadas. O prazo ativo mais próximo de B
        # é usado pela demanda compartilhada.
        items = self.client.get("/api/planning/items?start=2026-09-09&end=2026-09-20")
        self.assertEqual(items.status_code, 200, items.get_json())
        planning_items = items.get_json()["items"]
        self.assertEqual(len(planning_items), 1)
        planned = planning_items[0]
        self.assertEqual(planned["current_study_id"], canonical_study_id)
        self.assertTrue(planned["is_shared_study"])
        self.assertEqual(planned["deadline_date"], "2026-09-16")
        self.assertEqual(
            {entry["curriculum_subject_id"] for entry in planned["shared_curriculum_subjects"]},
            {subject_a["id"], subject_b["id"]},
        )

        automatic = self.client.post("/api/planning/apply", json={"sessions": [{
            "study_subject_id": canonical_study_id,
            "scheduled_date": "2026-09-10",
            "start_time": "14:00",
            "planned_duration_minutes": 50,
            "selection_reason": "prova de preservação de vínculo",
        }]})
        self.assertEqual(automatic.status_code, 200, automatic.get_json())
        block = automatic.get_json()["created"][0]

        # DELETE também é em duas fases: a prévia não apaga o vínculo nem o
        # estudo compartilhado. A confirmação preserva o estudo; re-vinculamos
        # B para validar o caso de arquivamento de A abaixo.
        unlink_preview = self.client.delete(f"/api/curriculum/{subject_b['id']}/shared-study", json={})
        self.assertEqual(unlink_preview.status_code, 200, unlink_preview.get_json())
        self.assertFalse(unlink_preview.get_json()["applied"])
        self.assertTrue(unlink_preview.get_json()["requires_confirmation"])
        unlinked = self.client.delete(
            f"/api/curriculum/{subject_b['id']}/shared-study",
            json={"confirm": True, "note": "teste de reversibilidade"},
        )
        self.assertEqual(unlinked.status_code, 200, unlinked.get_json())
        self.assertTrue(unlinked.get_json()["applied"])
        self.assertTrue(unlinked.get_json()["preserved_shared_data"])
        self.assertEqual(self.client.get(f"/api/planned/{block['id']}").get_json()["status"], "planned")

        relinked = self.client.post(
            f"/api/curriculum/{subject_b['id']}/shared-study",
            json={"canonical_study_id": canonical_study_id, "confirm": True, "link_note": "restaurado"},
        )
        self.assertEqual(relinked.status_code, 200, relinked.get_json())
        self.assertTrue(relinked.get_json()["applied"])

        archived_a = self.client.post(
            f"/api/formations/{formation_a['id']}/archive",
            json={"study_policy": "archive_studies"},
        )
        self.assertEqual(archived_a.status_code, 200, archived_a.get_json())
        archive_result = archived_a.get_json()
        self.assertEqual(archive_result["archived_studies"]["count"], 0)
        self.assertEqual(archive_result["preserved_shared_studies"]["ids"], [canonical_study_id])
        self.assertEqual(archive_result["cancelled_future_blocks"]["count"], 0)

        after_archive = self.client.get(f"/api/curriculum/{subject_b['id']}/shared-study")
        self.assertEqual(after_archive.status_code, 200, after_archive.get_json())
        self.assertEqual(after_archive.get_json()["link"]["study"]["status"], "active")
        self.assertIsNone(after_archive.get_json()["link"]["study"]["archived_at"])
        self.assertEqual(self.client.get(f"/api/planned/{block['id']}").get_json()["status"], "planned")
        # A formação proprietária pode estar arquivada, mas B continua ativa:
        # a única demanda canônica ainda precisa chegar ao Planejamento.
        visible_after_archive = self.client.get("/api/planning/items?start=2026-09-09&end=2026-09-20")
        self.assertEqual(visible_after_archive.status_code, 200, visible_after_archive.get_json())
        self.assertEqual(
            [row["current_study_id"] for row in visible_after_archive.get_json()["items"]],
            [canonical_study_id],
        )


if __name__ == "__main__":
    unittest.main()
