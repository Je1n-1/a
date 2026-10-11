from . import catalog, grade_parser
from .domain import DomainError


def preview(conn, course_id, upload=None, text=None, sheet=None):
    if upload is not None:
        result = grade_parser.preview(upload, upload.filename, sheet)
    else:
        if not isinstance(text, str) or len(text.encode("utf-8")) > grade_parser.MAX_UPLOAD_BYTES:
            raise DomainError("Cole um texto de até 5 MB.")
        result = grade_parser.preview_paste(text)
    # OCR pode levar segundos. Não adquirir snapshot de leitura SQLite antes dele,
    # para que o relógio possa continuar gravando enquanto o arquivo é processado.
    catalog.active_course(conn, course_id)
    existing = [
        dict(r)
        for r in conn.execute("SELECT id,name FROM subjects WHERE course_id=?", (course_id,))
    ]
    return grade_parser.annotate_duplicates(result, existing)


def confirm(conn, course_id, values):
    catalog.active_course(conn, course_id)
    if values.get("confirmed") is not True:
        raise DomainError("Revise a prévia e confirme a importação.")
    items = values.get("items")
    if not isinstance(items, list) or not 1 <= len(items) <= grade_parser.MAX_ROWS:
        raise DomainError("Envie de 1 a 1.000 linhas para importar.")
    if any(not isinstance(r, dict) or not isinstance(r.get("include", True), bool) for r in items):
        raise DomainError("Cada linha deve conter uma seleção válida.")
    if not any(r.get("include", True) for r in items):
        raise DomainError("Selecione ao menos uma linha; nenhuma disciplina foi importada.")
    summary = {"inserted": 0, "updated": 0, "ignored": 0}
    seen = set()
    for index, row in enumerate(items, 1):
        if not row.get("include", True):
            summary["ignored"] += 1
            continue
        try:
            data = catalog.subject_values(row)
        except DomainError as error:
            raise DomainError(f"Linha {index}: {error}", details={"row": index}) from error
        action = row.get("duplicate_action", "skip")
        if action not in ("skip", "update"):
            raise DomainError(f"Linha {index}: ação de duplicidade inválida.")
        if data["name_key"] in seen:
            summary["ignored"] += 1
            continue
        seen.add(data["name_key"])
        old = conn.execute(
            "SELECT id,archived_at FROM subjects WHERE course_id=? AND name_key=?",
            (course_id, data["name_key"]),
        ).fetchone()
        if old:
            if action == "skip":
                summary["ignored"] += 1
                continue
            if old["archived_at"]:
                raise DomainError(
                    f"Linha {index}: restaure a disciplina arquivada antes de atualizá-la.", 409
                )
            catalog.save_subject(conn, data, old["id"])
            summary["updated"] += 1
        else:
            catalog.save_subject(conn, {**data, "course_id": course_id})
            summary["inserted"] += 1
    return summary
