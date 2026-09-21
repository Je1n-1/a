"""Núcleo puro do planejamento interativo.

O módulo não conhece Flask, SQLite ou relógio global. O adaptador entrega um
snapshot completo e ``plan`` devolve uma proposta determinística. Nenhuma
função deste arquivo escreve dados ou infere fatos ausentes.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
import math
from typing import Iterable


POLICY_VERSION = "interactive-v1"


class PlanningError(ValueError):
    def __init__(self, message: str, code: str = "invalid_planning_input"):
        super().__init__(message)
        self.code = code


def _day(value) -> date:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError) as error:
        raise PlanningError("Uma data do planejamento é inválida.", "invalid_date") from error


def _days(first: date, last: date) -> Iterable[date]:
    cursor = first
    while cursor <= last:
        yield cursor
        cursor += timedelta(days=1)


def _minute(value) -> int:
    if isinstance(value, int):
        return value
    text = str(value or "")
    try:
        hour, minute = (int(piece) for piece in text.split(":", 1))
    except (TypeError, ValueError) as error:
        raise PlanningError("Um horário do planejamento é inválido.", "invalid_time") from error
    result = hour * 60 + minute
    if not 0 <= result <= 1440 or not 0 <= minute < 60:
        raise PlanningError("Um horário do planejamento é inválido.", "invalid_time")
    return result


def _clock(value: int) -> str:
    return f"{int(value) // 60:02d}:{int(value) % 60:02d}"


def merge_intervals(values) -> list[list[int]]:
    """Une intervalos sobrepostos/adjacentes sem contar relógio duas vezes."""
    intervals = sorted(
        [max(0, _minute(left)), min(1440, _minute(right))]
        for left, right in (values or [])
        if _minute(right) > _minute(left)
    )
    merged: list[list[int]] = []
    for left, right in intervals:
        if merged and left <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], right)
        else:
            merged.append([left, right])
    return merged


def subtract_intervals(values, occupied) -> list[list[int]]:
    remaining = merge_intervals(values)
    for blocked_left, blocked_right in merge_intervals(occupied):
        next_values = []
        for left, right in remaining:
            if blocked_right <= left or blocked_left >= right:
                next_values.append([left, right])
                continue
            if left < blocked_left:
                next_values.append([left, blocked_left])
            if blocked_right < right:
                next_values.append([blocked_right, right])
        remaining = next_values
    return remaining


def interval_minutes(values) -> int:
    return sum(max(0, int(right) - int(left)) for left, right in values or [])


def largest_remainder(total: int, weights: dict[int, float]) -> dict[int, int]:
    """Converte uma divisão proporcional em inteiros conservando a soma."""
    requested = max(0, int(total or 0))
    positive = {key: max(0.0, float(value or 0)) for key, value in weights.items()}
    denominator = sum(positive.values())
    if not requested or denominator <= 0:
        return {key: 0 for key in weights}
    raw = {key: requested * value / denominator for key, value in positive.items()}
    result = {key: math.floor(value) for key, value in raw.items()}
    left = requested - sum(result.values())
    order = sorted(raw, key=lambda key: (-(raw[key] - result[key]), key))
    for key in order[:left]:
        result[key] += 1
    return result


def allocate_with_caps(total: int, caps: dict[str, int], weights: dict[str, float] | None = None) -> dict[str, int]:
    """Distribui um inteiro respeitando tetos, sem perda por arredondamento."""
    remaining = max(0, min(int(total or 0), sum(max(0, int(value)) for value in caps.values())))
    result = {key: 0 for key in caps}
    active = {key for key, value in caps.items() if int(value or 0) > 0}
    while remaining and active:
        basis = {
            key: max(0.0, float((weights or caps).get(key, 0) or 0))
            for key in active
        }
        if not sum(basis.values()):
            basis = {key: 1.0 for key in active}
        share = largest_remainder(remaining, basis)
        progressed = 0
        for key in sorted(active):
            room = max(0, int(caps[key]) - result[key])
            amount = min(room, share.get(key, 0))
            result[key] += amount
            remaining -= amount
            progressed += amount
        active = {key for key in active if result[key] < int(caps[key])}
        if not progressed and remaining:
            key = min(active) if active else None
            if key is None:
                break
            result[key] += 1
            remaining -= 1
    return result


def study_weight(difficulty, mastery) -> int:
    if difficulty is None or mastery is None:
        raise PlanningError("Dificuldade e domínio precisam estar informados ou marcados como provisórios.", "missing_weight_data")
    difficulty, mastery = int(difficulty), int(mastery)
    if not 1 <= difficulty <= 5 or not 0 <= mastery <= 5:
        raise PlanningError("Dificuldade ou domínio fora do intervalo permitido.", "invalid_weight_data")
    return difficulty * (6 - mastery)


def _objective_blockers(item: dict) -> list[dict]:
    blockers = []
    if item.get("status") != "active":
        blockers.append({"code": "objective_not_active", "message": "O objetivo não está ativo."})
    if not item.get("deadline_date"):
        blockers.append({"code": "deadline_required", "message": "Defina um prazo para distribuir automaticamente."})
    if not item.get("topic_ids"):
        blockers.append({"code": "topic_required", "message": "Adicione pelo menos um tópico utilizável."})
    if item.get("budget_minutes") in (None, ""):
        blockers.append({"code": "budget_required", "message": "Informe o esforço ou aceite uma estimativa provisória."})
    if item.get("difficulty") is None:
        blockers.append({"code": "difficulty_required", "message": "Informe a dificuldade ou aceite um valor provisório."})
    if item.get("mastery") is None:
        blockers.append({"code": "mastery_required", "message": "Informe o domínio ou aceite um valor provisório."})
    if not item.get("canonical_valid", True):
        blockers.append({"code": "canonical_link_invalid", "message": "Revise o vínculo canônico deste estudo."})
    return blockers


def _topic_for(item: dict):
    topics = item.get("topics") or []
    for topic in topics:
        if topic.get("status") in {"in_progress", "not_started", "for_review"} and topic.get("archived_at") in (None, ""):
            return topic.get("id")
    return item.get("topic_ids", [None])[0] if item.get("topic_ids") else None


def _subtract_single(windows: list[list[int]], left: int, right: int) -> list[list[int]]:
    return subtract_intervals(windows, [[left, right]])


def _place_request(windows: list[list[int]], minutes: int, *, start_time=None,
                   preferred=None, split=True, pauses=0) -> tuple[list[tuple[int, int]], list[list[int]], int]:
    """Posiciona foco e devolve blocos, janelas restantes e minutos não alocados."""
    requested = max(0, int(minutes or 0))
    free = [list(value) for value in windows]
    if not requested:
        return [], free, 0
    if start_time not in (None, ""):
        start = _minute(start_time)
        end = start + requested
        if any(left <= start and end <= right for left, right in free):
            return [(start, end)], _subtract_single(free, start, end), 0
        return [], free, requested

    preferred = int(preferred or 0)
    chunks = []
    if preferred > 0:
        remaining = requested
        while remaining:
            chunks.append(min(preferred, remaining))
            remaining -= chunks[-1]
    else:
        chunks = [requested]

    placed: list[tuple[int, int]] = []
    pending = list(chunks)
    while pending:
        amount = pending.pop(0)
        candidate = next(((left, right) for left, right in free if right - left >= amount), None)
        if candidate:
            left, _right = candidate
            placed.append((left, left + amount))
            free = _subtract_single(free, left, left + amount)
        elif split:
            remaining = amount
            while remaining and free:
                left, right = free[0]
                take = min(remaining, right - left)
                if take <= 0:
                    free.pop(0)
                    continue
                placed.append((left, left + take))
                free = _subtract_single(free, left, left + take)
                remaining -= take
            if remaining:
                return placed, free, remaining + sum(pending)
        else:
            return placed, free, amount + sum(pending)

        if (pending or requested > sum(right - left for left, right in placed)) and pauses and free:
            last_end = placed[-1][1]
            for left, right in list(free):
                if left == last_end:
                    free = _subtract_single(free, left, min(right, left + int(pauses)))
                    break
    return placed, free, 0


def _selected(objectives: list[dict], selected_ids) -> list[dict]:
    if not selected_ids:
        return objectives
    wanted = {int(value) for value in selected_ids}
    return [item for item in objectives if int(item.get("study_subject_id") or 0) in wanted]


def plan(snapshot: dict, intents: list[dict] | None, parameters: dict | None, now) -> dict:
    """Gera uma prévia explicável sem escrever ou consultar estado externo."""
    intents, parameters = list(intents or []), dict(parameters or {})
    visual_start = _day(snapshot["horizon_start"])
    visual_end = _day(snapshot["horizon_end"])
    calculation_end = _day(snapshot.get("calculation_end") or visual_end)
    if visual_end < visual_start or calculation_end < visual_end:
        raise PlanningError("O período da prévia é inválido.", "invalid_horizon")

    objectives = _selected([dict(item) for item in snapshot.get("objectives", [])], snapshot.get("selected_study_ids"))
    objective_by_study = {int(item["study_subject_id"]): item for item in objectives}
    availability = {
        current.isoformat(): merge_intervals((snapshot.get("availability") or {}).get(current.isoformat(), []))
        for current in _days(visual_start, calculation_end)
    }
    protected = [dict(item) for item in snapshot.get("preserved_allocations", [])]
    protected_by_day = defaultdict(list)
    for item in protected:
        if item.get("start_time"):
            left = _minute(item["start_time"])
            protected_by_day[item["scheduled_date"]].append([left, left + int(item.get("planned_duration_minutes") or 0)])
    free_windows = {
        day: subtract_intervals(windows, protected_by_day.get(day, []))
        for day, windows in availability.items()
    }

    actual_by_day = {key: max(0, int(value or 0)) for key, value in (snapshot.get("actual_focus_seconds_by_day") or {}).items()}
    daily_limit = max(0, int(snapshot.get("daily_limit_minutes") or 0))
    weekly_limit = max(0, int(snapshot.get("weekly_limit_minutes") or 0))
    pause_minutes = max(0, int(snapshot.get("pause_minutes") or 0))
    daily_capacity = {}
    for current in _days(visual_start, calculation_end):
        key = current.isoformat()
        capacity = interval_minutes(free_windows.get(key, []))
        already_focus = math.ceil(actual_by_day.get(key, 0) / 60)
        already_planned = sum(int(item.get("planned_duration_minutes") or 0) for item in protected if item.get("scheduled_date") == key)
        if daily_limit:
            capacity = min(capacity, max(0, daily_limit - already_focus - already_planned))
        daily_capacity[key] = capacity

    ledgers, blockers = {}, []
    for item in objectives:
        study_id = int(item["study_subject_id"])
        budget = item.get("budget_minutes")
        realized_seconds = max(0, int(item.get("realized_seconds") or 0))
        remaining_seconds = max(0, int(budget or 0) * 60 - realized_seconds) if budget is not None else 0
        remaining = math.ceil(remaining_seconds / 60) if remaining_seconds else 0
        preserved_minutes = sum(
            int(row.get("planned_duration_minutes") or 0)
            for row in protected if int(row.get("study_subject_id") or 0) == study_id
        )
        item_blockers = _objective_blockers(item)
        blockers.extend({"study_subject_id": study_id, "name": item.get("name"), **value} for value in item_blockers)
        ledgers[study_id] = {
            "objective_id": item.get("objective_id"), "study_subject_id": study_id,
            "name": item.get("name"), "budget_minutes": budget,
            "budget_origin": item.get("budget_origin"), "budget_is_provisional": bool(item.get("budget_is_provisional")),
            "realized_seconds": realized_seconds, "remaining_minutes": remaining,
            "preserved_minutes": preserved_minutes,
            "manual_draft_minutes": 0,
            "balance_to_plan_minutes": max(0, remaining - preserved_minutes),
            "excess_reserved_minutes": max(0, preserved_minutes - remaining),
            "eligible_for_automatic": not item_blockers,
            "blockers": item_blockers,
        }

    requests_by_day = defaultdict(list)
    conflicts, alternatives, budget_changes = [], [], []
    manual_intent_types = {"subject_day", "manual_subject_day"}
    for index, intent in enumerate(intents):
        intent_type = intent.get("type")
        if intent_type == "period_total":
            study_id = int(intent.get("study_subject_id") or 0)
            ledger = ledgers.get(study_id)
            if not ledger:
                conflicts.append({"code": "study_not_selected", "intent_index": index, "message": "A matéria da intenção não está no escopo."})
                continue
            total = max(0, int(intent.get("minutes") or 0))
            additional = intent.get("scope") == "additional"
            proposed = (ledger.get("budget_minutes") or 0) + total if additional else total
            budget_changes.append({
                "study_subject_id": study_id, "objective_id": ledger.get("objective_id"),
                "previous_budget_minutes": ledger.get("budget_minutes"), "proposed_budget_minutes": proposed,
                "origin": "user", "reason": "Foco adicional solicitado" if additional else "Orçamento total escolhido no rascunho",
            })
            realized = math.ceil(ledger["realized_seconds"] / 60)
            ledger["budget_minutes"] = proposed
            ledger["remaining_minutes"] = max(0, proposed - realized)
            ledger["balance_to_plan_minutes"] = max(0, ledger["remaining_minutes"] - ledger["preserved_minutes"])
        elif intent_type in manual_intent_types:
            study_id = int(intent.get("study_subject_id") or 0)
            item = objective_by_study.get(study_id)
            ledger = ledgers.get(study_id)
            if not item or not ledger:
                conflicts.append({"code": "study_not_selected", "intent_index": index, "message": "A matéria da intenção não está no escopo."})
                continue
            dates = intent.get("dates") or [intent.get("date")]
            for raw_date in dates:
                if not raw_date:
                    continue
                selected_day = _day(raw_date)
                minutes = max(0, int(intent.get("minutes") or 0))
                if not visual_start <= selected_day <= visual_end:
                    conflicts.append({"code": "manual_outside_preview", "intent_index": index, "date": selected_day.isoformat(), "message": "Uma escolha manual ficou fora da prévia."})
                    continue
                requests_by_day[selected_day.isoformat()].append({
                    "study_subject_id": study_id, "objective_id": item.get("objective_id"),
                    "topic_id": intent.get("topic_id") or _topic_for(item), "minutes": minutes,
                    "source": "manual", "protected": True, "intent_index": index,
                    "start_time": intent.get("start_time"), "allow_split": bool(intent.get("allow_split", True)),
                    "reason": "Carga escolhida manualmente para esta matéria e data.",
                    "deadline_date": item.get("deadline_date"), "weight": 10**9,
                })
                ledger["manual_draft_minutes"] += minutes
                ledger["balance_to_plan_minutes"] = max(0, ledger["balance_to_plan_minutes"] - minutes)
                if ledger["manual_draft_minutes"] + ledger["preserved_minutes"] > ledger["remaining_minutes"]:
                    excess = ledger["manual_draft_minutes"] + ledger["preserved_minutes"] - ledger["remaining_minutes"]
                    conflicts.append({
                        "code": "manual_exceeds_budget", "study_subject_id": study_id,
                        "minutes": excess, "message": "A escolha manual excede o orçamento vigente; confirme uma ampliação ou reduza a carga.",
                    })
                    alternatives.append({"code": "extend_budget", "study_subject_id": study_id, "minutes": excess})

    strategy = parameters.get("strategy") or next((item.get("strategy") for item in intents if item.get("type") == "distribute_remaining"), "balanced")
    use_preferred = bool(parameters.get("use_preferred_duration", False))
    automatic_distribution_requested = any(
        value.get("type") in {"distribute_remaining", "concentrate"} for value in intents
    )
    manual_objective_days = {
        (request["study_subject_id"], day_key)
        for day_key, requests in requests_by_day.items()
        for request in requests if request["source"] == "manual"
    }

    # Intenção de meta total diária: reserva o que foi escolhido manualmente e
    # divide apenas a parcela restante por pesos inteiros conservativos.
    for intent in (value for value in intents if value.get("type") == "daily_total"):
        selected_dates = intent.get("dates") or [value.isoformat() for value in _days(visual_start, visual_end)]
        target = max(0, int(intent.get("minutes") or 0))
        for day_key in selected_dates:
            if not visual_start <= _day(day_key) <= visual_end:
                continue
            manual = sum(value["minutes"] for value in requests_by_day[day_key] if value["source"] == "manual")
            remaining_target = max(0, target - manual)
            candidates = {
                study_id: study_weight(objective_by_study[study_id].get("difficulty"), objective_by_study[study_id].get("mastery"))
                for study_id, ledger in ledgers.items()
                if ledger["balance_to_plan_minutes"] > 0 and ledger["eligible_for_automatic"]
            }
            shares = largest_remainder(min(remaining_target, sum(ledgers[key]["balance_to_plan_minutes"] for key in candidates)), candidates)
            for study_id, minutes in shares.items():
                if not minutes:
                    continue
                item, ledger = objective_by_study[study_id], ledgers[study_id]
                requests_by_day[day_key].append({
                    "study_subject_id": study_id, "objective_id": item.get("objective_id"), "topic_id": _topic_for(item),
                    "minutes": min(minutes, ledger["balance_to_plan_minutes"]), "source": "automatic", "protected": False,
                    "reason": "Parcela da meta diária dividida por dificuldade e domínio.",
                    "deadline_date": item.get("deadline_date"), "weight": candidates[study_id], "allow_split": True,
                })
                ledger["balance_to_plan_minutes"] -= min(minutes, ledger["balance_to_plan_minutes"])

    # Distribuição equilibrada/concentrada do saldo. A cota é calculada no
    # horizonte completo; a janela visual recebe somente sua parcela.
    quota_by_objective_day = {}
    for study_id, ledger in ledgers.items():
        item = objective_by_study[study_id]
        if not automatic_distribution_requested or not ledger["eligible_for_automatic"] or ledger["balance_to_plan_minutes"] <= 0:
            continue
        start = max(visual_start, _day(item.get("start_date") or visual_start))
        deadline = min(calculation_end, _day(item["deadline_date"]))
        allowed = set(int(value) for value in (item.get("allowed_weekdays") or range(7)))
        eligible = [value.isoformat() for value in _days(start, deadline) if value.weekday() in allowed]
        caps = {key: max(0, int(daily_capacity.get(key, 0))) for key in eligible}
        caps = {key: 0 if (study_id, key) in manual_objective_days else value for key, value in caps.items()}
        manual_cap = int(item.get("manual_daily_minutes") or 0)
        if manual_cap:
            caps = {key: min(value, manual_cap) for key, value in caps.items()}
            weights = {key: 1 for key in caps}
        elif strategy == "concentrate":
            weights = {key: max(1, len(caps) - index) for index, key in enumerate(caps)}
        else:
            weights = {key: max(1, value) for key, value in caps.items()}
        quotas = allocate_with_caps(ledger["balance_to_plan_minutes"], caps, weights)
        quota_by_objective_day[study_id] = quotas
        for day_key, minutes in quotas.items():
            if not minutes or not visual_start <= _day(day_key) <= visual_end:
                continue
            requests_by_day[day_key].append({
                "study_subject_id": study_id, "objective_id": item.get("objective_id"), "topic_id": _topic_for(item),
                "minutes": minutes, "source": "automatic", "protected": False,
                "reason": "Saldo distribuído de forma equilibrada até o prazo." if strategy != "concentrate" else "Carga concentrada no período escolhido.",
                "deadline_date": item.get("deadline_date"), "weight": study_weight(item.get("difficulty"), item.get("mastery")),
                "allow_split": True,
            })

    sessions, unscheduled = [], []
    scheduled_by_study = defaultdict(int)
    automatic_scheduled_by_study = defaultdict(int)
    weekly_consumed = defaultdict(int)
    for item in protected:
        selected_day = _day(item["scheduled_date"])
        weekly_consumed[(selected_day - timedelta(days=selected_day.weekday())).isoformat()] += int(item.get("planned_duration_minutes") or 0)
    for day_key, seconds in actual_by_day.items():
        selected_day = _day(day_key)
        weekly_consumed[(selected_day - timedelta(days=selected_day.weekday())).isoformat()] += math.ceil(int(seconds or 0) / 60)
    day_summaries = []
    for current in _days(visual_start, visual_end):
        day_key = current.isoformat()
        windows = [list(value) for value in free_windows.get(day_key, [])]
        focus_cap = max(0, int(daily_capacity.get(day_key, 0)))
        week_key = (current - timedelta(days=current.weekday())).isoformat()
        requests = requests_by_day.get(day_key, [])
        requests.sort(key=lambda value: (
            0 if value["source"] == "manual" else 1,
            value.get("deadline_date") or "9999-12-31", -int(value.get("weight") or 0), value["study_subject_id"],
        ))
        planned_focus = 0
        for request_index, request in enumerate(requests):
            requested = int(request["minutes"])
            weekly_room = max(0, weekly_limit - weekly_consumed[week_key]) if weekly_limit else requested
            allowed = min(requested, max(0, focus_cap - planned_focus), weekly_room)
            if allowed < requested and request["source"] == "manual":
                conflicts.append({
                    "code": "manual_exceeds_day_capacity", "date": day_key,
                    "study_subject_id": request["study_subject_id"], "minutes": requested - allowed,
                    "message": "A escolha manual não cabe no limite ou nas janelas deste dia.",
                })
            preferred = objective_by_study[request["study_subject_id"]].get("preferred_duration_minutes") if use_preferred else None
            placed, windows, left = _place_request(
                windows, allowed, start_time=request.get("start_time"), preferred=preferred,
                split=bool(request.get("allow_split", True)), pauses=pause_minutes,
            )
            placed_minutes = sum(right - left_edge for left_edge, right in placed)
            planned_focus += placed_minutes
            weekly_consumed[week_key] += placed_minutes
            scheduled_by_study[request["study_subject_id"]] += placed_minutes
            if request["source"] == "automatic":
                automatic_scheduled_by_study[request["study_subject_id"]] += placed_minutes
            for block_index, (left_edge, right) in enumerate(placed):
                sessions.append({
                    "study_subject_id": request["study_subject_id"], "objective_id": request.get("objective_id"),
                    "topic_id": request.get("topic_id"), "scheduled_date": day_key,
                    "subject_name": objective_by_study[request["study_subject_id"]].get("name"),
                    "topic_name": next((topic.get("name") for topic in objective_by_study[request["study_subject_id"]].get("topics", []) if topic.get("id") == request.get("topic_id")), None),
                    "start_time": _clock(left_edge), "planned_duration_minutes": right - left_edge,
                    "source": request["source"], "is_locked": 1 if request.get("protected") else 0,
                    "origin": "manual_intent" if request["source"] == "manual" else "engine_suggestion",
                    "reason": request["reason"], "intent_index": request.get("intent_index"),
                    "explanation": {
                        "budget_consumed_minutes": right - left_edge,
                        "availability_window": [_clock(left_edge), _clock(right)],
                        "deadline_date": request.get("deadline_date"),
                        "weight": request.get("weight"), "protected": bool(request.get("protected")),
                    },
                })
            missing = requested - placed_minutes
            if missing:
                unscheduled.append({
                    "study_subject_id": request["study_subject_id"], "date": day_key,
                    "minutes": missing, "source": request["source"],
                    "code": "manual_conflict" if request["source"] == "manual" else "capacity_insufficient",
                })
        day_summaries.append({
            "date": day_key, "focus_minutes": planned_focus,
            "protected_minutes": sum(value["planned_duration_minutes"] for value in protected if value.get("scheduled_date") == day_key),
            "actual_focus_seconds": actual_by_day.get(day_key, 0),
            "available_focus_minutes": daily_capacity.get(day_key, 0),
            "unallocated_minutes": sum(value["minutes"] for value in unscheduled if value["date"] == day_key),
        })

    forecast_after = 0
    for quotas in quota_by_objective_day.values():
        forecast_after += sum(minutes for day_key, minutes in quotas.items() if _day(day_key) > visual_end)
    for study_id, ledger in ledgers.items():
        ledger["scheduled_in_preview_minutes"] = scheduled_by_study[study_id]
        ledger["forecast_after_preview_minutes"] = sum(
            minutes for day_key, minutes in quota_by_objective_day.get(study_id, {}).items() if _day(day_key) > visual_end
        )
        ledger["unallocated_minutes"] = max(
            0,
            # ``balance_to_plan_minutes`` já foi reduzido pelas escolhas
            # manuais. Descontar apenas a parcela automática evita consumir a
            # mesma escolha protegida duas vezes no ledger.
            ledger["balance_to_plan_minutes"] - automatic_scheduled_by_study[study_id] - ledger["forecast_after_preview_minutes"],
        )

    deficits = [{
        "study_subject_id": item["study_subject_id"], "name": item.get("name"),
        "minutes": item["unallocated_minutes"], "code": "deadline_capacity_deficit",
        "message": "O orçamento não cabe até o prazo com as escolhas e capacidades atuais.",
    } for item in ledgers.values() if item.get("eligible_for_automatic") and item["unallocated_minutes"] > 0]

    automatic_blockers = [value for value in blockers if value["study_subject_id"] in objective_by_study]
    hard_conflicts = list(conflicts)
    return {
        "policy_version": POLICY_VERSION,
        "horizon_start": visual_start.isoformat(), "horizon_end": visual_end.isoformat(),
        "calculation_end": calculation_end.isoformat(),
        "sessions": sessions, "days": day_summaries, "objectives": list(ledgers.values()),
        "blockers": automatic_blockers, "conflicts": conflicts, "deficits": deficits, "alternatives": alternatives,
        "budget_changes": budget_changes, "unscheduled": unscheduled,
        "totals": {
            "proposed_focus_minutes": sum(value["planned_duration_minutes"] for value in sessions),
            "manual_minutes": sum(value["planned_duration_minutes"] for value in sessions if value["source"] == "manual"),
            "suggested_minutes": sum(value["planned_duration_minutes"] for value in sessions if value["source"] == "automatic"),
            "forecast_after_preview_minutes": forecast_after,
            "unallocated_minutes": sum(value["unallocated_minutes"] for value in ledgers.values()),
        },
        "applicable": not hard_conflicts,
        "explanation": "Escolhas manuais foram reservadas primeiro; o saldo foi distribuído sem transformar disponibilidade em demanda.",
    }
