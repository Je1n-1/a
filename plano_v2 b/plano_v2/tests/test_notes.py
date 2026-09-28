import tempfile
import unittest
from datetime import datetime
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

from flask import Flask

from database import connection
from database.migrations import migrate
from routes.api import api


class StudyNotesApiTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / "plano-notes-test.db"
        self.original_database_path = connection.DATABASE_PATH
        connection.DATABASE_PATH = self.database
        migrate(self.database)
        app = Flask(__name__)
        app.register_blueprint(api)
        app.config["TESTING"] = True
        self.client = app.test_client()
        self.clock = patch("services.core._local_now", return_value=datetime(2026, 9, 4, 10, 0, 0))
        self.clock.start()

    def tearDown(self):
        self.clock.stop()
        connection.DATABASE_PATH = self.original_database_path
        self.temp.cleanup()

    def create_study(self, name="Circuitos Elétricos I"):
        response = self.client.post("/api/studies", json={"personal_name": name})
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()

    def create_topic(self, study, name="Análise nodal"):
        response = self.client.post(f"/api/studies/{study['id']}/topics", json={"name": name})
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()

    def create_session(self, study, topic=None):
        payload = {
            "study_subject_id": study["id"],
            "duration_seconds": 1800,
            "entry_method": "timer",
            "date": "2026-09-04",
        }
        if topic:
            payload["topic_id"] = topic["id"]
        response = self.client.post("/api/sessions", json=payload)
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()

    def create_note(self, study, topic=None, **extra):
        payload = {
            "study_subject_id": study["id"],
            "title": "Circuitos Elétricos I — Análise nodal",
            "content_markdown": "# Ideias\n\nTensão e corrente com acentuação: conexão.",
            "tags": "estudos, circuitos-elétricos",
            "status": "draft",
            **extra,
        }
        if topic:
            payload["topic_id"] = topic["id"]
        response = self.client.post("/api/notes", json=payload)
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()

    def test_create_autosave_get_and_filter_notes_without_overwriting(self):
        study = self.create_study()
        topic = self.create_topic(study)
        first = self.create_note(study, topic, tags=" estudos, #circuitos elétricos, estudos ")
        self.assertEqual(first["status"], "draft")
        self.assertEqual(first["tags"], "estudos, circuitos elétricos")
        self.assertEqual(first["topic_id"], topic["id"])

        saved = self.client.patch(f"/api/notes/{first['id']}", json={
            "title": "Circuitos: versão revisada",
            "content_markdown": "Texto longo com á, ê, ç e uma segunda linha.\n\n- ponto importante",
            "tags": ["estudos", "revisão"],
        })
        self.assertEqual(saved.status_code, 200, saved.get_json())
        self.assertEqual(saved.get_json()["tags"], "estudos, revisão")
        self.assertIn("segunda linha", saved.get_json()["content_markdown"])

        second = self.create_note(study, title="Outra anotação", content_markdown="Independente")
        self.assertNotEqual(first["id"], second["id"])
        fetched = self.client.get(f"/api/notes/{first['id']}")
        self.assertEqual(fetched.status_code, 200, fetched.get_json())
        self.assertIn("segunda linha", fetched.get_json()["content_markdown"])

        by_subject = self.client.get(f"/api/notes?study_subject_id={study['id']}&status=draft")
        self.assertEqual(by_subject.status_code, 200, by_subject.get_json())
        self.assertEqual({item["id"] for item in by_subject.get_json()}, {first["id"], second["id"]})
        by_topic = self.client.get(f"/api/notes?topic_id={topic['id']}")
        self.assertEqual([item["id"] for item in by_topic.get_json()], [first["id"]])
        created_day = first["created_at"][:10]
        by_date = self.client.get(f"/api/notes?start={created_day}&end={created_day}")
        self.assertEqual({item["id"] for item in by_date.get_json()}, {first["id"], second["id"]})

    def test_finalize_is_idempotent_and_only_drafts_can_be_discarded(self):
        study = self.create_study()
        topic = self.create_topic(study)
        note = self.create_note(study, topic)
        session = self.create_session(study, topic)

        first = self.client.post(f"/api/notes/{note['id']}/finalize", json={"study_session_id": session["id"]})
        self.assertEqual(first.status_code, 200, first.get_json())
        self.assertEqual(first.get_json()["status"], "final")
        self.assertEqual(first.get_json()["study_session_id"], session["id"])
        repeated = self.client.post(f"/api/notes/{note['id']}/finalize", json={"study_session_id": session["id"]})
        self.assertEqual(repeated.status_code, 200, repeated.get_json())
        self.assertEqual(repeated.get_json()["id"], note["id"])

        other_session = self.create_session(study, topic)
        conflicting = self.client.post(f"/api/notes/{note['id']}/finalize", json={"study_session_id": other_session["id"]})
        self.assertEqual(conflicting.status_code, 409, conflicting.get_json())
        self.assertEqual(conflicting.get_json()["code"], "note_finalized")
        final_delete = self.client.delete(f"/api/notes/{note['id']}")
        self.assertEqual(final_delete.status_code, 409, final_delete.get_json())

        draft = self.create_note(study, title="Rascunho descartável")
        discarded = self.client.delete(f"/api/notes/{draft['id']}")
        self.assertEqual(discarded.status_code, 200, discarded.get_json())
        missing = self.client.get(f"/api/notes/{draft['id']}")
        self.assertEqual(missing.status_code, 404, missing.get_json())

    def test_markdown_and_obsidian_zip_are_utf8_and_have_safe_frontmatter(self):
        study = self.create_study('Circuitos "Elétricos"')
        topic = self.create_topic(study, "Análise nodal")
        note = self.create_note(
            study,
            topic,
            title='Circuitos "I"\nAnálise nodal',
            content_markdown="Conteúdo com acentos: ação, conexão e tensão.\n\n<script>não executa aqui</script>",
            tags="estudos, circuitos-elétricos",
        )
        second = self.create_note(study, title="Segunda nota", content_markdown="Outro conteúdo")

        markdown = self.client.get(f"/api/notes/{note['id']}/export")
        self.assertEqual(markdown.status_code, 200)
        self.assertIn("text/markdown", markdown.content_type)
        self.assertIn("attachment;", markdown.headers["Content-Disposition"])
        text = markdown.data.decode("utf-8")
        self.assertTrue(text.startswith("---\n"))
        self.assertIn('subject: "Circuitos \\"Elétricos\\""', text)
        self.assertIn('tags:\n  - "estudos"\n  - "circuitos-elétricos"', text)
        self.assertIn("session_id: null", text)
        self.assertIn("Conteúdo com acentos: ação", text)

        zipped = self.client.post("/api/notes/export/obsidian", json={"ids": [note["id"], second["id"], note["id"]]})
        self.assertEqual(zipped.status_code, 200)
        self.assertEqual(zipped.content_type, "application/zip")
        self.assertIn("anotacoes-obsidian.zip", zipped.headers["Content-Disposition"])
        with ZipFile(BytesIO(zipped.data)) as archive:
            self.assertEqual(len(archive.namelist()), 2)
            self.assertTrue(all(name.endswith(".md") and "/" not in name for name in archive.namelist()))
            exported = archive.read(archive.namelist()[0]).decode("utf-8")
            self.assertIn("ação", exported)

        none_selected = self.client.post("/api/notes/export/obsidian", json={"ids": []})
        self.assertEqual(none_selected.status_code, 400, none_selected.get_json())


if __name__ == "__main__":
    unittest.main()
