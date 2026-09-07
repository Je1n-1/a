"""Cálculos determinísticos para planejamento por esforço e capacidade.

Este módulo não conhece Flask nem SQL. ``services.core`` fornece os itens e
janelas já normalizados; assim as regras podem ser exercitadas isoladamente e
não ficam espalhadas pelas rotas HTTP.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta


def clamp(value, low, high):
    return max(low, min(high, value))


def interval_minutes(intervals):
    return sum(max(0, end - start) for start, end in intervals)


def effective_priority(item):
    return int(clamp(int(item.get("priority_base", 3)) + int(item.get("automatic_urgency", 0)), 1, 10))


def urgency(item):
    """Retorna urgência previsível de 0 a 5 e suas causas legíveis.

    A fórmula dá peso à folga de capacidade, não somente ao calendário: dois
    dias com meia hora pendente não ficam artificialmente acima de um déficit
    de várias horas em dez dias.
    """
    deadline = item.get("deadline")
    remaining = max(0, int(item.get("remaining_minutes") or 0))
    capacity = max(0, int(item.get("capacity_until_deadline_minutes") or 0))
    planned = max(0, int(item.get("future_planned_minutes") or 0))
    days = item.get("days_remaining")
    reasons = []
    if not deadline or remaining <= 0:
        return 0, reasons

    score = 0
    unallocated = max(0, remaining - planned)
    deficit = max(0, remaining - capacity)
    if deficit > 0:
        score += 3
        reasons.append(f"déficit de {deficit} min até o prazo")
    elif capacity and remaining / capacity >= 0.8:
        score += 2
        reasons.append("pouca folga de capacidade")
    elif capacity and remaining / capacity >= 0.55:
        score += 1
        reasons.append("folga moderada de capacidade")

    if days is not None:
        if days <= 2 and unallocated > 60:
            score += 2
            reasons.append(f"faltam {days} dia(s)")
        elif days <= 7 and unallocated > 120:
            score += 1
            reasons.append(f"faltam {days} dia(s)")

    if item.get("has_upcoming_evaluation"):
        score += 1
        reasons.append("há avaliação ou entrega próxima")
    if item.get("behind_ideal_pace"):
        score += 1
        reasons.append("ritmo real abaixo do necessário")
    return int(clamp(score, 0, 5)), reasons


def risk(item):
    remaining = max(0, int(item.get("remaining_minutes") or 0))
    if remaining == 0:
        return "on_track", "No ritmo"
    deadline = item.get("deadline")
    if not deadline:
        return "on_track", "Sem prazo definido"
    capacity = max(0, int(item.get("capacity_until_deadline_minutes") or 0))
    unallocated = max(0, int(item.get("unallocated_minutes") or 0))
    if capacity <= 0:
        return "impossible", "Impossível com a disponibilidade atual"
    if remaining > capacity:
        return "impossible", "Impossível com a disponibilidade atual"
    if unallocated > capacity * 0.35:
        return "at_risk", "Em risco"
    if unallocated > 0 or item.get("behind_ideal_pace"):
        return "attention", "Atenção"
    return "on_track", "No ritmo"


def weekly_buckets(start: date, end: date):
    values = []
    cursor = start
    while cursor <= end:
        monday = cursor - timedelta(days=cursor.weekday())
        sunday = monday + timedelta(days=6)
        values.append((max(cursor, monday), min(end, sunday)))
        cursor = sunday + timedelta(days=1)
    return values


def _fits_day(item, current: date):
    allowed = item.get("allowed_weekdays")
    return not allowed or current.weekday() in allowed


def _duration(item, available, minimum, maximum, default):
    preferred = int(item.get("preferred_block_minutes") or default)
    preferred = int(clamp(preferred, minimum, maximum))
    return min(preferred, available)


def _allocation_duration(item, available, desired, minimum, maximum, default):
    """Escolhe um bloco sem deixar uma sobra menor que o mínimo.

    Ex.: meta de 60 min, preferência de 50 e mínimo de 25 deve virar um
    bloco de 60, em vez de 50 + 10 min impossíveis de encaixar.
    """
    preferred = _duration(item, available, minimum, maximum, default)
    duration = min(preferred, desired)
    if duration < minimum:
        return duration
    remainder = desired - duration
    if 0 < remainder < minimum and desired <= available and desired <= maximum:
        return desired
    return duration


def _candidate_score(item, weekly_needs):
    # Mínimos semanais paralelos são atendidos antes de o excedente ser usado
    # pelas disciplinas com prazo. Depois, a prioridade efetiva e o risco
    # controlam a distribuição.
    weekly_need = weekly_needs.get(item["id"], 0)
    risk_points = {"impossible": 90, "at_risk": 60, "attention": 25, "on_track": 0}.get(item.get("risk"), 0)
    deadline_days = item.get("days_remaining")
    deadline_points = 0 if deadline_days is None else max(0, 20 - min(20, deadline_days))
    return (1000 if weekly_need > 0 else 0) + risk_points + deadline_points + effective_priority(item) * 8 + int(item.get("unallocated_minutes") or 0) / 120


def distribute(items, day_windows, start: date, end: date, *, pause_minutes=10,
               default_duration=50, minimum_duration=25, maximum_duration=120):
    """Distribui itens nas janelas livres recebidas.

    ``day_windows`` é ``{date: [(inicio_minuto, fim_minuto), ...]}``, já sem
    blocos existentes e sem horários passados. A função não modifica entradas.
    """
    mutable = [dict(item) for item in items]
    by_id = {item["id"]: item for item in mutable}
    for item in mutable:
        item["to_allocate"] = max(0, int(item.get("unallocated_minutes") or 0))
        item["allocated"] = 0

    proposals = []

    def weekly_needs_for(current):
        """Reinicia a garantia em cada segunda-feira sem ignorar blocos já salvos."""
        monday = (current - timedelta(days=current.weekday())).isoformat()
        is_current_week = monday == (start - timedelta(days=start.weekday())).isoformat()
        values = defaultdict(int)
        for item in mutable:
            if item.get("kind") != "personal":
                continue
            guaranteed = int(item.get("minimum_weekly_minutes") or 0)
            if not guaranteed:
                continue
            already_real = int(item.get("week_real_minutes") or 0) if is_current_week else 0
            already_planned = int((item.get("planned_by_week") or {}).get(monday, 0))
            values[item["id"]] = max(0, guaranteed - already_real - already_planned)
        return values

    cursor = start
    active_week = None
    weekly_needs = defaultdict(int)
    while cursor <= end:
        week_key = (cursor - timedelta(days=cursor.weekday())).isoformat()
        if week_key != active_week:
            active_week = week_key
            weekly_needs = weekly_needs_for(cursor)
        windows = [tuple(value) for value in day_windows.get(cursor, [])]
        for window_start, window_end in windows:
            point = window_start
            while point + minimum_duration <= window_end:
                eligible = [
                    item for item in mutable
                    if _fits_day(item, cursor)
                    and (item["to_allocate"] > 0 or weekly_needs.get(item["id"], 0) > 0)
                    and (not item.get("deadline_date") or cursor.isoformat() <= item["deadline_date"])
                ]
                if not eligible:
                    break
                selected = max(eligible, key=lambda item: _candidate_score(item, weekly_needs))
                available = window_end - point
                desired = max(selected["to_allocate"], weekly_needs.get(selected["id"], 0))
                if selected.get("required_study_minutes"):
                    desired = min(desired, selected["to_allocate"])
                duration = _allocation_duration(selected, available, desired, minimum_duration, maximum_duration, default_duration)
                if duration < minimum_duration:
                    # Não deixa uma sobra minúscula impedir os demais itens:
                    # testa o próximo candidato antes de abandonar a janela.
                    eligible = [item for item in eligible if item["id"] != selected["id"]]
                    alternate = next((item for item in sorted(eligible, key=lambda item: _candidate_score(item, weekly_needs), reverse=True)
                                      if _allocation_duration(item, available, max(item["to_allocate"], weekly_needs.get(item["id"], 0)), minimum_duration, maximum_duration, default_duration) >= minimum_duration), None)
                    if not alternate:
                        break
                    selected = alternate
                    desired = max(selected["to_allocate"], weekly_needs.get(selected["id"], 0))
                    if selected.get("required_study_minutes"):
                        desired = min(desired, selected["to_allocate"])
                    duration = _allocation_duration(selected, available, desired, minimum_duration, maximum_duration, default_duration)

                content = None
                for candidate in selected.get("contents", []):
                    if (candidate.get("status") != "completed" or selected.get("review_mode")) and not candidate.get("archived_at"):
                        content = candidate
                        break
                reason_bits = [
                    f"prioridade efetiva {effective_priority(selected)}/10",
                    selected.get("risk_label") or "No ritmo",
                ]
                if weekly_needs.get(selected["id"], 0) > 0:
                    reason_bits.append("mínimo semanal garantido")
                elif selected.get("urgency_reasons"):
                    reason_bits.append(selected["urgency_reasons"][0])
                proposals.append({
                    "study_subject_id": selected["study_subject_id"],
                    "topic_id": content.get("id") if content else None,
                    "scheduled_date": cursor.isoformat(),
                    "start_time": f"{point // 60:02d}:{point % 60:02d}",
                    "planned_duration_minutes": int(duration),
                    "subject_name": selected["name"],
                    "topic_name": content.get("name") if content else None,
                    "reason": "; ".join(reason_bits) + ".",
                    "item_id": selected["id"],
                    "priority_effective": effective_priority(selected),
                })
                selected["allocated"] += duration
                selected["to_allocate"] = max(0, selected["to_allocate"] - duration)
                weekly_needs[selected["id"]] = max(0, weekly_needs.get(selected["id"], 0) - duration)
                point += duration + pause_minutes
        cursor += timedelta(days=1)

    unscheduled = []
    for item in mutable:
        left = max(item["to_allocate"], weekly_needs.get(item["id"], 0))
        if left:
            unscheduled.append({
                "id": item["id"], "name": item["name"], "minutes": int(left),
                "reason": "Não houve janela livre suficiente no período.",
            })
    return {"sessions": proposals, "items": list(by_id.values()), "unscheduled": unscheduled}
