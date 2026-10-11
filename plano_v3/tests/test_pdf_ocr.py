import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, NameObject

from tracker import db, grade_parser, imports, pdf_ocr


def image_like_pdf(pages=1):
    writer = PdfWriter()
    for _ in range(pages):
        page = writer.add_blank_page(width=100, height=100)
        stream = DecodedStreamObject()
        stream.set_data(b"q 1 0 0 1 0 0 cm Q")
        page[NameObject("/Contents")] = writer._add_object(stream)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


class OcrParsing(unittest.TestCase):
    def test_file_reading_does_not_hold_database_read_lock(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "data.db"
            db.initialize(path)
            with db.transaction(path) as writer:
                writer.execute("INSERT INTO courses(name,created_at) VALUES ('Curso','2026-10-11')")

            def reading(*args):
                with db.transaction(path) as writer:
                    writer.execute("PRAGMA busy_timeout=50")
                    writer.execute(
                        "UPDATE courses SET institution='Atualizado durante leitura' WHERE id=1"
                    )
                return grade_parser.preview_paste("Disciplina\tCarga horária\nCircuitos\t45")

            with patch("tracker.grade_parser.preview", side_effect=reading):
                with db.read_transaction(path) as conn:
                    result = imports.preview(conn, 1, upload=SimpleNamespace(filename="grade.pdf"))
            self.assertEqual(result["summary"]["recognized"], 1)

    def test_columns_are_reassembled_by_position(self):
        words = [
            {"text": "45", "x": 800, "y": 101, "height": 18},
            {"text": "Circuitos", "x": 50, "y": 100, "height": 20},
            {"text": "Elétricos", "x": 160, "y": 99, "height": 21},
            {"text": "Álgebra", "x": 50, "y": 180, "height": 20},
            {"text": "60", "x": 800, "y": 181, "height": 18},
        ]
        self.assertEqual(pdf_ocr.lines_from_words(words), ["Circuitos Elétricos 45", "Álgebra 60"])

    def test_ocr_repeated_pages_keep_names_hours_and_periods(self):
        page = "UCFC BASE DE ENGENHARIA\nDisciplina Carga horária\nCircuitos Elétricos 45\nÁlgebra Linear 60"
        with patch("tracker.pdf_ocr.extract", return_value=page + "\n" + page) as extract:
            result = grade_parser.preview(io.BytesIO(image_like_pdf(2)), "grade.pdf")
        extract.assert_called_once()
        self.assertEqual(result["summary"]["recognized"], 2)
        self.assertEqual(result["summary"]["total_hours"], 105)
        self.assertEqual(result["ocr"]["repeated_rows"], 2)
        self.assertEqual(result["items"][0]["period"], "UCFC BASE DE ENGENHARIA")
        self.assertTrue(all(any("OCR" in w for w in row["warnings"]) for row in result["items"]))

    def test_page_limit_precedes_expensive_ocr(self):
        with patch("tracker.pdf_ocr.extract") as extract:
            with self.assertRaisesRegex(ValueError, "12 páginas"):
                grade_parser.preview(io.BytesIO(image_like_pdf(13)), "grade.pdf")
        extract.assert_not_called()

    def test_blank_pdf_is_not_sent_to_ocr(self):
        writer = PdfWriter()
        writer.add_blank_page(width=100, height=100)
        output = io.BytesIO()
        writer.write(output)
        with patch("tracker.pdf_ocr.extract") as extract:
            with self.assertRaisesRegex(ValueError, "texto interpretável"):
                grade_parser.preview(io.BytesIO(output.getvalue()), "blank.pdf")
        extract.assert_not_called()


@unittest.skipUnless(os.name == "nt", "Executável OCR usa Windows")
class OcrProcess(unittest.TestCase):
    def test_timeout_and_engine_failure_release_worker(self):
        cases = [subprocess.TimeoutExpired("ocr", 90), OSError("missing")]
        for error in cases:
            with patch("tracker.pdf_ocr.subprocess.run", side_effect=error):
                with self.assertRaises(ValueError):
                    pdf_ocr.extract(b"pdf")
            self.assertTrue(pdf_ocr._worker.acquire(blocking=False))
            pdf_ocr._worker.release()
        with patch(
            "tracker.pdf_ocr.subprocess.run",
            return_value=SimpleNamespace(returncode=1, stderr="OCR_PORTUGUESE_UNAVAILABLE"),
        ):
            with self.assertRaisesRegex(ValueError, "português"):
                pdf_ocr.extract(b"pdf")

    def test_busy_and_empty_or_invalid_response_are_visible_errors(self):
        pdf_ocr._worker.acquire()
        try:
            with self.assertRaisesRegex(ValueError, "Outra grade"):
                pdf_ocr.extract(b"pdf")
        finally:
            pdf_ocr._worker.release()
        for stdout in ("invalid", json.dumps({"pages": [{"words": []}]})):
            with patch(
                "tracker.pdf_ocr.subprocess.run",
                return_value=SimpleNamespace(returncode=0, stdout=stdout),
            ):
                with self.assertRaises(ValueError):
                    pdf_ocr.extract(b"pdf")
