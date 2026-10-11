from .domain import DomainError, clean, get, key, now

STATUSES = {
    "not_available",
    "available",
    "in_progress",
    "completed",
    "failed",
    "locked",
    "exempted",
}


def courses(conn, archived=False):
    where = "" if archived else "WHERE c.archived_at IS NULL"
    return [
        dict(r)
        for r in conn.execute(f"""SELECT c.*, COUNT(s.id) subject_count
        FROM courses c LEFT JOIN subjects s ON s.course_id=c.id AND s.archived_at IS NULL
        {where} GROUP BY c.id ORDER BY c.created_at,c.id""")
    ]


def save_course(conn, values, ident=None):
    old = get(conn, "courses", ident) if ident else {}
    name = clean(values.get("name", old.get("name")), "Nome do curso", required=True)
    institution = clean(values.get("institution", old.get("institution")), "Instituição")
    if ident:
        conn.execute(
            "UPDATE courses SET name=?,institution=? WHERE id=?", (name, institution, ident)
        )
    else:
        ident = conn.execute(
            "INSERT INTO courses(name,institution,created_at) VALUES (?,?,?)",
            (name, institution, now()),
        ).lastrowid
    return get(conn, "courses", ident)


def active_course(conn, ident):
    course = get(conn, "courses", ident)
    if course["archived_at"]:
        raise DomainError("Restaure o curso antes de alterar ou estudar suas disciplinas.", 409)
    return course


def subjects(conn, course_id=None, archived=False):
    clauses, args = [], []
    if course_id:
        clauses.append("s.course_id=?")
        args.append(course_id)
    if not archived:
        clauses.extend(["s.archived_at IS NULL", "c.archived_at IS NULL"])
    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    return [
        dict(r)
        for r in conn.execute(
            f"""SELECT s.*,c.name course_name,c.archived_at course_archived_at
        FROM subjects s JOIN courses c ON c.id=s.course_id {where}
        ORDER BY c.id,s.period,s.name COLLATE NOCASE,s.id""",
            args,
        )
    ]


def subject_values(values, old=None):
    data = dict(old or {})
    data.update(values)
    name = clean(data.get("name"), "Nome da disciplina", required=True)
    name_key = key(name)
    if not name_key:
        raise DomainError("Use letras ou números no nome da disciplina.")
    minutes = data.get("workload_minutes")
    if minutes in ("", None):
        minutes = None
    elif isinstance(minutes, bool) or not isinstance(minutes, int) or not 1 <= minutes <= 600000:
        raise DomainError("Carga horária: informe de 1 a 600.000 minutos inteiros.")
    status = data.get("academic_status", "not_available")
    if status not in STATUSES:
        raise DomainError("Escolha uma situação válida para a disciplina.")
    return {
        "name": name,
        "name_key": name_key,
        "code": clean(data.get("code"), "Código", 80),
        "period": clean(data.get("period"), "Período", 100),
        "workload_minutes": minutes,
        "academic_status": status,
        "notes": clean(data.get("notes"), "Observações", 5000),
    }


def save_subject(conn, values, ident=None):
    old = get(conn, "subjects", ident) if ident else {}
    course_id = old.get("course_id") if ident else values.get("course_id")
    if not isinstance(course_id, int) or isinstance(course_id, bool):
        raise DomainError("Selecione um curso.")
    active_course(conn, course_id)
    if old.get("archived_at"):
        raise DomainError("Restaure a disciplina antes de editar.", 409)
    data = subject_values(values, old)
    other = conn.execute(
        "SELECT id FROM subjects WHERE course_id=? AND name_key=?", (course_id, data["name_key"])
    ).fetchone()
    if other and other["id"] != ident:
        raise DomainError(
            "Já existe uma disciplina com esse nome neste curso, inclusive no arquivo.", 409
        )
    if ident:
        conn.execute(
            "UPDATE subjects SET " + ",".join(f"{k}=?" for k in data) + " WHERE id=?",
            (*data.values(), ident),
        )
    else:
        data.update(course_id=course_id, created_at=now())
        ident = conn.execute(
            "INSERT INTO subjects("
            + ",".join(data)
            + ") VALUES ("
            + ",".join("?" for _ in data)
            + ")",
            tuple(data.values()),
        ).lastrowid
    return get(conn, "subjects", ident)


def archive(conn, kind, ident, archived):
    table = {"course": "courses", "subject": "subjects"}[kind]
    get(conn, table, ident)
    # Arquivar não apaga estudos nem interrompe um timer existente.
    conn.execute(
        f"UPDATE {table} SET archived_at=? WHERE id=?", (now() if archived else None, ident)
    )
    return get(conn, table, ident)
