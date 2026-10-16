"""Conteúdos por disciplina; conclusão e revisão são decisões independentes."""

import re

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
