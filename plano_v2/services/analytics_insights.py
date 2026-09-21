"""Séries analíticas reconciliáveis com sessões e pausas reais."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta

from config import LOCAL_TIMEZONE
from database.repositories import core as repo


class AnalyticsInsightsError(ValueError):
    pass


def _day(value, label="Data") -> date:
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError) as error:
        raise AnalyticsInsightsError(f"{label} deve usar AAAA-MM-DD.") from error


def _timestamp(value) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=LOCAL_TIMEZONE)
    return parsed.astimezone(LOCAL_TIMEZONE)


def _range(start=None, end=None):
    today = datetime.now(LOCAL_TIMEZONE).date()
    first = _day(start) if start else today - timedelta(days=29)
    last = _day(end) if end else today
    if last < first:
        raise AnalyticsInsightsError("A data final não pode ser anterior à inicial.")
    if (last - first).days > 366:
        raise AnalyticsInsightsError("O período analítico deve ter no máximo 367 dias.")
    return first, last


def _session_filters(start: date, end: date, filters: dict):
    clauses = ["x.date BETWEEN ? AND ?"]
    params = [start.isoformat(), end.isoformat()]
    study_id = filters.get("study_subject_id") or filters.get("item_id")
    if study_id not in (None, ""):
        clauses.append("x.study_subject_id=?")
        params.append(int(study_id))
    formation_id = filters.get("formation_id")
    if formation_id not in (None, ""):
        clauses.append("""(
          COALESCE(s.related_formation_id,d.formation_id)=?
          OR EXISTS (
            SELECT 1 FROM curriculum_study_links sl
            JOIN disciplinas_grade linked ON linked.id=sl.curriculum_subject_id
            WHERE sl.canonical_study_id=s.id AND linked.formation_id=?
          )
        )""")
        params.extend((int(formation_id), int(formation_id)))
    campaign_id = filters.get("campaign_id")
    if campaign_id not in (None, ""):
        clauses.append("x.review_campaign_id=?")
        params.append(int(campaign_id))
    purpose = filters.get("purpose")
    if purpose not in (None, ""):
        if purpose not in {"study", "review"}:
            raise AnalyticsInsightsError("Finalidade analítica inválida.")
        clauses.append("x.purpose=?")
        params.append(purpose)
    return clauses, params


def _split_interval(start: datetime, end: datetime):
    cursor = start
    while cursor < end:
        boundary = datetime.combine(cursor.date() + timedelta(days=1), time.min, tzinfo=LOCAL_TIMEZONE)
        segment_end = min(end, boundary)
        yield cursor.date().isoformat(), max(0, int((segment_end - cursor).total_seconds()))
        cursor = segment_end


def _subtract_segments(start: datetime, end: datetime, breaks: list[dict]):
    segments = [(start, end)]
    for item in breaks:
        if not item.get("started_at") or not item.get("ended_at"):
            continue
        pause_start, pause_end = _timestamp(item["started_at"]), _timestamp(item["ended_at"])
        next_segments = []
        for left, right in segments:
            if pause_end <= left or pause_start >= right:
                next_segments.append((left, right))
                continue
            if pause_start > left:
                next_segments.append((left, min(pause_start, right)))
            if pause_end < right:
                next_segments.append((max(pause_end, left), right))
        segments = next_segments
    return segments


def _session_focus_by_day(session: dict, breaks: list[dict]):
    expected = int(session.get("duration_seconds") or 0)
    if not session.get("started_at") or not session.get("ended_at"):
        return {session["date"]: expected}, "date_only"
    try:
        start, end = _timestamp(session["started_at"]), _timestamp(session["ended_at"])
    except (TypeError, ValueError):
        return {session["date"]: expected}, "date_only"
    if end <= start:
        return {session["date"]: expected}, "date_only"
    pieces = defaultdict(int)
    segments = _subtract_segments(start, end, breaks)
    raw_total = 0
    for left, right in segments:
        for selected_date, seconds in _split_interval(left, right):
            pieces[selected_date] += seconds
            raw_total += seconds
    if not raw_total:
        return {session["date"]: expected}, "date_only"
    # Recuperações e ajustes podem tornar a duração oficial diferente da soma
    # geométrica. A escala mantém o total factual sem inventar minutos.
    allocated = 0
    keys = sorted(pieces)
    for index, key in enumerate(keys):
        if index == len(keys) - 1:
            pieces[key] = max(0, expected - allocated)
        else:
            pieces[key] = round(expected * pieces[key] / raw_total)
            allocated += pieces[key]
    return dict(pieces), "timestamp"


def _breaks_by_day(session: dict, breaks: list[dict]):
    values = []
    for item in breaks:
        if item.get("started_at") and item.get("ended_at"):
            start, end = _timestamp(item["started_at"]), _timestamp(item["ended_at"])
            for selected_date, seconds in _split_interval(start, end):
                values.append((selected_date, seconds, item.get("reason") or "unspecified", "timestamp"))
        else:
            values.append((session["date"], int(item.get("duration_seconds") or 0), item.get("reason") or "unspecified", "duration_only"))
    return values


def build(conn, start=None, end=None, **filters) -> dict:
    first, last = _range(start, end)
    clauses, params = _session_filters(first, last, filters)
    sessions = repo.many(conn, """
        SELECT x.*,COALESCE(d.name,s.personal_name) subject_name,
          d.formation_id primary_formation_id,t.name topic_name
        FROM sessoes_estudo x
        JOIN materias_estudo s ON s.id=x.study_subject_id
        LEFT JOIN disciplinas_grade d ON d.id=s.curriculum_subject_id
        LEFT JOIN topicos t ON t.id=x.topic_id
        WHERE """ + " AND ".join(clauses) + " ORDER BY x.date,x.id", params)
    session_ids = [row["id"] for row in sessions]
    breaks_by_session = defaultdict(list)
    if session_ids:
        placeholders = ",".join("?" for _ in session_ids)
        for item in repo.many(conn, f"SELECT * FROM session_breaks WHERE study_session_id IN ({placeholders}) ORDER BY id", session_ids):
            breaks_by_session[item["study_session_id"]].append(item)

    daily = {
        (first + timedelta(days=offset)).isoformat(): {
            "date": (first + timedelta(days=offset)).isoformat(),
            "focus_seconds": 0,
            "pause_seconds": 0,
            "planned_minutes": 0,
            "subjects": {},
            "pause_reasons": {},
            "timeline_precision": "timestamp",
        }
        for offset in range((last - first).days + 1)
    }
    for session in sessions:
        session_breaks = breaks_by_session.get(session["id"], [])
        focus_parts, precision = _session_focus_by_day(session, session_breaks)
        for selected_date, seconds in focus_parts.items():
            if selected_date not in daily:
                continue
            item = daily[selected_date]
            item["focus_seconds"] += seconds
            subject = item["subjects"].setdefault(str(session["study_subject_id"]), {
                "study_subject_id": session["study_subject_id"],
                "name": session["subject_name"],
                "focus_seconds": 0,
                "sessions": [],
            })
            subject["focus_seconds"] += seconds
            if session["id"] not in subject["sessions"]:
                subject["sessions"].append(session["id"])
            if precision != "timestamp":
                item["timeline_precision"] = "date_only"
        for selected_date, seconds, reason, break_precision in _breaks_by_day(session, session_breaks):
            if selected_date not in daily:
                continue
            item = daily[selected_date]
            item["pause_seconds"] += seconds
            item["pause_reasons"][reason] = item["pause_reasons"].get(reason, 0) + seconds
            if break_precision != "timestamp":
                item["timeline_precision"] = "date_only"

    planned_clauses = ["p.scheduled_date BETWEEN ? AND ?", "p.status IN ('planned','completed')"]
    planned_params = [first.isoformat(), last.isoformat()]
    study_id = filters.get("study_subject_id") or filters.get("item_id")
    if study_id not in (None, ""):
        planned_clauses.append("p.study_subject_id=?")
        planned_params.append(int(study_id))
    if filters.get("campaign_id") not in (None, ""):
        planned_clauses.append("p.review_campaign_id=?")
        planned_params.append(int(filters["campaign_id"]))
    if filters.get("purpose") not in (None, ""):
        planned_clauses.append("p.intent=?")
        planned_params.append(filters["purpose"])
    planned = repo.many(conn, """
        SELECT p.scheduled_date,COALESCE(SUM(p.planned_duration_minutes),0) minutes
        FROM sessoes_planejadas p
        WHERE """ + " AND ".join(planned_clauses) + " GROUP BY p.scheduled_date", planned_params)
    for row in planned:
        if row["scheduled_date"] in daily:
            daily[row["scheduled_date"]]["planned_minutes"] = int(row["minutes"] or 0)

    mastery_clauses = ["date(o.observed_at) BETWEEN ? AND ?", "o.kind='mastery'"]
    mastery_params = [first.isoformat(), last.isoformat()]
    if study_id not in (None, ""):
        mastery_clauses.append("o.study_subject_id=?")
        mastery_params.append(int(study_id))
    mastery = repo.many(conn, """
        SELECT o.*,COALESCE(d.name,s.personal_name) subject_name
        FROM study_observations o JOIN materias_estudo s ON s.id=o.study_subject_id
        LEFT JOIN disciplinas_grade d ON d.id=s.curriculum_subject_id
        WHERE """ + " AND ".join(mastery_clauses) + " ORDER BY o.observed_at,o.id", mastery_params)

    rhythm_clauses = ["date(r.calculated_at) BETWEEN ? AND ?"]
    rhythm_params = [first.isoformat(), last.isoformat()]
    if study_id not in (None, ""):
        rhythm_clauses.append("r.study_subject_id=?")
        rhythm_params.append(int(study_id))
    rhythm = repo.many(conn, """
        SELECT r.*,COALESCE(d.name,s.personal_name) subject_name
        FROM recommendation_snapshots r JOIN materias_estudo s ON s.id=r.study_subject_id
        LEFT JOIN disciplinas_grade d ON d.id=s.curriculum_subject_id
        WHERE """ + " AND ".join(rhythm_clauses) + " ORDER BY r.calculated_at,r.id", rhythm_params)

    difficulty_clauses = ["date(o.observed_at) BETWEEN ? AND ?", "o.kind='difficulty'"]
    difficulty_params = [first.isoformat(), last.isoformat()]
    if study_id not in (None, ""):
        difficulty_clauses.append("o.study_subject_id=?")
        difficulty_params.append(int(study_id))
    difficulty = repo.many(conn, """
        SELECT o.*,COALESCE(d.name,s.personal_name) subject_name
        FROM study_observations o JOIN materias_estudo s ON s.id=o.study_subject_id
        LEFT JOIN disciplinas_grade d ON d.id=s.curriculum_subject_id
        WHERE """ + " AND ".join(difficulty_clauses) + " ORDER BY o.observed_at,o.id", difficulty_params)

    budget_clauses = ["date(b.created_at) BETWEEN ? AND ?"]
    budget_params = [first.isoformat(), last.isoformat()]
    if study_id not in (None, ""):
        budget_clauses.append("o.study_subject_id=?")
        budget_params.append(int(study_id))
    budget_history = repo.many(conn, """
        SELECT b.*,o.study_subject_id,o.cycle_number,
          COALESCE(d.name,s.personal_name,o.title) subject_name
        FROM study_budget_revisions b
        JOIN study_objectives o ON o.id=b.objective_id
        JOIN materias_estudo s ON s.id=o.study_subject_id
        LEFT JOIN disciplinas_grade d ON d.id=s.curriculum_subject_id
        WHERE """ + " AND ".join(budget_clauses) + " ORDER BY b.created_at,b.id", budget_params)

    result_rows = repo.many(conn, """
        SELECT r.* FROM daily_study_results r
        WHERE r.date BETWEEN ? AND ? ORDER BY r.date,r.id
    """, (first.isoformat(), last.isoformat()))
    result_ids = [row["id"] for row in result_rows]
    reasons_by_result = defaultdict(list)
    if result_ids:
        placeholders = ",".join("?" for _ in result_ids)
        for row in repo.many(conn, f"SELECT * FROM daily_study_result_reasons WHERE daily_result_id IN ({placeholders}) ORDER BY reason", result_ids):
            reasons_by_result[row["daily_result_id"]].append(row["reason"])
    reason_days = defaultdict(int)
    for row in result_rows:
        row["reasons"] = reasons_by_result[row["id"]]
        for reason in set(row["reasons"]):
            reason_days[reason] += 1

    daily_rows = []
    for item in daily.values():
        item["subjects"] = sorted(item["subjects"].values(), key=lambda value: (-value["focus_seconds"], value["name"]))
        daily_rows.append(item)
    total_focus = sum(item["focus_seconds"] for item in daily_rows)
    total_pause = sum(item["pause_seconds"] for item in daily_rows)
    planned_days = sum(1 for item in daily_rows if item["planned_minutes"] > 0)
    studied_days = sum(1 for item in daily_rows if item["focus_seconds"] > 0)
    return {
        "start": first.isoformat(),
        "end": last.isoformat(),
        "filters": {key: value for key, value in filters.items() if value not in (None, "")},
        "totals": {
            "focus_seconds": total_focus,
            "pause_seconds": total_pause,
            "sessions": len(sessions),
            "days_studied": studied_days,
            "days_planned": planned_days,
            "average_focus_seconds_per_studied_day": round(total_focus / studied_days) if studied_days else 0,
            "average_focus_seconds_per_planned_day": round(total_focus / planned_days) if planned_days else 0,
        },
        "daily": daily_rows,
        "mastery_observations": mastery,
        "difficulty_observations": difficulty,
        "rhythm_history": rhythm,
        "budget_history": budget_history,
        "daily_results": result_rows,
        "daily_result_analysis": {
            "answered_days": len(result_rows),
            "period_days": len(daily_rows),
            "coverage_percent": round(len(result_rows) * 100 / len(daily_rows), 1) if daily_rows else 0,
            "reason_day_counts": dict(sorted(reason_days.items(), key=lambda item: (-item[1], item[0]))),
            "multiple_choice": True,
        },
        "sessions": sessions,
    }
