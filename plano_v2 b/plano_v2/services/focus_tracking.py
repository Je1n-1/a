"""Persistência de pausas e correções de sessões de foco."""
from __future__ import annotations

from datetime import datetime
import json

from config import LOCAL_TIMEZONE
from database.repositories import core as repo


BREAK_REASONS = {
    "rest", "water_food", "bathroom", "external_interruption", "difficulty", "other",
}


class FocusTrackingError(ValueError):
    def __init__(self, message, code="focus_tracking_error", status=400):
        super().__init__(message)
        self.code = code
        self.status = status


def _now() -> str:
    return datetime.now(LOCAL_TIMEZONE).isoformat(timespec="seconds")


def _timestamp(value, label="Horário") -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as error:
        raise FocusTrackingError(f"{label} inválido.", "invalid_break_interval") from error
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=LOCAL_TIMEZONE)
    return parsed.astimezone(LOCAL_TIMEZONE)


def _reason(value):
    if value in (None, ""):
        return None
    if value not in BREAK_REASONS:
        raise FocusTrackingError("Motivo da pausa inválido.", "invalid_break_reason")
    return value


def breaks_for_focus(conn, focus_id: int) -> list[dict]:
    return repo.many(conn, """
        SELECT * FROM session_breaks
        WHERE focus_session_id=? ORDER BY COALESCE(started_at,created_at),id
    """, (focus_id,))


def breaks_for_session(conn, session_id: int) -> list[dict]:
    return repo.many(conn, """
        SELECT * FROM session_breaks
        WHERE study_session_id=? ORDER BY COALESCE(started_at,created_at),id
    """, (session_id,))


def _duration(row: dict, now=None) -> int:
    if row.get("duration_seconds") is not None:
        return max(0, int(row["duration_seconds"]))
    if row.get("started_at"):
        end = _timestamp(row.get("ended_at") or now or _now())
        return max(0, int((end - _timestamp(row["started_at"])).total_seconds()))
    return 0


def pause_totals(conn, *, focus_id=None, session_id=None, now=None) -> dict:
    rows = breaks_for_focus(conn, focus_id) if focus_id is not None else breaks_for_session(conn, session_id)
    total = sum(_duration(row, now) for row in rows)
    current = next((row for row in rows if row.get("started_at") and not row.get("ended_at")), None)
    return {
        "pause_seconds": total,
        "current_pause_seconds": _duration(current, now) if current else 0,
        "breaks": rows,
    }


def start_break(conn, focus_id: int, values=None) -> dict:
    values = values or {}
    existing = repo.one(conn, """
        SELECT * FROM session_breaks
        WHERE focus_session_id=? AND started_at IS NOT NULL AND ended_at IS NULL
        ORDER BY id DESC LIMIT 1
    """, (focus_id,))
    if existing:
        return existing
    key = values.get("idempotency_key")
    if key:
        existing = repo.one(conn, "SELECT * FROM session_breaks WHERE idempotency_key=?", (str(key),))
        if existing:
            return existing
    ident = repo.insert(conn, "session_breaks", {
        "focus_session_id": focus_id,
        "study_session_id": None,
        "started_at": values.get("started_at") or _now(),
        "ended_at": None,
        "duration_seconds": None,
        "reason": _reason(values.get("reason")),
        "notes": values.get("notes"),
        "origin": "timer",
        "subtracts_from_focus": 0,
        "idempotency_key": str(key) if key else None,
    })
    return repo.one(conn, "SELECT * FROM session_breaks WHERE id=?", (ident,))


def finish_open_break(conn, focus_id: int, values=None, *, ended_at=None) -> dict | None:
    values = values or {}
    current = repo.one(conn, """
        SELECT * FROM session_breaks
        WHERE focus_session_id=? AND started_at IS NOT NULL AND ended_at IS NULL
        ORDER BY id DESC LIMIT 1
    """, (focus_id,))
    if not current:
        return None
    end = ended_at or _now()
    duration = max(0, int((_timestamp(end) - _timestamp(current["started_at"])).total_seconds()))
    reason = _reason(values.get("reason")) if "reason" in values else current.get("reason")
    notes = values.get("notes", current.get("notes"))
    conn.execute(
        "UPDATE session_breaks SET ended_at=?,duration_seconds=?,reason=?,notes=?,version=version+1,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
        (end, duration, reason, notes, current["id"]),
    )
    return repo.one(conn, "SELECT * FROM session_breaks WHERE id=?", (current["id"],))


def update_break(conn, break_id: int, values: dict) -> dict:
    current = repo.one(conn, "SELECT * FROM session_breaks WHERE id=?", (break_id,))
    if not current:
        raise FocusTrackingError("Pausa não encontrada.", "break_not_found", 404)
    expected = values.get("version")
    if expected not in (None, "") and int(expected) != int(current["version"]):
        raise FocusTrackingError("A pausa foi atualizada em outra aba.", "break_version_conflict", 409)
    updates = {}
    if "reason" in values:
        updates["reason"] = _reason(values.get("reason"))
    if "notes" in values:
        updates["notes"] = values.get("notes")
    if updates:
        assignments = ",".join(f"{key}=?" for key in updates)
        conn.execute(
            f"UPDATE session_breaks SET {assignments},version=version+1,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
            (*updates.values(), break_id),
        )
    return repo.one(conn, "SELECT * FROM session_breaks WHERE id=?", (break_id,))


def attach_to_session(conn, focus_id: int, session_id: int) -> dict:
    conn.execute(
        "UPDATE session_breaks SET study_session_id=?,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE focus_session_id=? AND study_session_id IS NULL",
        (session_id, focus_id),
    )
    totals = pause_totals(conn, session_id=session_id)
    conn.execute(
        "UPDATE sessoes_estudo SET pause_seconds=?,version=version+1,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
        (totals["pause_seconds"], session_id),
    )
    return totals


def _session(conn, session_id: int) -> dict:
    row = repo.one(conn, "SELECT * FROM sessoes_estudo WHERE id=?", (session_id,))
    if not row:
        raise FocusTrackingError("Sessão não encontrada.", "session_not_found", 404)
    return row


def _overlaps(conn, session: dict, start: datetime, end: datetime) -> bool:
    rows = breaks_for_session(conn, session["id"])
    for row in rows:
        if not row.get("started_at") or not row.get("ended_at"):
            continue
        existing_start = _timestamp(row["started_at"])
        existing_end = _timestamp(row["ended_at"])
        if start < existing_end and end > existing_start:
            return True
    return False


def add_retroactive_break(conn, session_id: int, values: dict) -> dict:
    session = _session(conn, session_id)
    key = values.get("idempotency_key")
    if key:
        existing = repo.one(conn, "SELECT * FROM study_session_corrections WHERE idempotency_key=?", (str(key),))
        if existing:
            return {
                "session": _session(conn, session_id),
                "break": repo.one(conn, "SELECT * FROM session_breaks WHERE id=?", (existing["break_id"],)),
                "correction": existing,
                "idempotent": True,
            }
    start_value, end_value = values.get("started_at"), values.get("ended_at")
    if bool(start_value) != bool(end_value):
        raise FocusTrackingError("Informe início e fim da pausa, ou somente a duração.", "invalid_break_interval")
    if start_value:
        if not session.get("started_at") or not session.get("ended_at"):
            raise FocusTrackingError("Esta sessão não possui horários confiáveis; informe apenas a duração da pausa.", "session_timeline_unavailable")
        start, end = _timestamp(start_value, "Início da pausa"), _timestamp(end_value, "Fim da pausa")
        session_start, session_end = _timestamp(session["started_at"]), _timestamp(session["ended_at"])
        if end <= start or start < session_start or end > session_end:
            raise FocusTrackingError("A pausa deve ficar integralmente dentro do período da sessão.", "invalid_break_interval")
        if _overlaps(conn, session, start, end):
            raise FocusTrackingError("A pausa informada se sobrepõe a outra pausa desta sessão.", "break_overlap", 409)
        duration = int((end - start).total_seconds())
        origin = "retroactive_interval"
        stored_start, stored_end = start.isoformat(timespec="seconds"), end.isoformat(timespec="seconds")
    else:
        try:
            duration = int(values.get("duration_seconds"))
        except (TypeError, ValueError) as error:
            raise FocusTrackingError("Informe a duração da pausa em segundos.", "invalid_break_duration") from error
        if duration <= 0:
            raise FocusTrackingError("A duração da pausa deve ser maior que zero.", "invalid_break_duration")
        origin = "retroactive_duration"
        stored_start = stored_end = None
    before = dict(session)
    if duration >= int(session["duration_seconds"]):
        raise FocusTrackingError("A pausa não pode consumir todo o tempo de foco da sessão.", "break_exceeds_focus")
    focus = repo.one(conn, "SELECT id FROM sessoes_foco WHERE completed_study_session_id=?", (session_id,))
    break_id = repo.insert(conn, "session_breaks", {
        "focus_session_id": focus["id"] if focus else None,
        "study_session_id": session_id,
        "started_at": stored_start,
        "ended_at": stored_end,
        "duration_seconds": duration,
        "reason": _reason(values.get("reason")),
        "notes": values.get("notes"),
        "origin": origin,
        "subtracts_from_focus": 1,
        "idempotency_key": f"break:{key}" if key else None,
    })
    totals = pause_totals(conn, session_id=session_id)
    corrected_focus = int(session["duration_seconds"]) - duration
    conn.execute(
        "UPDATE sessoes_estudo SET duration_seconds=?,pause_seconds=?,version=version+1,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
        (corrected_focus, totals["pause_seconds"], session_id),
    )
    after = _session(conn, session_id)
    correction_id = repo.insert(conn, "study_session_corrections", {
        "study_session_id": session_id,
        "break_id": break_id,
        "correction_type": "add_break",
        "before_json": json.dumps(before, ensure_ascii=False),
        "after_json": json.dumps(after, ensure_ascii=False),
        "reason": values.get("correction_reason") or "Pausa esquecida informada pelo usuário",
        "idempotency_key": str(key) if key else None,
    })
    return {
        "session": after,
        "break": repo.one(conn, "SELECT * FROM session_breaks WHERE id=?", (break_id,)),
        "correction": repo.one(conn, "SELECT * FROM study_session_corrections WHERE id=?", (correction_id,)),
        "idempotent": False,
    }
