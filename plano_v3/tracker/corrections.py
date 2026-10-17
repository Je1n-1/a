"""Correções explícitas: motivo, versão, antes/depois e reenvio idempotente."""

import json
from datetime import date
from . import sessions, topics, projects
from .domain import DomainError, LOCAL_ZONE, clean, get, now


def history(conn, ident):
    get(conn, "study_sessions", ident)
    rows = [
        {
            **dict(r),
            "old_values": json.loads(r["old_values"]),
            "new_values": json.loads(r["new_values"]),
        }
        for r in conn.execute(
            "SELECT * FROM session_corrections WHERE session_id=? ORDER BY version DESC", (ident,)
        )
    ]
    ids = {
        r[side]["subject_id"]
        for r in rows
        for side in ["old_values", "new_values"]
        if r[side]["subject_id"] is not None
    }
    labels = {}
    if ids:
        labels = {
            r["id"]: r["name"] + " · " + r["course_name"]
            for r in conn.execute(
                "SELECT s.id,s.name,c.name course_name FROM subjects s JOIN courses c ON c.id=s.course_id WHERE s.id IN ("
                + ",".join("?" for _ in ids)
                + ")",
                tuple(ids),
            )
        }
    for row in rows:
        for side in ["old_values", "new_values"]:
            row[side]["subject_label"] = labels.get(row[side]["subject_id"], "Estudo avulso")
    return rows


def correct(conn, ident, values):
    token = clean(values.get("operation_key"), "Identificador da operação", 80, required=True)
    repeat = conn.execute(
        "SELECT session_id FROM session_corrections WHERE operation_key=?", (token,)
    ).fetchone()
    if repeat:
        if repeat["session_id"] != ident:
            raise DomainError("Identificador já utilizado em outra sessão.", 409)
        return sessions.detail(conn, ident)
    old = get(conn, "study_sessions", ident)
    if type(values.get("version")) is not int or values["version"] != old["correction_version"]:
        raise DomainError(
            "Esta sessão mudou em outra aba. Feche e reabra a correção para conferir os valores atuais.",
            409,
        )
    reason = clean(values.get("reason"), "Motivo da correção", 1000, required=True)
    data = dict(old)
    subject_id = values.get("subject_id", old["subject_id"])
    if subject_id is not None:
        if type(subject_id) is not int:
            raise DomainError("Selecione uma disciplina válida.")
        subject = get(conn, "subjects", subject_id)
        data["title"] = subject["name"]
    else:
        data["title"] = clean(values.get("title", old["title"]), "Nome do estudo", required=True)
    if subject_id != old["subject_id"] and old["topic_id"] is not None and "topic_id" not in values:
        raise DomainError(
            "Ao trocar a disciplina, escolha um tópico dela ou remova o vínculo explicitamente."
        )
    topic = topics.link(
        conn,
        subject_id,
        {
            "topic_id": values.get("topic_id", old["topic_id"]),
            "session_kind": values.get("session_kind", old["session_kind"]),
        },
    )
    if topic["topic_id"] == old["topic_id"]:
        topic["topic_name"] = old["topic_name"]
    data.update(topic)
    data["subject_id"] = subject_id
    project = projects.link(conn, {"project_id": values.get("project_id", old["project_id"]), "step_id": values.get("step_id", old["step_id"]), "subject_id": subject_id, **topic}, active=False)
    if project["project_id"] == old["project_id"]:
        for field in ('project_name', 'project_course_id'):
            project[field] = old[field]
        if project['step_id'] == old['step_id']:
            project['step_name'] = old['step_name']
    data.update(project)
    if project['project_id'] is not None:
        data['title'] = project['project_name']
    data["note"] = clean(values.get("note", old["note"]), "O que estudei", 5000)
    mode = values.get("mode", "keep")
    stamp = now()
    current = sessions.instant(stamp, "Agora")
    if mode == "duration":
        try:
            day = date.fromisoformat(values.get("date")).isoformat()
        except (ValueError, TypeError):
            raise DomainError("Informe uma data válida.")
        seconds = values.get("duration_seconds")
        if (
            type(seconds) is not int
            or not 1 <= seconds <= 86400
            or day > current.astimezone(LOCAL_ZONE).date().isoformat()
        ):
            raise DomainError("Informe data não futura e duração de 1 segundo a 24 horas.")
        data.update(
            local_date=day,
            effective_seconds=seconds,
            break_seconds=0,
            rest_seconds=0,
            started_at=None,
            ended_at=None,
            allocation_mode=mode,
        )
    elif mode == "times":
        start = sessions.instant(values.get("started_at"), "Início")
        end = sessions.instant(values.get("ended_at"), "Fim")
        seconds = int((end - start).total_seconds())
        if not 1 <= seconds <= 86400 or end > current:
            raise DomainError(
                "Informe de 1 segundo a 24 horas, sem fim futuro ou anterior ao início."
            )
        data.update(
            local_date=start.astimezone(LOCAL_ZONE).date().isoformat(),
            effective_seconds=seconds,
            break_seconds=0,
            rest_seconds=0,
            started_at=start.isoformat(),
            ended_at=end.isoformat(),
            allocation_mode=mode,
        )
    elif mode != "keep":
        raise DomainError("Escolha como corrigir o registro.")
    if data == old:
        raise DomainError("Altere ao menos um campo para registrar a correção.")
    data["correction_version"] += 1
    fields = [*projects.FIELDS,
        "subject_id",
        "topic_id",
        "topic_name",
        "session_kind",
        "title",
        "note",
        "local_date",
        "started_at",
        "ended_at",
        "effective_seconds",
        "break_seconds",
        "rest_seconds",
        "allocation_mode",
        "correction_version",
    ]
    conn.execute(
        "UPDATE study_sessions SET " + ",".join(f"{k}=?" for k in fields) + " WHERE id=?",
        tuple(data[k] for k in fields) + (ident,),
    )
    sessions.rebuild_days(conn, ident)
    conn.execute(
        """INSERT INTO session_corrections(session_id,version,operation_key,reason,old_values,new_values,created_at)
        VALUES (?,?,?,?,?,?,?)""",
        (
            ident,
            data["correction_version"],
            token,
            reason,
            json.dumps(old, ensure_ascii=False),
            json.dumps(data, ensure_ascii=False),
            stamp,
        ),
    )
    return sessions.detail(conn, ident)
