"""Indicadores, gráficos, histórico e CSV sobre a mesma projeção diária."""

import csv
import io
from datetime import date, datetime, timedelta
from .domain import DomainError, LOCAL_ZONE, now


def number(value, label, default=None, maximum=2147483647):
    if value in (None, ""):
        return default
    try:
        result = int(value)
        if isinstance(value, bool) or str(result) != str(value) or not 1 <= result <= maximum:
            raise ValueError()
        return result
    except (ValueError, TypeError):
        raise DomainError(f"{label}: informe um inteiro válido.")


def filters(values):
    today = datetime.fromisoformat(now()).astimezone(LOCAL_ZONE).date()
    try:
        start = date.fromisoformat(values.get("start") or (today - timedelta(days=29)).isoformat())
        end = date.fromisoformat(values.get("end") or today.isoformat())
    except (ValueError, TypeError):
        raise DomainError("Informe datas válidas para o período.")
    if end < start or (end - start).days > 3660:
        raise DomainError("Escolha um período em ordem cronológica, com no máximo 3.661 dias.")
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "course_id": number(values.get("course_id"), "Curso"),
        "subject_id": "free"
        if values.get("subject_id") == "free"
        else number(values.get("subject_id"), "Disciplina"),
        "page": number(values.get("page"), "Página", 1),
        "page_size": number(values.get("page_size"), "Tamanho da página", 20, 100),
        "today": today.isoformat(),
        "timezone": "America/Sao_Paulo",
    }


def selection(f, *, labels=False):
    where = ["d.local_date BETWEEN ? AND ?"]
    args = [f["start"], f["end"]]
    if f["course_id"]:
        where.append("s.course_id=?")
        args.append(f["course_id"])
    if f["subject_id"] == "free":
        where.append("x.subject_id IS NULL")
    elif f["subject_id"]:
        where.append("x.subject_id=?")
        args.append(f["subject_id"])
    joins = "FROM session_days d JOIN study_sessions x ON x.id=d.session_id"
    if labels or f["course_id"]:
        joins += " LEFT JOIN subjects s ON s.id=x.subject_id"
    if labels:
        joins += " LEFT JOIN courses c ON c.id=s.course_id"
    return joins + " WHERE " + " AND ".join(where), args


def totals(conn, f):
    clause, args = selection(f)
    return dict(
        conn.execute(
            """SELECT COALESCE(SUM(d.effective_seconds),0) effective_seconds,
        COALESCE(SUM(d.break_seconds),0) break_seconds,COUNT(DISTINCT x.id) sessions """
            + clause,
            args,
        ).fetchone()
    )


def quick_summary(conn):
    f = filters({})
    today = date.fromisoformat(f["today"])
    return {
        "today": totals(conn, {**f, "start": today.isoformat(), "end": today.isoformat()}),
        "week": totals(
            conn,
            {
                **f,
                "start": (today - timedelta(days=today.weekday())).isoformat(),
                "end": today.isoformat(),
            },
        ),
        "timezone": f["timezone"],
    }


def history_query(f):
    clause, args = selection(f)
    return (
        """WITH selected AS (SELECT x.id,SUM(d.effective_seconds) effective_seconds,
        SUM(d.break_seconds) break_seconds,MIN(d.local_date) first_day,MAX(d.local_date) last_day
        """
        + clause
        + """ GROUP BY x.id)
        SELECT x.id,x.subject_id,x.title,x.source,x.started_at,x.ended_at,x.local_date,x.note,
        x.correction_version,x.allocation_mode,c.name course_name,
        selected.effective_seconds,selected.break_seconds,selected.first_day,selected.last_day,
        x.effective_seconds total_effective_seconds,x.break_seconds total_break_seconds
        FROM selected JOIN study_sessions x ON x.id=selected.id
        LEFT JOIN subjects s ON s.id=x.subject_id LEFT JOIN courses c ON c.id=s.course_id
        ORDER BY selected.last_day DESC,COALESCE(x.started_at,x.local_date) DESC,x.id DESC""",
        args,
    )


def report(conn, values):
    f = filters(values)
    period = totals(conn, f)
    today = date.fromisoformat(f["today"])
    summary = {"period": period}
    for label, start in [
        ("today", today),
        ("week", today - timedelta(days=today.weekday())),
        ("month", today.replace(day=1)),
    ]:
        summary[label] = totals(conn, {**f, "start": start.isoformat(), "end": today.isoformat()})
    clause, args = selection(f)
    existing = {
        r["date"]: dict(r)
        for r in conn.execute(
            "SELECT d.local_date date,SUM(d.effective_seconds) effective_seconds "
            + clause
            + " GROUP BY d.local_date",
            args,
        )
    }
    start = date.fromisoformat(f["start"])
    end = date.fromisoformat(f["end"])
    by_day = []
    for offset in range((end - start).days + 1):
        key = (start + timedelta(days=offset)).isoformat()
        by_day.append(existing.get(key, {"date": key, "effective_seconds": 0}))
    clause, args = selection(f, labels=True)
    by_subject = [
        dict(r)
        for r in conn.execute(
            """SELECT x.subject_id,COALESCE(s.name,'Estudo avulso') name,
        c.name course_name,SUM(d.effective_seconds) effective_seconds
        """
            + clause
            + " GROUP BY x.subject_id ORDER BY effective_seconds DESC,name COLLATE NOCASE,x.subject_id",
            args,
        )
    ]
    pages = max(1, (period["sessions"] + f["page_size"] - 1) // f["page_size"])
    f["page"] = min(f["page"], pages)
    sql, args = history_query(f)
    rows = [
        dict(r)
        for r in conn.execute(
            sql + " LIMIT ? OFFSET ?", [*args, f["page_size"], (f["page"] - 1) * f["page_size"]]
        )
    ]
    return {
        "filters": f,
        "summary": summary,
        "by_day": by_day,
        "by_subject": by_subject,
        "history": {
            "rows": rows,
            "page": f["page"],
            "pages": pages,
            "page_size": f["page_size"],
            "total": period["sessions"],
        },
    }


def safe_cell(value):
    text = "" if value is None else str(value)
    # Prefix text which Excel might evaluate, even after leading whitespace.
    if text.lstrip().startswith(("=", "+", "-", "@")) or text.startswith(("\t", "\r", "\n")):
        return "'" + text
    return text


def local_time(value):
    return datetime.fromisoformat(value).astimezone(LOCAL_ZONE).isoformat() if value else ""


def export_csv(conn, values):
    f = filters(values)
    sql, args = history_query(f)
    output = io.StringIO(newline="")
    writer = csv.writer(output, delimiter=";", lineterminator="\r\n")
    writer.writerow(
        [
            "ID",
            "Data inicial no período",
            "Data final no período",
            "Curso",
            "Disciplina/estudo",
            "Origem",
            "Versão",
            "Início da sessão (São Paulo)",
            "Fim da sessão (São Paulo)",
            "Bruto no período (s)",
            "Pausas no período (s)",
            "Líquido no período (s)",
            "Líquido total da sessão (s)",
            "Nota",
            "Filtro inicial",
            "Filtro final",
            "Fuso",
        ]
    )
    for row in conn.execute(sql, args):
        writer.writerow(
            [
                row["id"],
                row["first_day"],
                row["last_day"],
                safe_cell(row["course_name"]),
                safe_cell(row["title"]),
                row["source"],
                row["correction_version"],
                local_time(row["started_at"]),
                local_time(row["ended_at"]),
                row["effective_seconds"] + row["break_seconds"],
                row["break_seconds"],
                row["effective_seconds"],
                row["total_effective_seconds"],
                safe_cell(row["note"]),
                f["start"],
                f["end"],
                f["timezone"],
            ]
        )
    return "\ufeff" + output.getvalue()
