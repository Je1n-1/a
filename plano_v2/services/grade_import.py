"""Parser conservador: extrai texto, sugere campos e nunca persiste no preview."""
from __future__ import annotations

import csv
import io
import re
from pathlib import Path


ALLOWED = {"csv", "txt", "docx", "pdf"}


def _clean(value):
    return re.sub(r"\s+", " ", str(value or "").replace("\xa0", " ")).strip(" -;|")


def _minutes(value):
    text = _clean(value).lower().replace(",", ".")
    match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(?:h|hs|hora|horas)?", text)
    return round(float(match.group(1)) * 60) if match and float(match.group(1)) > 0 else None


def _from_text(text):
    result, period = [], None
    for raw in text.splitlines():
        line = _clean(raw)
        if not line:
            continue
        if re.search(r"\b(m[oó]dulo|semestre|per[ií]odo|etapa|ciclo)\b", line, re.I) and len(line) < 60:
            period = line
            continue
        for piece in re.split(r"\t|\s{3,}|\|", line):
            name = _clean(piece)
            normalized = name.casefold()
            if 3 <= len(name) <= 120 and re.search(r"[a-záéíóúãõç]", normalized) and not re.search(r"(carga hor|cr[eé]dito|matriz curricular|disciplina$|c[oó]digo|p[aá]gina)", normalized):
                result.append({"name": name, "code": None, "period": period, "workload_minutes": None, "sort_order": len(result), "source_index": len(result) + 1})
    return result


def preview(file, filename):
    extension = Path(filename).suffix.lower().lstrip(".")
    if extension not in ALLOWED:
        raise ValueError("Formato não suportado. Use PDF, DOCX, CSV ou TXT.")
    content = file.read()
    file.seek(0)
    if extension == "csv":
        text = content.decode("utf-8-sig", errors="replace")
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=";,\t") if text.strip() else csv.excel
        rows = list(csv.DictReader(io.StringIO(text), dialect=dialect))
        if rows and rows[0]:
            fields = {key: key.casefold() for key in rows[0]}
            find = lambda options: next((key for key, normalized in fields.items() if any(option in normalized for option in options)), None)
            name, code, period, workload = find(("disciplina", "matéria", "materia", "nome")), find(("código", "codigo", "sigla")), find(("período", "periodo", "módulo", "modulo", "semestre")), find(("carga", "horas", "ch"))
            result = [{"name": _clean(row.get(name)), "code": _clean(row.get(code)) or None, "period": _clean(row.get(period)) or None, "workload_minutes": _minutes(row.get(workload)), "sort_order": index, "source_index": index + 2} for index, row in enumerate(rows) if name and _clean(row.get(name))]
        else:
            result = _from_text(text)
    else:
        if extension == "txt":
            text = content.decode("utf-8-sig", errors="replace")
        elif extension == "docx":
            from docx import Document
            document = Document(io.BytesIO(content))
            text = "\n".join([p.text for p in document.paragraphs] + [" | ".join(cell.text for cell in row.cells) for table in document.tables for row in table.rows])
        else:
            from pypdf import PdfReader
            text = "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(content)).pages)
        result = _from_text(text)
    if not result:
        raise ValueError("Nenhuma disciplina foi identificada. Corrija o arquivo ou cadastre manualmente.")
    return result
