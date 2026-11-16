"""Roteiros disciplinares: testes exclusivamente em banco temporário isolado."""

import tempfile
import unittest
from pathlib import Path

from app import create_app
from tracker import db


def document(topics=None, title="Roteiro de instalações"):
    topics = topics or [{"key": "lei_ohm", "title": "Lei de Ohm", "description": "Aplicar a relação entre tensão, corrente e resistência.", "estimated_minutes": 60, "source_reference": "Plano, unidade 1", "existing_topic_id": None}]
    return {"schema_version": 1, "kind": "subject_study_route", "route": {"title": title, "description": "Do documento da disciplina", "modules": [{"key": "fundamentos", "title": "Fundamentos", "description": "Base", "topics": topics}]}}


class StudyRouteFlows(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "isolated.db"
        db.initialize(self.path)
        self.client = create_app(self.path).test_client()
        self.course = self.post("/courses", {"name": "Eletrotécnica", "institution": "SENAI"})["id"]
        self.subject = self.post("/subjects", {"course_id": self.course, "name": "Circuitos Elétricos", "code": "EL-1", "period": "1º", "workload_minutes": 6000})["id"]
        self.other = self.post("/subjects", {"course_id": self.course, "name": "Eletrônica"})["id"]

    def post(self, route, data, status=200):
        response = self.client.post("/api" + route, json=data)
        self.assertEqual(response.status_code, status, response.json)
        return response.json

    def test_preview_is_read_only_then_confirm_creates_topics(self):
        before = self.client.get("/api/topics?subject_id=" + str(self.subject)).json
        preview = self.post(f"/subjects/{self.subject}/study-route/preview", {"document": document()})
        self.assertEqual(preview["warnings"], [])
        self.assertEqual(self.client.get("/api/topics?subject_id=" + str(self.subject)).json, before)
        result = self.post(f"/subjects/{self.subject}/study-route", {"document": document(), "expected_version": 0, "operation_key": "route-import-0001"})
        self.assertEqual(result["route"]["module_count"], 1)
        self.assertEqual(result["route"]["topic_count"], 1)
        topic = result["route"]["modules"][0]["topics"][0]
        self.assertEqual((topic["name"], topic["estimated_minutes"], topic["source_reference"]), ("Lei de Ohm", 60, "Plano, unidade 1"))
        self.assertEqual(len(self.client.get("/api/topics?subject_id=" + str(self.subject)).json), 1)

    def test_exact_existing_topic_reused_and_history_status_preserved(self):
        existing = self.post("/topics", {"subject_id": self.subject, "name": "Lei de Ohm"})
        existing = self.client.patch(f"/api/topics/{existing['id']}", json={"version": 1, "completed": True, "needs_review": True}).json
        session = self.post("/sessions/manual", {"operation_key": "route-session-01", "subject_id": self.subject, "topic_id": existing["id"], "session_kind": "study", "mode": "duration", "date": "2026-11-10", "duration_seconds": 1200})
        result = self.post(f"/subjects/{self.subject}/study-route", {"document": document(), "expected_version": 0, "operation_key": "route-import-0002"})
        routed = result["route"]["modules"][0]["topics"][0]
        self.assertEqual(routed["id"], existing["id"])
        self.assertEqual((routed["completed"], routed["needs_review"], routed["effective_seconds"], routed["sessions"]), (1, 1, 1200, 1))
        self.assertEqual(self.client.get(f"/api/sessions/{session['id']}").json["topic_name"], "Lei de Ohm")

    def test_modules_and_topics_keep_imported_order(self):
        doc = document(title="Ordenado")
        doc["route"]["modules"] = [
            {"key":"segundo", "title":"Segundo no nome", "topics":[{"key":"topico_b", "title":"Tópico B"}]},
            {"key":"primeiro", "title":"Primeiro no nome", "topics":[{"key":"topico_a", "title":"Tópico A"}]},
        ]
        result = self.post(f"/subjects/{self.subject}/study-route", {"document":doc, "expected_version":0, "operation_key":"route-order-0001"})
        self.assertEqual([m["title"] for m in result["route"]["modules"]], ["Segundo no nome", "Primeiro no nome"])
        self.assertEqual([m["topics"][0]["name"] for m in result["route"]["modules"]], ["Tópico B", "Tópico A"])

    def test_foreign_topic_id_rejected_and_preview_has_no_writes(self):
        foreign = self.post("/topics", {"subject_id": self.other, "name": "Lei de Ohm"})
        doc = document([{"key": "t1", "title": "Lei de Ohm", "existing_topic_id": foreign["id"]}])
        self.post(f"/subjects/{self.subject}/study-route/preview", {"document": doc}, 400)
        self.assertEqual(self.client.get("/api/topics?subject_id=" + str(self.subject)).json, [])

    def test_contract_rejects_invalid_shapes_untrusted_state_and_bounds(self):
        invalid = [
            {"schema_version": 2, "kind": "subject_study_route", "route": {}},
            {"schema_version": 1, "kind": "subject_study_route", "route": {"title": "x", "modules": []}},
            document([{ "key": "x", "title": "x", "completed": True }]),
            document([{ "key": "x", "title": "x", "estimated_minutes": True }]),
            document([{ "key": "bad key", "title": "x" }]),
            document([{ "key": "x", "title": "x" }, {"key": "x", "title": "y"}]),
        ]
        for data in invalid:
            with self.subTest(data=data):
                self.post(f"/subjects/{self.subject}/study-route/preview", {"document": data}, 400)
        self.post(f"/subjects/{self.subject}/study-route/preview", {"document": "{"}, 400)

    def test_ambiguity_requires_explicit_choice_and_internal_duplicates_are_reported(self):
        candidate = self.post("/topics", {"subject_id": self.subject, "name": "Lei de Ohm aplicada"})
        doc = document([{ "key": "lei_ohm", "title": "Lei de Ohm aplicadas" }])
        preview = self.post(f"/subjects/{self.subject}/study-route/preview", {"document": doc})
        self.assertTrue(preview["has_unresolved_choices"])
        self.post(f"/subjects/{self.subject}/study-route", {"document": doc, "expected_version": 0, "operation_key": "route-import-0003"}, 400)
        self.assertEqual(len(self.client.get("/api/topics?subject_id=" + str(self.subject)).json), 1)
        decisions = {"lei_ohm": {"action": "existing", "topic_id": candidate["id"]}}
        result = self.post(f"/subjects/{self.subject}/study-route", {"document": doc, "decisions": decisions, "expected_version": 0, "operation_key": "route-import-0004"})
        self.assertEqual(result["route"]["modules"][0]["topics"][0]["id"], candidate["id"])
        dup = document([{ "key": "a", "title": "Lei de Ohm" }, {"key": "b", "title": "lei-de-ohm"}])
        self.assertEqual([w["type"] for w in self.post(f"/subjects/{self.subject}/study-route/preview", {"document": dup})["warnings"]], ["duplicate_in_json"])

    def test_update_preserves_removed_topics_sessions_and_replay_is_idempotent(self):
        first = self.post(f"/subjects/{self.subject}/study-route", {"document": document(), "expected_version": 0, "operation_key": "route-import-0005"})
        topic = first["route"]["modules"][0]["topics"][0]
        session = self.post("/sessions/manual", {"operation_key": "route-session-02", "subject_id": self.subject, "topic_id": topic["id"], "session_kind": "study", "mode": "duration", "date": "2026-11-11", "duration_seconds": 1800})
        again = self.post(f"/subjects/{self.subject}/study-route", {"document": document(), "expected_version": 0, "operation_key": "route-import-0005"})
        self.assertTrue(again["idempotent_replay"])
        self.assertEqual(again["route"]["version"], 1)
        unchanged = self.post(f"/subjects/{self.subject}/study-route", {"document": document(), "expected_version": 1, "operation_key": "route-import-0005b"})
        self.assertTrue(unchanged["unchanged"])
        self.assertEqual(unchanged["route"]["version"], 1)
        update_doc = document([{ "key": "novo", "title": "Proteção elétrica" }], "Roteiro atualizado")
        updated = self.post(f"/subjects/{self.subject}/study-route", {"document": update_doc, "expected_version": 1, "operation_key": "route-import-0006"})
        self.assertEqual(updated["route"]["version"], 2)
        self.assertEqual([t["name"] for t in updated["outside_topics"]], ["Lei de Ohm"])
        self.assertEqual(self.client.get(f"/api/sessions/{session['id']}").json["effective_seconds"], 1800)
        stale = self.post(f"/subjects/{self.subject}/study-route", {"document": document(), "expected_version": 1, "operation_key": "route-import-0007"}, 409)

    def test_internal_duplicate_and_same_canonical_topic_cannot_be_confirmed(self):
        doc = document([{ "key": "a", "title": "Lei de Ohm" }, {"key": "b", "title": "lei de ohm"}])
        self.post(f"/subjects/{self.subject}/study-route", {"document": doc, "expected_version": 0, "operation_key": "route-import-0008"}, 400)
        self.assertEqual(self.client.get("/api/topics?subject_id=" + str(self.subject)).json, [])


if __name__ == "__main__":
    unittest.main()
