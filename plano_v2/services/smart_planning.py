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


def _date_range(start: date, end: date):
    cursor = start
    while cursor <= end:
        yield cursor
        cursor += timedelta(days=1)


def _fits_day(item, current: date):
    allowed = item.get("allowed_weekdays")
    return not allowed or current.weekday() in allowed


def _duration(item, available, minimum, maximum, default):
    preferred = int(item.get("preferred_block_minutes") or default)
    preferred = int(clamp(preferred, minimum, maximum))
    return min(preferred, available)


def _allocation_duration(item, available, desired, minimum, maximum, default, pause=0):
    """Escolhe um bloco sem deixar uma sobra menor que o mínimo.

    Ex.: meta de 60 min, preferência de 50 e mínimo de 25 deve virar um
    bloco de 60, em vez de 50 + 10 min impossíveis de encaixar.
    """
    preferred = _duration(item, available, minimum, maximum, default)
    duration = min(preferred, desired)
    if duration < minimum:
        return duration
    remainder = desired - duration
    # A preferência é uma meta de ergonomia, não uma barreira rígida. Quando
    # quebrar o alvo em dois blocos exigiria uma pausa que não cabe na janela,
    # usamos uma sessão adaptada e preservamos a cota do dia.
    if (
        remainder >= minimum
        and desired <= available
        and desired <= maximum
        and duration + max(0, int(pause)) + remainder > available
    ):
        return desired
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


def _ceil_div(value, divisor):
    return (max(0, int(value)) + max(1, int(divisor)) - 1) // max(1, int(divisor))


def build_daily_targets(total_minutes, capacity_by_day):
    """Distribui uma demanda total por dias usando *water-filling*.

    A cota diária é calculada uma única vez a partir da demanda do período.
    Dias de baixa capacidade são preenchidos até o limite e o restante é
    dividido de modo uniforme entre os demais. Assim, o motor não recalcula a
    média com o saldo mutável a cada bloco — a origem da concentração precoce.
    """
    requested = max(0, int(total_minutes or 0))
    capacities = {
        str(day): max(0, int(minutes or 0))
        for day, minutes in (capacity_by_day or {}).items()
    }
    targets = {day: 0 for day in capacities}
    amount = min(requested, sum(capacities.values()))
    if amount <= 0:
        return targets

    ordered = sorted((capacity, day) for day, capacity in capacities.items() if capacity > 0)
    previous = 0
    index = 0
    while index < len(ordered):
        level = ordered[index][0]
        active = len(ordered) - index
        required_to_level = (level - previous) * active
        if amount >= required_to_level:
            amount -= required_to_level
            previous = level
            while index < len(ordered) and ordered[index][0] == level:
                targets[ordered[index][1]] = level
                index += 1
            continue

        increment, remainder = divmod(amount, active)
        for position, (_capacity, day) in enumerate(ordered[index:]):
            targets[day] = previous + increment + (1 if position < remainder else 0)
        amount = 0
        break

    # Se toda a capacidade foi usada, os patamares já saturados foram gravados
    # dentro do laço. Datas com mais capacidade só aparecem aqui nesse caso.
    if amount == 0 and index >= len(ordered):
        for capacity, day in ordered:
            targets[day] = capacity
    return targets


def _required_day_target(item, minimum, default):
    """Cota de hoje para esforço com prazo, sem concentrar tudo no começo.

    Quando a necessidade diária cabe em uma sessão, ela é distribuída de forma
    proporcional entre os dias restantes. Se a média ficar menor que uma sessão
    mínima, blocos preferidos são espaçados; uma matéria de 60 min em 42 dias
    não vira 25 min nos três primeiros dias por acidente.
    """
    remaining = max(0, int(item.get("to_allocate") or 0))
    if not remaining:
        return 0
    total_days = max(1, int(item.get("_pace_days_total") or item.get("available_days_until_deadline") or 1))
    seen_days = max(0, int(item.get("_pace_days_seen") or 0))
    remaining_days = max(1, total_days - seen_days)
    daily = _ceil_div(remaining, remaining_days)
    if daily >= minimum:
        return daily
    preferred = max(minimum, int(item.get("preferred_block_minutes") or default))
    # Se tudo o que resta cabe em uma sessão preferida, não fragmentamos a
    # demanda em uma parte mínima e um resto impossível de planejar depois.
    # Ex.: 60 min em uma disciplina de longo prazo continuam sendo uma sessão
    # de 60 min, ainda que a média diária seja menor que o mínimo configurado.
    if remaining <= preferred:
        return remaining if seen_days == 0 else 0
    block = min(preferred, remaining)
    blocks = _ceil_div(remaining, block)
    # No primeiro dia uma sessão pequena já cria impulso; os próximos blocos
    # são espaçados conforme a quantidade que ainda precisa ocorrer.
    spacing = max(1, remaining_days // max(1, blocks))
    return block if seen_days % spacing == 0 else 0


def _has_usable_window(day_windows, current, minimum):
    values = day_windows.get(current, day_windows.get(current.isoformat(), []))
    return any(end - start >= minimum for start, end in values)


def distribute(items, day_windows, start: date, end: date, *, pause_minutes=10,
               default_duration=50, minimum_duration=25, maximum_duration=120):
    """Distribui itens nas janelas livres recebidas.

    ``day_windows`` é ``{date: [(inicio_minuto, fim_minuto), ...]}``, já sem
    blocos existentes e sem horários passados. A função não modifica entradas.
    """
    mutable = [{**item, "contents": [dict(topic) for topic in item.get("contents", [])]} for item in items]
    by_id = {item["id"]: item for item in mutable}
    pause_minutes = max(0, int(pause_minutes or 0))

    def windows_for(current):
        return [tuple(value) for value in day_windows.get(current, day_windows.get(current.isoformat(), []))]

    def eligible_on(item, current):
        return (
            item.get("is_schedulable", True)
            and _fits_day(item, current)
            and _can_allocate_item(item, current)
            and (not item.get("effective_start_date") or current.isoformat() >= item["effective_start_date"])
            and (not item.get("deadline_date") or current.isoformat() <= item["deadline_date"])
        )

    def capacity_by_day(item, first, last):
        return {
            current.isoformat(): interval_minutes(windows_for(current))
            for current in _date_range(first, last)
            if eligible_on(item, current)
        }

    def compact_small_targets(targets, preferred, capacities):
        """Agrupa cotas menores que o mínimo em sessões reais e espaçadas."""
        total = sum(targets.values())
        if not total or total >= minimum_duration * len([value for value in targets.values() if value]):
            return targets
        keys = [key for key in sorted(capacities) if int(capacities.get(key) or 0) >= minimum_duration]
        if not keys:
            return targets
        grouped = {key: 0 for key in targets}
        block = max(minimum_duration, min(maximum_duration, int(preferred or default_duration)))
        blocks, remaining = [], total
        while remaining > 0:
            amount = min(block, remaining)
            if 0 < remaining - amount < minimum_duration:
                amount = remaining
            blocks.append(amount)
            remaining -= amount
        count = len(blocks)
        positions = [round(index * (len(keys) - 1) / max(1, count - 1)) for index in range(count)]
        for amount, position in zip(blocks, positions):
            key = next(
                (
                    keys[(position + offset) % len(keys)]
                    for offset in range(len(keys))
                    if int(capacities.get(keys[(position + offset) % len(keys)]) or 0) - grouped[keys[(position + offset) % len(keys)]] >= amount
                ),
                None,
            )
            if key is None:
                return targets
            grouped[key] += amount
        return grouped

    weekly_targets = {}
    for item in mutable:
        required = bool(item.get("required_study_minutes"))
        period_demand = max(
            0,
            int(
                item.get("demand_in_period_minutes")
                if item.get("demand_in_period_minutes") is not None
                else item.get("unallocated_minutes") or 0
            ),
        )
        item["_period_demand_minutes"] = period_demand if required else 0
        item["to_allocate"] = item["_period_demand_minutes"]
        item["allocated"] = 0
        item["_deadline_allocated"] = 0
        item["_daily_targets"] = {}
        if required and item.get("is_schedulable", True):
            item_capacity = capacity_by_day(item, start, end)
            item["_daily_targets"] = compact_small_targets(
                build_daily_targets(period_demand, item_capacity),
                item.get("preferred_block_minutes"), item_capacity,
            )

        for week_first, week_last in weekly_buckets(start, end):
            monday = (week_first - timedelta(days=week_first.weekday())).isoformat()
            weekly_need = max(
                int((item.get("weekly_goal_by_week") or {}).get(monday, 0)),
                int((item.get("minimum_by_week") or {}).get(monday, 0)),
            )
            if required:
                weekly_need = min(weekly_need, period_demand)
            if weekly_need <= 0:
                continue
            week_capacity = capacity_by_day(item, week_first, week_last)
            weekly_targets[(item["id"], monday)] = compact_small_targets(
                build_daily_targets(weekly_need, week_capacity),
                item.get("preferred_block_minutes"), week_capacity,
            )

    proposals = []
    weekly_unmet = defaultdict(int)
    allocated_by_week = defaultdict(int)

    def weekly_needs_for(current):
        monday = (current - timedelta(days=current.weekday())).isoformat()
        values = defaultdict(int)
        for item in mutable:
            targets = weekly_targets.get((item["id"], monday), {})
            values[item["id"]] = max(0, sum(targets.values()) - allocated_by_week[(item["id"], monday)])
        return values

    def deadline_need_for(item, current):
        if not item.get("required_study_minutes"):
            return 0
        due_so_far = sum(value for day, value in item["_daily_targets"].items() if day <= current.isoformat())
        return max(0, due_so_far - item["_deadline_allocated"])

    def weekly_need_for(item, current):
        monday = (current - timedelta(days=current.weekday())).isoformat()
        targets = weekly_targets.get((item["id"], monday), {})
        due_so_far = sum(value for day, value in targets.items() if day <= current.isoformat())
        return max(0, due_so_far - allocated_by_week[(item["id"], monday)])

    def keep_week_unmet(current):
        monday = (current - timedelta(days=current.weekday())).isoformat()
        for item in mutable:
            targets = weekly_targets.get((item["id"], monday), {})
            left = max(0, sum(targets.values()) - allocated_by_week[(item["id"], monday)])
            if left:
                weekly_unmet[item["id"]] += left

    cursor = start
    active_week = None
    while cursor <= end:
        week_key = (cursor - timedelta(days=cursor.weekday())).isoformat()
        if active_week is not None and week_key != active_week:
            keep_week_unmet(cursor - timedelta(days=1))
        active_week = week_key
        weekly_needs = weekly_needs_for(cursor)
        for window_start, window_end in windows_for(cursor):
            point = window_start
            while point + minimum_duration <= window_end:
                eligible = [
                    item for item in mutable
                    if eligible_on(item, cursor)
                    and (deadline_need_for(item, cursor) > 0 or weekly_need_for(item, cursor) > 0)
                ]
                if not eligible:
                    break
                selected = max(eligible, key=lambda item: _candidate_score(item, weekly_needs))
                content, topic_reason = _topic_choice(selected, cursor)
                available = window_end - point
                deadline_need = deadline_need_for(selected, cursor)
                weekly_need = weekly_need_for(selected, cursor)
                desired = max(deadline_need, weekly_need)
                if selected.get("required_study_minutes"):
                    desired = min(desired, selected["to_allocate"])
                if content and content.get("planning_remaining_minutes") is not None and not selected.get("review_mode"):
                    desired = min(desired, int(content["planning_remaining_minutes"]))
                duration = _allocation_duration(
                    selected, available, desired, minimum_duration, maximum_duration,
                    default_duration, pause_minutes,
                )
                if duration < minimum_duration:
                    alternatives = []
                    for item in eligible:
                        if item["id"] == selected["id"]:
                            continue
                        alternative_desired = max(deadline_need_for(item, cursor), weekly_need_for(item, cursor))
                        alternative_duration = _allocation_duration(
                            item, available, alternative_desired, minimum_duration,
                            maximum_duration, default_duration, pause_minutes,
                        )
                        if alternative_duration >= minimum_duration:
                            alternatives.append(item)
                    if not alternatives:
                        break
                    selected = max(alternatives, key=lambda item: _candidate_score(item, weekly_needs))
                    content, topic_reason = _topic_choice(selected, cursor)
                    desired = max(deadline_need_for(selected, cursor), weekly_need_for(selected, cursor))
                    if selected.get("required_study_minutes"):
                        desired = min(desired, selected["to_allocate"])
                    if content and content.get("planning_remaining_minutes") is not None and not selected.get("review_mode"):
                        desired = min(desired, int(content["planning_remaining_minutes"]))
                    duration = _allocation_duration(
                        selected, available, desired, minimum_duration, maximum_duration,
                        default_duration, pause_minutes,
                    )

                monday = (cursor - timedelta(days=cursor.weekday())).isoformat()
                reason_bits = [
                    f"prioridade efetiva {effective_priority(selected)}/10",
                    selected.get("risk_label") or "No ritmo",
                ]
                if topic_reason:
                    reason_bits.append(topic_reason)
                if int((selected.get("minimum_by_week") or {}).get(monday, 0)) > 0 and weekly_need_for(selected, cursor) > 0:
                    reason_bits.append("mínimo semanal garantido")
                elif weekly_need_for(selected, cursor) > 0:
                    reason_bits.append("meta semanal distribuída")
                elif selected.get("urgency_reasons"):
                    reason_bits.append(selected["urgency_reasons"][0])
                remaining_before = max(selected["to_allocate"], weekly_needs.get(selected["id"], 0))
                proposal = {
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
                    "remaining_before_minutes": int(remaining_before),
                    "topic_progress_percent": content.get("effort_progress_percent") if content else None,
                    "topic_remaining_minutes": content.get("planning_remaining_minutes") if content else None,
                }
                selected["allocated"] += duration
                selected["_deadline_allocated"] += min(duration, selected["to_allocate"])
                selected["to_allocate"] = max(0, selected["to_allocate"] - duration)
                allocated_by_week[(selected["id"], monday)] += duration
                weekly_needs[selected["id"]] = max(0, weekly_needs.get(selected["id"], 0) - duration)
                if content and content.get("planning_remaining_minutes") is not None and not selected.get("review_mode"):
                    content["planning_remaining_minutes"] = max(0, int(content["planning_remaining_minutes"]) - duration)
                proposal["remaining_after_minutes"] = int(max(selected["to_allocate"], weekly_needs.get(selected["id"], 0)))
                proposals.append(proposal)

                point += duration
                # Não se cria uma pausa fictícia após o último bloco. Uma
                # pausa só ocupa a janela quando ainda cabe uma sessão real.
                if point + pause_minutes + minimum_duration <= window_end:
                    point += pause_minutes
        cursor += timedelta(days=1)

    if active_week is not None:
        keep_week_unmet(end)
    unscheduled = []
    for item in mutable:
        weekly_left = int(weekly_unmet.get(item["id"], 0))
        deadline_left = max(0, int(item["_period_demand_minutes"]) - int(item["_deadline_allocated"]))
        shortage = max(deadline_left, weekly_left)
        item["scheduled_in_preview_minutes"] = int(item["_deadline_allocated"] if item.get("required_study_minutes") else item["allocated"])
        item["deferred_beyond_preview_minutes"] = max(
            0,
            int(item.get("deferred_beyond_preview_minutes") or 0),
            int(item.get("unallocated_minutes") or 0) - int(item["_period_demand_minutes"]),
        ) if item.get("required_study_minutes") else 0
        item["unallocated_due_to_capacity_minutes"] = int(shortage)
        item["allocation_state"] = "capacity_insufficient" if shortage else "scheduled"
        if shortage:
            minimum_unmet = bool(item.get("minimum_weekly_minutes") and weekly_left)
            unscheduled.append({
                "id": item["id"], "name": item["name"], "minutes": int(shortage),
                "code": "minimum_weekly_unmet" if minimum_unmet else "capacity_insufficient",
                "weekly_unmet_minutes": weekly_left,
                "reason": "Não houve janela livre suficiente para cumprir o mínimo semanal." if minimum_unmet else "Não houve janela livre suficiente no período.",
            })
        for key in ("_period_demand_minutes", "_daily_targets", "_deadline_allocated"):
            item.pop(key, None)
    return {"sessions": proposals, "items": list(by_id.values()), "unscheduled": unscheduled}
