"""Conteúdos por disciplina; conclusão e revisão são decisões independentes."""

import io
import re
import unicodedata

from . import catalog
from .domain import DomainError, clean, get, key, now


def listing(conn, subject_id=None, review_only=False, archived=False):
    where, args = [], []
    if subject_id is not None:
        where.append("t.subject_id=?")
        args.append(subject_id)
    if review_only:
        where.append("t.needs_review=1")
    if not archived:
        where.extend(["s.archived_at IS NULL", "c.archived_at IS NULL"])
    return [
        dict(r)
        for r in conn.execute(
            """SELECT t.*,s.name subject_name,c.name course_name,c.id course_id,
        COALESCE(x.seconds,0) effective_seconds,COALESCE(x.sessions,0) sessions
        FROM topics t JOIN subjects s ON s.id=t.subject_id JOIN courses c ON c.id=s.course_id
        LEFT JOIN (SELECT topic_id,SUM(effective_seconds) seconds,COUNT(*) sessions
        FROM study_sessions GROUP BY topic_id) x ON x.topic_id=t.id"""
            + (" WHERE " + " AND ".join(where) if where else "")
            + " ORDER BY c.id,s.name COLLATE NOCASE,t.id",
            args,
        )
    ]


def create(conn, subject_id, name):
    if type(subject_id) is not int:
        raise DomainError("Escolha uma disciplina para criar o tópico.")
    subject = get(conn, "subjects", subject_id)
    catalog.active_course(conn, subject["course_id"])
    if subject["archived_at"]:
        raise DomainError("Restaure a disciplina antes de criar um tópico.", 409)
    name = clean(name, "Nome do tópico", required=True)
    name_key = key(name)
    if not name_key:
        raise DomainError("Use letras ou números no nome do tópico.")
    old = conn.execute(
        "SELECT id FROM topics WHERE subject_id=? AND name_key=?", (subject_id, name_key)
    ).fetchone()
    if old:
        return get(conn, "topics", old["id"])
    ident = conn.execute(
        "INSERT INTO topics(subject_id,name,name_key,created_at) VALUES (?,?,?,?)",
        (subject_id, name, name_key, now()),
    ).lastrowid
    return get(conn, "topics", ident)


def preview(conn, subject_id, values):
    """Divisão determinística e revisável; nunca escreve nem completa texto ausente."""
    if type(subject_id) is not int:
        raise DomainError("Escolha uma disciplina.")
    get(conn, "subjects", subject_id)
    text = clean(values.get("text"), "Conteúdo", 50000, required=True)
    mode = values.get("mode", "lines")
    if mode not in ("lines", "pages", "semicolon"):
        raise DomainError("Escolha como separar o conteúdo.")
    if mode == "pages":
        # Números só são interpretados como páginas por escolha explícita.
        text = re.sub(r"[.·…\t ]+\d{1,4}[\t ]+(?=[A-ZÀ-Ý])", "\n", text)
        text = re.sub(r"[.·…\s]+\d{1,4}\s*$", "", text, flags=re.MULTILINE)
    elif mode == "semicolon":
        text = text.replace(";", "\n")
    names = []
    for line in text.splitlines():
        line = re.sub(r"^\s*(?:[•●▪◦*-]\s+|\d+(?:\.\d+)*[.)]\s+)", "", line).strip()
        if line:
            names.append(line)
    if not names or len(names) > 300:
        raise DomainError("Cole de 1 a 300 tópicos por vez.")
    known = {r[0] for r in conn.execute("SELECT name_key FROM topics WHERE subject_id=?", (subject_id,))}
    rows = []
    for name in names:
        duplicate = key(name) in known
        rows.append({"name": name, "duplicate": duplicate})
        known.add(key(name))
    return {"rows": rows, "warning": "Revise os títulos antes de salvar. A divisão não recupera texto incompleto. No modo de sumário, confira se os números removidos eram páginas."}


def preview_pdf(conn, subject_id, filename, content):
    """Extrai a tabela de cronograma de um PDF local, sem gravar tópicos."""
    if type(subject_id) is not int:
        raise DomainError("Escolha uma disciplina.")
    subject = get(conn, "subjects", subject_id)
    catalog.active_course(conn, subject["course_id"])
    if subject["archived_at"]:
        raise DomainError("Restaure a disciplina antes de importar tópicos.", 409)
    if not filename or not str(filename).lower().endswith(".pdf"):
        raise DomainError("Escolha um arquivo PDF.")
    if not content or len(content) > 5 * 1024 * 1024:
        raise DomainError("Escolha um PDF de até 5 MB.")

    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(content))
        if reader.is_encrypted:
            raise ValueError("PDF protegido por senha.")
        if not 1 <= len(reader.pages) <= 100:
            raise ValueError("O PDF precisa ter de 1 a 100 páginas.")
        page_texts = [(page.extract_text() or "") for page in reader.pages]
    except Exception as error:
        if isinstance(error, ValueError) and str(error) in {
            "PDF protegido por senha.",
            "O PDF precisa ter de 1 a 100 páginas.",
        }:
            raise DomainError(str(error)) from error
        raise DomainError(
            "Não consegui ler esse PDF. Use um PDF pesquisável ou copie o texto para a opção de colagem/IA externa."
        ) from error

    fold = lambda value: unicodedata.normalize("NFD", value).encode("ascii", "ignore").decode().lower()
    schedule_pages = [
        (index, page)
        for index, (page, text) in enumerate(zip(reader.pages, page_texts), 1)
        if "cronograma de atividades" in fold(text)
    ]
    if not schedule_pages:
        raise DomainError(
            "Não encontrei uma seção 'Cronograma de atividades' com texto selecionável. Use a instrução para IA externa e cole a lista de tópicos abaixo."
        )

    candidates = []
    for page_number, page in schedule_pages:
        width = float(page.mediabox.width)
        height = float(page.mediabox.height)
        runs = []

        def collect(text, _cm, tm, _font, font_size):
            value = re.sub(r"\s+", " ", str(text or "")).strip()
            if value:
                runs.append((float(tm[4]), float(tm[5]), value, float(font_size or 10)))

        page.extract_text(visitor_text=collect)
        anchors = sorted(
            {
                round(y, 1)
                for x, y, value, _size in runs
                if x <= width * 0.15
                and y < height * 0.82
                and y > height * 0.08
                and re.fullmatch(r"\d{1,2}", value)
            },
            reverse=True,
        )
        cells = {anchor: [] for anchor in anchors}
        for run in runs:
            x, y, value, size = run
            if width * 0.145 <= x <= width * 0.56 and anchors:
                anchor = min(anchors, key=lambda item: abs(item - y))
                if abs(anchor - y) <= 24:
                    cells[anchor].append(run)

        for anchor in anchors:
            row_runs = cells[anchor]
            if not row_runs:
                continue
            lines = []
            for run in sorted(row_runs, key=lambda item: (-round(item[1], 1), item[0])):
                x, y, value, size = run
                line = next((item for item in lines if abs(item[0] - y) <= 1.5), None)
                if line is None:
                    line = [y, []]
                    lines.append(line)
                line[1].append((x, value, size))
            text_lines = []
            for _y, fragments in sorted(lines, key=lambda item: -item[0]):
                fragments.sort(key=lambda item: item[0])
                parts = []
                for fragment_index, (_x, value, size) in enumerate(fragments):
                    if fragment_index and len(value) == 1 and value.isalpha():
                        previous_x, previous_text, previous_size = fragments[fragment_index - 1]
                        gap = _x - previous_x
                        if len(previous_text) == 1 and gap <= max(size, previous_size) * 0.8:
                            parts[-1] += value
                            continue
                    if parts and len(parts[-1]) == 1 and parts[-1].isalpha():
                        previous_x, previous_text, previous_size = fragments[fragment_index - 1]
                        gap = _x - previous_x
                        if value[:1].islower() and gap <= max(size, previous_size) * 0.8:
                            parts[-1] += value
                            continue
                    parts.append(value)
                text_lines.append(" ".join(parts))
            name = re.sub(r"\s+", " ", " ".join(text_lines)).strip()
            name = re.sub(r"(?<=\w)\s+-\s+(?=\w)", "-", name)
            name = re.sub(r"\b(\w{5,}i)\s+a\b", r"\1a", name)
            name = re.sub(r"\s+([,.;:])", r"\1", name)
            if name:
                folded = fold(name)
                kind = "assessment" if re.match(r"^(avaliacao|atividade pratica|prova)\b", folded) else "content"
                parts = (
                    [part.strip(" .;") for part in re.split(r"(?<=[.!?])\s+(?=[A-ZÀ-Ý0-9])", name)]
                    if kind == "content"
                    else [name]
                )
                candidates.extend(
                    {"name": part, "kind": kind, "page": page_number}
                    for part in parts
                    if part
                )

    if not candidates:
        raise DomainError(
            "Encontrei a seção do cronograma, mas não consegui separar as linhas da tabela. Cole o texto do conteúdo ou use a instrução para IA externa."
        )
    if len(candidates) > 300:
        raise DomainError("O cronograma contém mais de 300 linhas. Divida o PDF antes de importar.")
    known = {r[0] for r in conn.execute("SELECT name_key FROM topics WHERE subject_id=?", (subject_id,))}
    rows = []
    for candidate in candidates:
        name = candidate["name"]
        name_key = key(name)
        duplicate = name_key in known
        rows.append({**candidate, "duplicate": duplicate})
        known.add(name_key)
    content_count = sum(row["kind"] == "content" for row in rows)
    assessment_count = len(rows) - content_count
    warning = (
        f"PDF lido localmente nas páginas {', '.join(str(n) for n, _ in schedule_pages)}. "
        f"Encontrei {content_count} bloco(s) de conteúdo e {assessment_count} item(ns) avaliativo(s). "
        "Os itens avaliativos vêm desmarcados; revise todos os títulos antes de adicionar."
    )
    return {"rows": rows, "warning": warning, "page_count": len(reader.pages)}


def create_many(conn, subject_id, values):
    names = values.get("names")
    if not isinstance(names, list) or not 1 <= len(names) <= 300:
        raise DomainError("Selecione de 1 a 300 tópicos.")
    # Valida tudo antes do primeiro INSERT. O endpoint também é transacional.
    names = [clean(name, "Nome do tópico", required=True) for name in names]
    if any(not key(name) for name in names):
        raise DomainError("Use letras ou números em cada tópico.")
    before = conn.execute("SELECT COUNT(*) FROM topics WHERE subject_id=?", (subject_id,)).fetchone()[0]
    rows = [create(conn, subject_id, name) for name in names]
    after = conn.execute("SELECT COUNT(*) FROM topics WHERE subject_id=?", (subject_id,)).fetchone()[0]
    return {"created": after - before, "skipped": len(names) - (after - before), "rows": rows}


def link(conn, subject_id, values, *, allow_create=False):
    ident = values.get("topic_id")
    name = values.get("new_topic_name")
    kind = values.get("session_kind", "study")
    if kind not in ("study", "review", None):
        raise DomainError("Escolha estudo ou revisão.")
    if ident is not None and type(ident) is not int:
        raise DomainError("Escolha um tópico válido.")
    if name and (not allow_create or ident is not None):
        raise DomainError("Selecione um tópico existente ou informe um novo nome.")
    topic = (
        create(conn, subject_id, name)
        if name
        else get(conn, "topics", ident)
        if ident is not None
        else None
    )
    if topic and topic["subject_id"] != subject_id:
        raise DomainError("O tópico pertence a outra disciplina.")
    if kind == "review" and not topic:
        raise DomainError("Escolha o tópico que será revisado.")
    return {
        "topic_id": topic["id"] if topic else None,
        "topic_name": topic["name"] if topic else None,
        "session_kind": kind,
    }


def update(conn, ident, values):
    old = get(conn, "topics", ident)
    if type(values.get("version")) is not int or values["version"] != old["version"]:
        raise DomainError("O tópico mudou em outra aba. Atualize a lista antes de salvar.", 409)
    changes = {}
    for field in ("completed", "needs_review"):
        if field in values:
            if type(values[field]) is not bool:
                raise DomainError("Informe uma escolha válida para conclusão e revisão.")
            changes[field] = int(values[field])
    if not changes:
        raise DomainError("Escolha o que deseja alterar no tópico.")
    conn.execute(
        "UPDATE topics SET "
        + ",".join(f"{field}=?" for field in changes)
        + ",version=version+1 WHERE id=?",
        (*changes.values(), ident),
    )
    return get(conn, "topics", ident)
