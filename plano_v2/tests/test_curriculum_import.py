import io
import tempfile
import unittest
from pathlib import Path

from flask import Flask
from openpyxl import Workbook

from database import connection
from database.migrations import migrate
from routes.api import api
from services import grade_import


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OFFICIAL_TEMPLATE = PROJECT_ROOT / "static" / "downloads" / "modelo_grade_curricular.xlsx"


class CurriculumImportApiTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / "plano-test.db"
        self.original_database_path = connection.DATABASE_PATH
        connection.DATABASE_PATH = self.database
        migrate(self.database)
        app = Flask(__name__)
        app.register_blueprint(api)
        app.config["TESTING"] = True
        self.client = app.test_client()

    def tearDown(self):
        connection.DATABASE_PATH = self.original_database_path
        self.temp.cleanup()

    def create_formation(self):
        response = self.client.post("/api/formations", json={"name": "Formação para importação"})
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()

    def curriculum(self, formation_id):
        response = self.client.get(f"/api/formations/{formation_id}/curriculum")
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()

    def preview_file(self, formation_id, content, filename, sheet=None):
        data = {"file": (io.BytesIO(content), filename)}
        if sheet:
            data["sheet"] = sheet
        return self.client.post(
            f"/api/formations/{formation_id}/curriculum/preview",
            data=data,
            content_type="multipart/form-data",
        )

    def test_migration_template_and_official_xlsx_preview_do_not_write(self):
        with connection.connect() as conn:
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(disciplinas_grade)")}
        self.assertTrue({"start_date", "end_date", "notes"}.issubset(columns))

        download = self.client.get("/api/curriculum/template")
        self.addCleanup(download.close)
        self.assertEqual(download.status_code, 200)
        self.assertEqual(download.data, OFFICIAL_TEMPLATE.read_bytes())
        self.assertIn("attachment", download.headers["Content-Disposition"])

        formation = self.create_formation()
        response = self.preview_file(formation["id"], OFFICIAL_TEMPLATE.read_bytes(), "modelo_grade_curricular.xlsx")
        self.assertEqual(response.status_code, 200, response.get_json())
        payload = response.get_json()
        self.assertEqual(payload["format"], "xlsx")
        self.assertEqual(payload["selected_sheet"], "GRADE_PARA_IMPORTAR")
        self.assertFalse(payload["requires_sheet_selection"])
        self.assertEqual(payload["summary"]["recognized"], 3)
        self.assertEqual(payload["summary"]["selected"], 0)
        self.assertEqual(payload["items"][0]["code"], "ELT101")
        self.assertEqual(payload["items"][0]["workload_minutes"], 2700)
        self.assertEqual(payload["items"][2]["start_date"], "2026-09-01")
        self.assertEqual(payload["items"][2]["end_date"], "2026-10-30")
        self.assertEqual(self.curriculum(formation["id"]), [])

    def test_paste_normalizes_aliases_preserves_leading_code_and_blocks_unknown_status(self):
        formation = self.create_formation()
        source = (
            "Disciplina\tCódigo\tMódulo/Período\tCarga horária (h)\tSituação\tData de início\tData de término\tImportar?\n"
            "Circuitos\t001\t3º\t45\tDisponível\t01/09/2026\t30/09/2026\tSim\n"
            "Sem status\t002\t3º\t30\tA definir\t\t\tSim\n"
            "Não incluir\t003\t3º\t10\tNão iniciado\t\t\tNão\n"
        )
        response = self.client.post(
            f"/api/formations/{formation['id']}/curriculum/preview/paste",
            json={"text": source},
        )
        self.assertEqual(response.status_code, 200, response.get_json())
        items = response.get_json()["items"]
        self.assertEqual(items[0]["code"], "001")
        self.assertEqual(items[0]["workload_minutes"], 2700)
        self.assertEqual(items[0]["academic_status"], "available")
        self.assertEqual(items[0]["start_date"], "2026-09-01")
        self.assertEqual(items[0]["end_date"], "2026-09-30")
        self.assertEqual(items[1]["status_raw"], "A definir")
        self.assertTrue(items[1]["requires_review"])
        self.assertEqual(items[1]["state"], "blocked")
        self.assertFalse(items[2]["include"])

    def test_preview_never_writes_and_import_requires_explicit_confirmation(self):
        formation = self.create_formation()
        preview = self.client.post(
            f"/api/formations/{formation['id']}/curriculum/preview/paste",
            json={"text": "Álgebra Linear\nGeometria Analítica"},
        )
        self.assertEqual(preview.status_code, 200, preview.get_json())
        self.assertEqual(self.curriculum(formation["id"]), [])

        blocked = self.client.post(
            f"/api/formations/{formation['id']}/curriculum/import",
            json={"items": preview.get_json()["items"]},
        )
        self.assertEqual(blocked.status_code, 400, blocked.get_json())
        self.assertEqual(blocked.get_json()["code"], "import_confirmation_required")
        self.assertEqual(self.curriculum(formation["id"]), [])

    def test_confirmed_import_persists_metadata_and_skips_unselected_items(self):
        formation = self.create_formation()
        response = self.client.post(
            f"/api/formations/{formation['id']}/curriculum/import",
            json={
                "confirmed": True,
                "items": [
                    {
                        "name": "Eletrônica I", "code": "EL-001", "period": "3º período",
                        "workload_minutes": 2700, "academic_status": "available", "sort_order": 5,
                        "start_date": "2026-09-01", "end_date": "2026-10-30", "notes": "Revisar laboratório.",
                    },
                    {"name": "Não selecionada", "include": False, "workload_minutes": 600},
                ],
            },
        )
        self.assertEqual(response.status_code, 200, response.get_json())
        payload = response.get_json()
        self.assertEqual(payload["summary"], {"requested": 2, "inserted": 1, "updated": 0, "skipped": 1})
        self.assertEqual(payload["skipped"][0]["reason"], "not_selected")
        saved = self.curriculum(formation["id"])
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["code"], "EL-001")
        self.assertEqual(saved[0]["start_date"], "2026-09-01")
        self.assertEqual(saved[0]["end_date"], "2026-10-30")
        self.assertEqual(saved[0]["notes"], "Revisar laboratório.")

    def test_duplicate_default_is_skip_update_is_explicit_and_invalid_batch_rolls_back(self):
        formation = self.create_formation()
        existing = self.client.post(
            f"/api/formations/{formation['id']}/curriculum",
            json={"name": "Cálculo I", "workload_minutes": 1800, "academic_status": "not_available"},
        )
        self.assertEqual(existing.status_code, 200, existing.get_json())

        skipped = self.client.post(
            f"/api/formations/{formation['id']}/curriculum/import",
            json={"confirmed": True, "items": [{"name": "  calculo   i ", "workload_minutes": 3600}]},
        )
        self.assertEqual(skipped.status_code, 200, skipped.get_json())
        self.assertEqual(skipped.get_json()["summary"]["skipped"], 1)
        self.assertEqual(self.curriculum(formation["id"])[0]["workload_minutes"], 1800)

        updated = self.client.post(
            f"/api/formations/{formation['id']}/curriculum/import",
            json={
                "confirmed": True,
                "items": [{"name": "Cálculo I", "workload_minutes": 3600, "academic_status": "available", "duplicate_action": "update"}],
            },
        )
        self.assertEqual(updated.status_code, 200, updated.get_json())
        self.assertEqual(updated.get_json()["summary"]["updated"], 1)
        self.assertEqual(self.curriculum(formation["id"])[0]["workload_minutes"], 3600)

        rollback = self.client.post(
            f"/api/formations/{formation['id']}/curriculum/import",
            json={
                "confirmed": True,
                "items": [
                    {"name": "Álgebra Linear", "workload_minutes": 2400},
                    {"name": "", "workload_minutes": 1200},
                ],
            },
        )
        self.assertEqual(rollback.status_code, 400, rollback.get_json())
        self.assertEqual(rollback.get_json()["code"], "curriculum_import_invalid")
        self.assertEqual(rollback.get_json()["details"]["rows"][0]["row"], 2)
        self.assertEqual([row["name"] for row in self.curriculum(formation["id"])], ["Cálculo I"])

    def test_multiple_compatible_sheets_require_choice_before_preview(self):
        book = Workbook()
        first = book.active
        first.title = "Grade A"
        second = book.create_sheet("Grade B")
        for sheet, subject in ((first, "Circuitos"), (second, "Máquinas")):
            sheet.append(["Disciplina", "Carga horária (h)", "Importar?"])
            sheet.append([subject, 45, "Sim"])
        content = io.BytesIO()
        book.save(content)

        formation = self.create_formation()
        choice = self.preview_file(formation["id"], content.getvalue(), "duas-grades.xlsx")
        self.assertEqual(choice.status_code, 200, choice.get_json())
        self.assertTrue(choice.get_json()["requires_sheet_selection"])
        self.assertEqual(choice.get_json()["items"], [])
        selected = self.preview_file(formation["id"], content.getvalue(), "duas-grades.xlsx", sheet="Grade B")
        self.assertEqual(selected.status_code, 200, selected.get_json())
        self.assertEqual(selected.get_json()["selected_sheet"], "Grade B")
        self.assertEqual(selected.get_json()["items"][0]["name"], "Máquinas")


class CurriculumImportPdfFixtureTest(unittest.TestCase):
    """Verificação de regressão opcional para as três fontes reais do usuário."""

    @staticmethod
    def _downloads_pdf(fragment):
        found = list((Path.home() / "Downloads").glob(f"*{fragment}*.pdf"))
        return found[0] if found else None

    def test_real_senai_schedule_extracts_true_start_end_and_total_warning(self):
        source = self._downloads_pdf("Cronograma")
        if source is None:
            self.skipTest("PDF SENAI fornecido pelo usuário não está disponível neste ambiente.")
        with source.open("rb") as file:
            result = grade_import.preview(file, source.name)
        self.assertEqual(result["summary"]["recognized"], 26)
        self.assertEqual(result["summary"]["total_hours"], 1220)
        self.assertEqual(result["declared_total_hours"], 1200)
        ambientacao = next(item for item in result["items"] if item["name"] == "Ambientação")
        fundamentos = next(item for item in result["items"] if item["name"] == "Fundamentos de Eletricidade")
        self.assertEqual((ambientacao["start_date"], ambientacao["end_date"]), ("2026-03-23", "2026-03-27"))
        self.assertEqual((fundamentos["start_date"], fundamentos["end_date"]), ("2026-03-23", "2026-04-24"))
        self.assertTrue(any("difere do total declarado" in warning for warning in result["warnings"]))

    def test_real_uninter_pdfs_extract_expected_course_counts(self):
        electrical = self._downloads_pdf("Engenharia Elétrica Semipresencial")
        computer = self._downloads_pdf("Engenharia da Computação")
        if not electrical or not computer:
            self.skipTest("PDFs UNINTER fornecidos pelo usuário não estão disponíveis neste ambiente.")
        with electrical.open("rb") as file:
            electrical_result = grade_import.preview(file, electrical.name)
        with computer.open("rb") as file:
            computer_result = grade_import.preview(file, computer.name)
        self.assertEqual(electrical_result["summary"]["recognized"], 76)
        self.assertEqual(computer_result["summary"]["recognized"], 76)
        tcc = next(item for item in electrical_result["items"] if "Trabalho de Conclusão" in item["name"])
        self.assertFalse(tcc["include"])
        self.assertIsNone(tcc["workload_minutes"])
        computer_names = {item["name"] for item in computer_result["items"]}
        self.assertTrue({"Eletiva I", "Eletiva II", "Eletiva III", "Eletiva IV"}.issubset(computer_names))


if __name__ == "__main__":
    unittest.main()
