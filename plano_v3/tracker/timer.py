"""Relógio persistido: transições serializadas, recuperação e conclusão única."""

from datetime import datetime
from . import catalog
from .domain import DomainError, LOCAL_ZONE, clean, get, now
from .sessions import instant, rebuild_days

RECOVERY_SECONDS = 8 * 3600


def snapshot(conn, ident, current=None):
    timer = get(conn, "timers", ident)
    current = current or now()
    totals = {"focus": 0, "break": 0}
    opened = None
    clock_error = False
    for row in conn.execute("SELECT * FROM timer_intervals WHERE timer_id=? ORDER BY id", (ident,)):
        seconds = int(
            (
                datetime.fromisoformat(row["ended_at"] or current)
                - datetime.fromisoformat(row["started_at"])
            ).total_seconds()
        )
        clock_error = clock_error or seconds < 0
        if row["ended_at"] is None:
            opened = dict(row)
        totals[row["kind"]] += max(0, seconds)
    timer.update(
        effective_seconds=totals["focus"],
        break_seconds=totals["break"],
        total_seconds=sum(totals.values()),
        server_now=current,
    )
    subject = conn.execute(
        "SELECT s.name,c.name course_name FROM subjects s JOIN courses c ON c.id=s.course_id WHERE s.id=?",
        (timer["subject_id"],),
    ).fetchone()
    timer["course_name"] = subject["course_name"] if subject else None
    session = conn.execute("SELECT id FROM study_sessions WHERE timer_id=?", (ident,)).fetchone()
    timer["session_id"] = session["id"] if session else None
    confirmation = conn.execute(
        "SELECT confirmed_at FROM timer_recoveries WHERE timer_id=? ORDER BY id DESC LIMIT 1",
        (ident,),
    ).fetchone()
    reference = confirmation["confirmed_at"] if confirmation else timer["started_at"]
    timer["recovery_required"] = (
        timer["status"] in ("running", "paused")
        and (instant(current, "Agora") - instant(reference, "Confirmação")).total_seconds()
        >= RECOVERY_SECONDS
    )
    timer["recovery_limit_seconds"] = RECOVERY_SECONDS
    timer["open_interval"] = opened
    timer["clock_error"] = clock_error
    return timer


def active(conn):
    row = conn.execute("SELECT id FROM timers WHERE status IN ('running','paused')").fetchone()
    return snapshot(conn, row["id"]) if row else None


def start(conn, values):
    token = clean(values.get("operation_key"), "Identificador da operação", 80, required=True)
    subject_id = values.get("subject_id")
    if subject_id is not None and (isinstance(subject_id, bool) or not isinstance(subject_id, int)):
        raise DomainError("Selecione uma disciplina válida.")
    previous = conn.execute(
        "SELECT id,subject_id FROM timers WHERE operation_key=?", (token,)
    ).fetchone()
    if previous:
        if previous["subject_id"] != subject_id:
            raise DomainError("Identificador já utilizado em outra disciplina.", 409)
        return snapshot(conn, previous["id"])
    if active(conn):
        raise DomainError(
            "Já existe um relógio em andamento. Abra Hoje para continuar ou finalizar.", 409
        )
    if subject_id is not None:
        subject = get(conn, "subjects", subject_id)
        catalog.active_course(conn, subject["course_id"])
        if subject["archived_at"]:
            raise DomainError("Restaure a disciplina antes de estudar.", 409)
        title = subject["name"]
    else:
        title = clean(values.get("title") or "Estudo avulso", "Nome do estudo", required=True)
    stamp = now()
    ident = conn.execute(
        "INSERT INTO timers(subject_id,title,status,started_at,operation_key) VALUES (?,?,'running',?,?)",
        (subject_id, title, stamp, token),
    ).lastrowid
    conn.execute(
        "INSERT INTO timer_intervals(timer_id,kind,started_at) VALUES (?,'focus',?)", (ident, stamp)
    )
    return snapshot(conn, ident)


def check_version(timer, values):
    if type(values.get("version")) is not int or values["version"] != timer["version"]:
        raise DomainError(
            "O relógio mudou em outra aba. O estado foi atualizado; confira e tente novamente.", 409
        )


def recover(conn, ident, values):
    token = clean(values.get("operation_key"), "Identificador da operação", 80, required=True)
    previous = conn.execute(
        "SELECT timer_id FROM timer_recoveries WHERE operation_key=?", (token,)
    ).fetchone()
    if previous:
        if previous["timer_id"] != ident:
            raise DomainError("Identificador já usado em outro relógio.", 409)
        return snapshot(conn, ident)
    stamp = now()
    timer = snapshot(conn, ident, stamp)
    check_version(timer, values)
    if timer["status"] not in ("running", "paused"):
        raise DomainError("Este relógio já foi encerrado.", 409)
    if timer["clock_error"]:
        raise DomainError(
            "O horário do computador voltou no tempo. Corrija-o antes de recuperar o relógio.", 409
        )
    choice = values.get("choice")
    if choice not in ("full", "cutoff"):
        raise DomainError("Escolha manter o período ou informar quando parou.")
    interval = timer["open_interval"]
    if not interval:
        raise DomainError("Não há intervalo aberto para recuperar.", 409)
    cutoff = None
    if choice == "cutoff":
        if timer["status"] != "running":
            raise DomainError("O estudo já está pausado. Confirme o período registrado.", 409)
        accepted = instant(values.get("cutoff_at"), "Quando parei")
        if not instant(interval["started_at"], "Início") <= accepted <= instant(stamp, "Agora"):
            raise DomainError("O horário deve ficar entre a última retomada e agora.")
        cutoff = accepted.isoformat()
        conn.execute("UPDATE timer_intervals SET ended_at=? WHERE id=?", (cutoff, interval["id"]))
        conn.execute(
            "INSERT INTO timer_intervals(timer_id,kind,started_at) VALUES (?,'break',?)",
            (ident, cutoff),
        )
    elif timer["status"] == "running":
        conn.execute("UPDATE timer_intervals SET ended_at=? WHERE id=?", (stamp, interval["id"]))
        conn.execute(
            "INSERT INTO timer_intervals(timer_id,kind,started_at) VALUES (?,'break',?)",
            (ident, stamp),
        )
    # Toda revisão deixa o relógio pausado, para o usuário retomar conscientemente.
    conn.execute("UPDATE timers SET status='paused',version=version+1 WHERE id=?", (ident,))
    accepted = snapshot(conn, ident, stamp)["effective_seconds"]
    conn.execute(
        """INSERT INTO timer_recoveries
        (timer_id,operation_key,choice,cutoff_at,previous_effective_seconds,accepted_effective_seconds,confirmed_at)
        VALUES (?,?,?,?,?,?,?)""",
        (ident, token, choice, cutoff, timer["effective_seconds"], accepted, stamp),
    )
    return snapshot(conn, ident, stamp)


def transition(conn, ident, action, values):
    if action == "recover":
        return recover(conn, ident, values)
    timer = get(conn, "timers", ident)
    if action not in ("pause", "resume", "finish", "cancel"):
        raise DomainError("Ação inválida.", 404)
    if (timer["status"] == "completed" and action == "finish") or (
        timer["status"] == "cancelled" and action == "cancel"
    ):
        return snapshot(conn, ident)
    check_version(timer, values)
    if timer["status"] not in ("running", "paused"):
        raise DomainError("Este relógio já foi encerrado.", 409)
    next_status = {
        "pause": "paused",
        "resume": "running",
        "finish": "completed",
        "cancel": "cancelled",
    }[action]
    if timer["status"] == next_status:
        return snapshot(conn, ident)
    stamp = now()
    state = snapshot(conn, ident, stamp)
    if action in ("resume", "finish") and state["recovery_required"]:
        raise DomainError(
            "Esta sessão ficou aberta por 8 horas ou mais. Revise o período antes de retomar ou finalizar.",
            409,
        )
    interval = conn.execute(
        "SELECT * FROM timer_intervals WHERE timer_id=? AND ended_at IS NULL", (ident,)
    ).fetchone()
    if (
        not interval
        or instant(stamp, "Agora") < instant(interval["started_at"], "Início")
        or state["clock_error"]
    ):
        raise DomainError(
            "O horário do sistema mudou. Confira o relógio do computador antes de continuar.", 409
        )
    if action == "finish" and state["effective_seconds"] < 1:
        raise DomainError("Estude por pelo menos um segundo antes de finalizar.")
    note = clean(values.get("note"), "O que estudei", 5000) if action == "finish" else ""
    conn.execute("UPDATE timer_intervals SET ended_at=? WHERE id=?", (stamp, interval["id"]))
    ended = stamp if action in ("finish", "cancel") else None
    conn.execute(
        "UPDATE timers SET status=?,ended_at=?,version=version+1 WHERE id=?",
        (next_status, ended, ident),
    )
    if action in ("pause", "resume"):
        conn.execute(
            "INSERT INTO timer_intervals(timer_id,kind,started_at) VALUES (?,?,?)",
            (ident, "break" if action == "pause" else "focus", stamp),
        )
    if action == "finish":
        totals = snapshot(conn, ident, stamp)
        local_date = (
            datetime.fromisoformat(timer["started_at"]).astimezone(LOCAL_ZONE).date().isoformat()
        )
        session_id = conn.execute(
            """INSERT INTO study_sessions(timer_id,subject_id,title,source,started_at,ended_at,
            local_date,effective_seconds,break_seconds,note,created_at) VALUES (?,?,?,'timer',?,?,?,?,?,?,?)""",
            (
                ident,
                timer["subject_id"],
                timer["title"],
                timer["started_at"],
                stamp,
                local_date,
                totals["effective_seconds"],
                totals["break_seconds"],
                note,
                stamp,
            ),
        ).lastrowid
        rebuild_days(conn, session_id)
    return snapshot(conn, ident, stamp)


def recent(conn):
    return [
        dict(row)
        for row in conn.execute("""SELECT x.*,c.name course_name FROM study_sessions x
        LEFT JOIN subjects s ON s.id=x.subject_id LEFT JOIN courses c ON c.id=s.course_id
        ORDER BY x.id DESC LIMIT 5""")
    ]
