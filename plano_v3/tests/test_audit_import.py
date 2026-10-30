import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pypdf import PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject, NameObject, DictionaryObject

from tracker import db, catalog, grade_parser as parser, imports
from tests.test_pdf_ocr import image_like_pdf


def mixed_pdf():
    writer = PdfWriter()
    page = writer.add_blank_page(width=600, height=800)
    font = DictionaryObject({NameObject('/Type'): NameObject('/Font'),
                             NameObject('/Subtype'): NameObject('/Type1'),
                             NameObject('/BaseFont'): NameObject('/Helvetica')})
    page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
    stream = DecodedStreamObject()
    stream.set_data(b'BT /F1 12 Tf 20 700 Td (UCFC BASE) Tj 0 -20 Td (Design de paginas web 60) Tj ET')
    page[NameObject('/Contents')] = writer._add_object(stream)
    writer.add_page(PdfReader(io.BytesIO(image_like_pdf())).pages[0])
    out = io.BytesIO(); writer.write(out)
    return out.getvalue()


class AuditImport(unittest.TestCase):
    def row(self, **values):
        return parser.normalize_row({'name':'Circuitos', **values}, 'test', 1, 1)

    def test_extreme_hours_are_blocked_without_exception(self):
        for value in ('9'*500, '9'*307, '15000', '0', '-1', '0.001'):
            with self.subTest(value=value[:20]):
                self.assertEqual(self.row(workload_hours=value)['state'], 'blocked')

    def test_minutes_boundaries_and_types(self):
        for value in (0, -1, 600001, True, 1.5, float('inf')):
            self.assertEqual(self.row(workload_minutes=value)['state'], 'blocked')
        for value in (1, 600000):
            self.assertFalse(self.row(workload_minutes=value)['errors'])
        for hours, minutes in (('10000', 600000), ('1,5', 90), ('0.0166667', 1)):
            row = self.row(workload_hours=hours)
            self.assertFalse(row['errors'])
            self.assertEqual(row['workload_minutes'], minutes)

    def test_preview_matches_catalog_lengths(self):
        for field, value in (('name','X'*201), ('name','!!!'), ('code','X'*81), ('period','X'*101), ('notes','X'*5001)):
            self.assertEqual(self.row(**{field:value})['state'], 'blocked')

    def test_dates_and_order_survive_confirmation_as_notes(self):
        row = self.row(sort_order=8, start_date='2026-10-01', end_date='2026-10-31', workload_hours=60)
        self.assertIn('observações', ' '.join(row['warnings']))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'test.db'; db.initialize(path)
            with db.transaction(path) as conn:
                course = catalog.save_course(conn, {'name':'Curso'})
                imports.confirm(conn, course['id'], {'confirmed':True, 'items':[row]})
                self.assertEqual(imports.confirm(conn, course['id'], {'confirmed':True, 'items':[row]})['ignored'], 1)
                saved = catalog.subjects(conn)[0]
                self.assertIn('Ordem na grade original: 8', saved['notes'])
                self.assertIn('2026-10-01 a 2026-10-31', saved['notes'])

    def test_page_footer_not_subject_name(self):
        self.assertFalse(parser._pdf_noise('Design de páginas web'))
        for footer in ('Página 2', 'Página 2 de 4', 'Página 2/4'):
            self.assertTrue(parser._pdf_noise(footer))

    def test_mixed_pdf_preserves_native_text_and_ocr_order(self):
        def ocr(content):
            self.assertEqual(len(PdfReader(io.BytesIO(content)).pages), 1)
            return ['Circuitos 45']
        with patch('tracker.pdf_ocr.extract_pages', side_effect=ocr) as extract:
            result = parser._preview_pdf(mixed_pdf())
        extract.assert_called_once()
        self.assertEqual([r['name'] for r in result['items']], ['Design de paginas web', 'Circuitos'])
        self.assertEqual(result['ocr_page_numbers'], [2])
        self.assertEqual(result['summary']['total_hours'], 105)

    def test_unreadable_mixed_page_rejects_partial_preview(self):
        with patch('tracker.pdf_ocr.extract_pages', return_value=['']):
            with self.assertRaisesRegex(ValueError, 'parcial'):
                parser._preview_pdf(mixed_pdf())

    def test_page_limit_precedes_extraction(self):
        writer = PdfWriter()
        for _ in range(101): writer.add_blank_page(width=100, height=100)
        out = io.BytesIO(); writer.write(out)
        with patch('pypdf._page.PageObject.extract_text') as extract:
            with self.assertRaisesRegex(ValueError, '100 páginas'):
                parser._preview_pdf(out.getvalue())
        extract.assert_not_called()
