"""Registro manual e rateio de intervalos reais por dia em São Paulo."""

from datetime import date, datetime, time, timedelta, timezone
from . import catalog, topics
from .domain import DomainError, LOCAL_ZONE, clean, get, now


def instant(value, label):
    try:
        if not isinstance(value, str) or len(value) < 16 or value[10] not in ("T", " "):
            raise ValueError("Informe data e horário completos")
        result = datetime.fromisoformat(value)
        if result.tzinfo is None:
            # Campos datetime-local representam sempre o fuso indicado na UI.
            local = result.replace(tzinfo=LOCAL_ZONE)
            if local.astimezone(timezone.utc).astimezone(LOCAL_ZONE).replace(tzinfo=None) != result:
                raise ValueError("Horário inexistente")
            if local.utcoffset() != local.replace(fold=1).utcoffset():
                raise ValueError("Horário ambíguo")
            result = local
        if result.microsecond:
            raise ValueError("Use segundos inteiros")
        return result.astimezone(timezone.utc)
    except (ValueError, TypeError, OverflowError):
        raise DomainError(f"{label}: informe data e horário válidos, com precisão de segundos.")


def split_interval(start, end):
    """Intervalos [início, fim): meia-noite pertence ao dia seguinte."""
    cursor = instant(start, "Início")
    stop = instant(end, "Fim")
    if stop < cursor:
        raise DomainError("O fim deve ser posterior ao início.")
    while cursor < stop:
        local_date = cursor.astimezone(LOCAL_ZONE).date()
        midnight = datetime.combine(local_date + timedelta(days=1), time(), LOCAL_ZONE).astimezone(
            timezone.utc
        )
        boundary = min(stop, midnight)
        yield local_date.isoformat(), int((boundary - cursor).total_seconds())
        cursor = boundary


def daily_allocation(conn, session):
    days = {}

    def add(day, kind, seconds):
        entry = days.setdefault(day, {"date": day, "effective_seconds": 0, "break_seconds": 0, "rest_seconds": 0})
        entry[kind] += seconds

    if session["source"] == "timer" and session.get("allocation_mode", "original") == "original":
        intervals = conn.execute(
            "SELECT * FROM timer_intervals WHERE timer_id=? ORDER BY id", (session["timer_id"],)
        )
        for row in intervals:
            if row["ended_at"] is None:
                raise DomainError("Sessão finalizada contém intervalo aberto.", 409)
            for day, seconds in split_interval(row["started_at"], row["ended_at"]):
                add(
                    day, "rest_seconds" if row["is_rest"] else "effective_seconds" if row["kind"] == "focus" else "break_seconds", seconds
                )
    elif session["started_at"]:
        for day, seconds in split_interval(session["started_at"], session["ended_at"]):
            add(day, "effective_seconds", seconds)
    else:
        add(session["local_date"], "effective_seconds", session["effective_seconds"])
    if (
        sum(d["effective_seconds"] for d in days.values()) != session["effective_seconds"]
        or sum(d["break_seconds"] for d in days.values()) != session["break_seconds"]
        or sum(d["rest_seconds"] for d in days.values()) != session.get("rest_seconds", 0)
    ):
        raise DomainError(
            "Os intervalos divergem do total da sessão. Confira os dados antes de agregar.", 409
        )
    return [days[day] for day in sorted(days)]


def detail(conn, ident):
    session = get(conn, "study_sessions", ident)
    session["daily_allocation"] = daily_allocation(conn, session)
    return session


def rebuild_days(conn, ident):
    allocation = daily_allocation(conn, get(conn, "study_sessions", ident))
    conn.execute("DELETE FROM session_days WHERE session_id=?", (ident,))
    conn.executemany(
        "INSERT INTO session_days(session_id,local_date,effective_seconds,break_seconds,rest_seconds) VALUES (?,?,?,?,?)",
        [(ident, d["date"], d["effective_seconds"], d["break_seconds"], d["rest_seconds"]) for d in allocation],
    )


def manual(conn, values):
    request_key = clean(values.get("operation_key"), "Identificador da operação", 80, required=True)
    previous = conn.execute(
        "SELECT id FROM study_sessions WHERE request_key=?", (request_key,)
    ).fetchone()
    if previous:
        return detail(conn, previous["id"])
    subject_id = values.get("subject_id")
    if subject_id is not None:
        if type(subject_id) is not int:
            raise DomainError("Selecione uma disciplina válida.")
        subject = get(conn, "subjects", subject_id)
        catalog.active_course(conn, subject["course_id"])
        if subject["archived_at"]:
            raise DomainError("Restaure a disciplina antes de registrar estudo.", 409)
        title = subject["name"]
    else:
        title = clean(values.get("title") or "Estudo avulso", "Nome do estudo", required=True)
    stamp = now()
    current = instant(stamp, "Agora")
    mode = values.get("mode")
    started = ended = None
    if mode == "duration":
        try:
            local_date = date.fromisoformat(values.get("date")).isoformat()
        except (ValueError, TypeError):
            raise DomainError("Informe uma data válida.")
        if local_date > current.astimezone(LOCAL_ZONE).date().isoformat():
            raise DomainError("O estudo não pode ser registrado em uma data futura.")
        seconds = values.get("duration_seconds")
        if type(seconds) is not int or not 1 <= seconds <= 86400:
            raise DomainError("Informe uma duração de 1 segundo a 24 horas.")
    elif mode == "times":
        start = instant(values.get("started_at"), "Início")
        end = instant(values.get("ended_at"), "Fim")
        seconds = int((end - start).total_seconds())
        if not 1 <= seconds <= 86400 or end > current:
            raise DomainError(
                "Informe de 1 segundo a 24 horas, com fim posterior ao início e sem horário futuro."
            )
        started, ended = start.isoformat(), end.isoformat()
        local_date = start.astimezone(LOCAL_ZONE).date().isoformat()
    else:
        raise DomainError("Escolha duração ou horários para o registro manual.")
    topic = topics.link(conn, subject_id, values, allow_create=True)
    note = clean(values.get("note"), "O que estudei", 5000)
    ident = conn.execute(
        """INSERT INTO study_sessions
        (subject_id,title,source,started_at,ended_at,local_date,effective_seconds,note,created_at,request_key)
        VALUES (?,?,'manual',?,?,?,?,?,?,?)""",
        (subject_id, title, started, ended, local_date, seconds, note, stamp, request_key),
    ).lastrowid
    conn.execute(
        "UPDATE study_sessions SET topic_id=?,topic_name=?,session_kind=? WHERE id=?",
        (topic["topic_id"], topic["topic_name"], topic["session_kind"], ident),
    )
    rebuild_days(conn, ident)
    return detail(conn, ident)
