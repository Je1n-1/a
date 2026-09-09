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
    """Ordena sem deixar um mínimo paralelo eclipsar uma entrega urgente.

    Um mínimo semanal continua sendo protegido, mas não recebe mais um bônus
    absoluto. Assim, uma disciplina curricular em risco ou com prazo iminente
    ocupa a janela crítica primeiro; havendo capacidade, o paralelo ainda
    recebe o mínimo configurado naquela mesma semana.
    """
    weekly_need = weekly_needs.get(item["id"], 0)
    risk_points = {"impossible": 90, "at_risk": 60, "attention": 25, "on_track": 0}.get(item.get("risk"), 0)
    deadline_days = item.get("days_remaining")
    deadline_points = 0 if deadline_days is None else max(0, 20 - min(20, deadline_days))
    urgent_curriculum = bool(
        item.get("kind") == "curriculum" and item.get("to_allocate", 0) > 0
        and (item.get("risk") in {"impossible", "at_risk"} or (deadline_days is not None and deadline_days <= 2))
    )
    return (
        int(urgent_curriculum), risk_points, deadline_points,
        int(weekly_need > 0), effective_priority(item), int(item.get("unallocated_minutes") or 0) / 120,
    )


def _topic_choice(item, current):
    """Escolhe a unidade concreta, sem cair sempre no primeiro tópico.

    A ordem é intencional: conteúdo em andamento, próximo conteúdo liberado,
    revisão vencida e, somente quando não há tópicos, um bloco geral. O saldo
    calculado para a prévia impede que um tópico receba mais esforço que sua
    estimativa enquanto os demais ficam esquecidos.
    """
    topics = [topic for topic in item.get("contents", []) if not topic.get("archived_at")]
    if not topics:
        return None, "bloco geral: a disciplina ainda não possui tópicos"

    def can_receive(topic):
        if not topic.get("prerequisites_completed", True):
            return False
        if item.get("review_mode") and topic.get("status") == "completed":
            due = topic.get("next_review_date")
            return not due or due <= current.isoformat()
        if topic.get("status") == "for_review":
            due = topic.get("next_review_date")
            return not due or due <= current.isoformat()
        return topic.get("status") in {"in_progress", "not_started"}

    candidates = [topic for topic in topics if can_receive(topic)]
    if not candidates:
        return None, None

    # Uma revisão pode ser planejada mesmo depois do esforço de conclusão;
    # tópicos regulares precisam ter saldo concreto para receber um novo bloco.
    regular = [topic for topic in candidates if topic.get("status") in {"in_progress", "not_started"}]
    regular = [topic for topic in regular if topic.get("planning_remaining_minutes") is None or topic.get("planning_remaining_minutes", 0) > 0]
    review = [topic for topic in candidates if topic not in regular]
    candidates = regular or review
    if not candidates:
        return None, None

    rank = {"in_progress": 0, "not_started": 1, "for_review": 2, "completed": 3}
    selected = min(
        candidates,
        key=lambda topic: (
            rank.get(topic.get("status"), 9),
            topic.get("next_evaluation_date") or "9999-12-31",
            int(topic.get("sort_order") or 0),
            topic.get("next_review_date") or "9999-12-31",
            int(topic.get("mastery") or 0),
            int(topic.get("planning_remaining_minutes") or 0) if topic.get("planning_remaining_minutes") is not None else 0,
            topic.get("id") or 0,
        ),
    )
    message = {
        "in_progress": "tópico em andamento",
        "not_started": "próximo tópico com pré-requisitos concluídos",
        "for_review": "tópico marcado para revisão",
        "completed": "revisão dentro da janela",
    }.get(selected.get("status"), "tópico elegível")
    if selected.get("next_evaluation_date"):
        message += f"; avaliação em {selected['next_evaluation_date']}"
    return selected, message


def _can_allocate_item(item, current):
    if not item.get("contents"):
        return True
    topic, _reason = _topic_choice(item, current)
    return topic is not None


def distribute(items, day_windows, start: date, end: date, *, pause_minutes=10,
               default_duration=50, minimum_duration=25, maximum_duration=120):
    """Distribui itens nas janelas livres recebidas.

    ``day_windows`` é ``{date: [(inicio_minuto, fim_minuto), ...]}``, já sem
    blocos existentes e sem horários passados. A função não modifica entradas.
    """
    mutable = [{**item, "contents": [dict(topic) for topic in item.get("contents", [])]} for item in items]
    by_id = {item["id"]: item for item in mutable}
    for item in mutable:
        # Metas recorrentes são controladas por semana, para que uma prévia de
        # 14 ou 30 dias não consuma toda a meta logo nos primeiros dias.
        item["to_allocate"] = max(0, int(item.get("unallocated_minutes") or 0)) if item.get("is_schedulable", True) and item.get("required_study_minutes") else 0
        item["allocated"] = 0

    proposals = []
    weekly_unmet = defaultdict(int)

    def weekly_needs_for(current):
        """Calcula metas e mínimos da semana, já descontando o que existe."""
        monday = (current - timedelta(days=current.weekday())).isoformat()
        values = defaultdict(int)
        for item in mutable:
            if not item.get("is_schedulable", True):
                continue
            goal = int((item.get("weekly_goal_by_week") or {}).get(monday, 0))
            minimum = int((item.get("minimum_by_week") or {}).get(monday, 0))
            required_floor = max(goal, minimum)
            if item.get("required_study_minutes"):
                required_floor = min(required_floor, item["to_allocate"])
            values[item["id"]] = max(0, required_floor)
        return values

    def keep_unmet(values):
        for ident, minutes in values.items():
            if minutes > 0:
                weekly_unmet[ident] += int(minutes)

    cursor = start
    active_week = None
    weekly_needs = defaultdict(int)
    while cursor <= end:
        week_key = (cursor - timedelta(days=cursor.weekday())).isoformat()
        if week_key != active_week:
            if active_week is not None:
                keep_unmet(weekly_needs)
            active_week = week_key
            weekly_needs = weekly_needs_for(cursor)
        windows = [tuple(value) for value in day_windows.get(cursor, [])]
        for window_start, window_end in windows:
            point = window_start
            while point + minimum_duration <= window_end:
                eligible = [
                    item for item in mutable
                    if item.get("is_schedulable", True)
                    and _fits_day(item, cursor)
                    and _can_allocate_item(item, cursor)
                    and (item["to_allocate"] > 0 or weekly_needs.get(item["id"], 0) > 0)
                    and (not item.get("effective_start_date") or cursor.isoformat() >= item["effective_start_date"])
                    and (not item.get("deadline_date") or cursor.isoformat() <= item["deadline_date"])
                ]
                if not eligible:
                    break
                selected = max(eligible, key=lambda item: _candidate_score(item, weekly_needs))
                content, topic_reason = _topic_choice(selected, cursor)
                available = window_end - point
                desired = max(selected["to_allocate"], weekly_needs.get(selected["id"], 0))
                if selected.get("required_study_minutes"):
                    desired = min(desired, selected["to_allocate"])
                if content and content.get("planning_remaining_minutes") is not None and not selected.get("review_mode"):
                    desired = min(desired, int(content["planning_remaining_minutes"]))
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
                    content, topic_reason = _topic_choice(selected, cursor)
                    desired = max(selected["to_allocate"], weekly_needs.get(selected["id"], 0))
                    if selected.get("required_study_minutes"):
                        desired = min(desired, selected["to_allocate"])
                    if content and content.get("planning_remaining_minutes") is not None and not selected.get("review_mode"):
                        desired = min(desired, int(content["planning_remaining_minutes"]))
                    duration = _allocation_duration(selected, available, desired, minimum_duration, maximum_duration, default_duration)

                reason_bits = [
                    f"prioridade efetiva {effective_priority(selected)}/10",
                    selected.get("risk_label") or "No ritmo",
                ]
                if topic_reason:
                    reason_bits.append(topic_reason)
                monday = (cursor - timedelta(days=cursor.weekday())).isoformat()
                if int((selected.get("minimum_by_week") or {}).get(monday, 0)) > 0 and weekly_needs.get(selected["id"], 0) > 0:
                    reason_bits.append("mínimo semanal garantido")
                elif weekly_needs.get(selected["id"], 0) > 0:
                    reason_bits.append("meta semanal distribuída")
                elif selected.get("urgency_reasons"):
                    reason_bits.append(selected["urgency_reasons"][0])
                remaining_before = max(selected["to_allocate"], weekly_needs.get(selected["id"], 0))
                remaining_after = max(
                    max(0, selected["to_allocate"] - duration),
                    max(0, weekly_needs.get(selected["id"], 0) - duration),
                )
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
                    "source": "automatic", "formation_name": selected.get("formation_name"),
                    "deadline_date": selected.get("deadline_date"), "risk_label": selected.get("risk_label"),
                    "automatic_urgency": int(selected.get("automatic_urgency") or 0),
                    "remaining_before_minutes": int(remaining_before), "remaining_after_minutes": int(remaining_after),
                    "topic_progress_percent": content.get("effort_progress_percent") if content else None,
                    "topic_remaining_minutes": content.get("planning_remaining_minutes") if content else None,
                })
                selected["allocated"] += duration
                selected["to_allocate"] = max(0, selected["to_allocate"] - duration)
                if content and content.get("planning_remaining_minutes") is not None and not selected.get("review_mode"):
                    content["planning_remaining_minutes"] = max(0, int(content["planning_remaining_minutes"]) - duration)
                weekly_needs[selected["id"]] = max(0, weekly_needs.get(selected["id"], 0) - duration)
                point += duration + pause_minutes
        cursor += timedelta(days=1)

    if active_week is not None:
        keep_unmet(weekly_needs)
    unscheduled = []
    for item in mutable:
        weekly_left = int(weekly_unmet.get(item["id"], 0))
        left = max(item["to_allocate"], weekly_left)
        if left:
            minimum_unmet = bool(item.get("minimum_weekly_minutes") and weekly_left)
            unscheduled.append({
                "id": item["id"], "name": item["name"], "minutes": int(left),
                "code": "minimum_weekly_unmet" if minimum_unmet else "capacity_insufficient",
                "weekly_unmet_minutes": weekly_left,
                "reason": "Não houve janela livre suficiente para cumprir o mínimo semanal." if minimum_unmet else "Não houve janela livre suficiente no período.",
            })
    return {"sessions": proposals, "items": list(by_id.values()), "unscheduled": unscheduled}
