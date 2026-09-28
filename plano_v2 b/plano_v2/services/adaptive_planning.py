"""Política versionada de ritmo adaptativo.

O módulo não conhece HTTP nem telas. Ele mantém separados a necessidade
estimada, a capacidade viável e o que já foi alocado. Sessões reais são a
única fonte de minutos realizados; observações alteram apenas orçamento e
recomendação futuros.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
import json
import math

from config import LOCAL_TIMEZONE
from database.repositories import core as repo


POLICY_VERSION = "adaptive-v1"
DEFAULT_DIFFICULTY_REFERENCE = {1: 120, 2: 240, 3: 360, 4: 480, 5: 600}
MASTERY_VALUES = {
    "still_difficult": 0,
    "with_help": 1,
    "independent": 3,
    "can_apply": 4,
}


class AdaptivePlanningError(ValueError):
    def __init__(self, message, code="adaptive_planning_error"):
        super().__init__(message)
        self.code = code


def _now() -> str:
    # Microsegundos evitam que uma observação feita logo após a criação do
    # perfil pareça anterior ao snapshot inicial por empate de timestamp.
    return datetime.now(LOCAL_TIMEZONE).isoformat(timespec="microseconds")


def _today() -> date:
    return datetime.now(LOCAL_TIMEZONE).date()


def _settings(conn) -> dict:
    return {row["key"]: row["value"] for row in repo.many(conn, "SELECT key,value FROM configuracoes")}


def _integer(value, default, *, minimum=0):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, parsed)


def _reference(settings) -> dict[int, int]:
    try:
        raw = json.loads(settings.get("rhythm_difficulty_reference_json") or "{}")
        parsed = {int(key): max(0, int(value)) for key, value in raw.items()}
    except (TypeError, ValueError, json.JSONDecodeError):
        parsed = {}
    return {level: parsed.get(level, minutes) for level, minutes in DEFAULT_DIFFICULTY_REFERENCE.items()}


def _weekdays(value) -> list[int]:
    if value in (None, "", []):
        return list(range(7))
    try:
        raw = json.loads(value) if isinstance(value, str) else value
    except json.JSONDecodeError:
        raw = str(value).split(",")
    try:
        parsed = sorted({int(day) for day in raw})
    except (TypeError, ValueError):
        return list(range(7))
    return [day for day in parsed if 0 <= day <= 6] or list(range(7))


def _dates(start: date, end: date, allowed: list[int]) -> list[date]:
    if end < start:
        return []
    return [start + timedelta(days=offset) for offset in range((end - start).days + 1)
            if (start + timedelta(days=offset)).weekday() in allowed]


def _study_profile(conn, study_id: int) -> dict:
    study = repo.one(conn, """
        SELECT s.*,COALESCE(d.name,s.personal_name) name,
          COALESCE(d.deadline_date,s.target_date,d.end_date) effective_deadline,
          COALESCE(d.required_study_minutes,s.required_study_minutes) explicit_effort_minutes,
          COALESCE(d.allowed_weekdays,s.allowed_weekdays) effective_weekdays,
          COALESCE(d.preferred_block_minutes,s.preferred_block_minutes) effective_block_minutes,
          d.workload_minutes curriculum_workload_minutes
        FROM materias_estudo s
        LEFT JOIN disciplinas_grade d ON d.id=s.curriculum_subject_id
        WHERE s.id=?
    """, (study_id,))
    if not study:
        raise AdaptivePlanningError("Estudo não encontrado.", "study_not_found")
    mastery = study.get("mastery_level")
    if mastery is None:
        observed = repo.one(conn, """
            SELECT AVG(COALESCE(manual_mastery,mastery)) value,COUNT(*) count
            FROM topicos WHERE archived_at IS NULL AND
              (study_subject_id=? OR curriculum_subject_id=?)
        """, (study_id, study.get("curriculum_subject_id")))
        if observed and int(observed.get("count") or 0):
            mastery = round(float(observed["value"]), 1)
    study["effective_mastery"] = mastery
    study["allowed_weekdays_list"] = _weekdays(study.get("effective_weekdays"))
    return study


def _horizon(profile: dict, settings: dict, reference: date) -> tuple[date, date, str]:
    start = max(reference, date.fromisoformat(profile.get("start_date") or reference.isoformat()))
    deadline = profile.get("effective_deadline")
    if deadline:
        return start, max(start, date.fromisoformat(deadline)), "deadline"
    cycle_days = _integer(settings.get("provisional_cycle_days"), 28, minimum=1)
    return start, start + timedelta(days=cycle_days - 1), "recurring_cycle"


def _initial_daily(profile: dict, settings: dict) -> tuple[int, list[str]]:
    difficulty = max(1, min(5, int(profile.get("difficulty") or 3)))
    mastery = profile.get("effective_mastery")
    factors = [f"dificuldade {difficulty}/5"]
    if mastery is None:
        factor = 0.6
        factors.append("domínio ainda desconhecido")
    else:
        factor = max(0.0, min(1.0, (5 - float(mastery)) / 5))
        factors.append(f"domínio {mastery}/5")
    base = int(round(_reference(settings)[difficulty] * factor))
    if base == 0 and profile.get("objective") in {"review", "continuous"}:
        base = _integer(settings.get("rhythm_change_step_minutes"), 15, minimum=1) * 2
        factors.append("manutenção/revisão")
    subject_cap = profile.get("habitual_daily_max_minutes") or settings.get("subject_daily_max_minutes")
    if subject_cap not in (None, ""):
        cap = _integer(subject_cap, base, minimum=1)
        if base > cap:
            factors.append(f"teto habitual da matéria: {cap} min")
        base = min(base, cap)
    return max(0, base), factors


def preview_profile(values: dict, settings: dict | None = None) -> dict:
    """Calcula o primeiro ritmo sem criar matéria, baseline ou snapshot.

    O cadastro usa esta função antes da confirmação. Assim a prévia e o valor
    posteriormente persistido obedecem à mesma política, mas cancelar o fluxo
    não deixa registros parciais no banco.
    """
    settings = settings or {}
    reference = date.fromisoformat(values.get("start_date") or _today().isoformat())
    deadline = values.get("target_date") or values.get("deadline_date")
    if deadline:
        end = date.fromisoformat(deadline)
        horizon_kind = "deadline"
    else:
        cycle_days = _integer(settings.get("provisional_cycle_days"), 28, minimum=1)
        end = reference + timedelta(days=cycle_days - 1)
        horizon_kind = "recurring_cycle"
    if end < reference:
        raise AdaptivePlanningError("O prazo não pode ser anterior à data de início.", "invalid_registration")
    profile = {
        "difficulty": values.get("difficulty") or 3,
        "effective_mastery": values.get("mastery_level"),
        "objective": values.get("objective") or "study",
        "habitual_daily_max_minutes": values.get("habitual_daily_max_minutes"),
    }
    allowed = _weekdays(values.get("allowed_weekdays"))
    eligible = _dates(reference, end, allowed)
    initial_daily, factors = _initial_daily(profile, settings)
    effort = values.get("required_study_minutes")
    if effort not in (None, ""):
        budget = max(0, int(effort))
        daily = math.ceil(budget / max(1, len(eligible)))
        factors.append(f"{budget} min informados em {len(eligible)} dia(s) elegível(is)")
    else:
        daily = initial_daily
        budget = daily * len(eligible)
    preferred = values.get("preferred_block_minutes") or settings.get("default_session_minutes") or 50
    maximum = _integer(settings.get("maximum_session_minutes"), 120, minimum=1)
    minimum = _integer(settings.get("minimum_session_minutes"), 25, minimum=1)
    block = max(minimum, min(maximum, int(preferred), max(minimum, daily or int(preferred))))
    frequency = min(len(allowed), max(0, math.ceil(daily / max(1, block)))) if daily else 0
    return {
        "horizon_start": reference.isoformat(),
        "horizon_end": end.isoformat(),
        "horizon_kind": horizon_kind,
        "estimated_budget_minutes": budget,
        "recommended_daily_minutes": daily,
        "recommended_block_minutes": block,
        "recommended_days_per_week": frequency,
        "eligible_days": len(eligible),
        "factors": factors,
        "is_estimate": effort in (None, ""),
    }


def _recommended_pattern(conn, study_id: int, profile: dict, settings: dict, daily: int) -> tuple[int, int, list[str]]:
    preferred = profile.get("effective_block_minutes") or settings.get("default_session_minutes") or 50
    maximum = _integer(settings.get("maximum_session_minutes"), 120, minimum=1)
    minimum = _integer(settings.get("minimum_session_minutes"), 25, minimum=1)
    block = max(minimum, min(maximum, int(preferred)))
    factors = []
    recent = repo.many(conn, """
        SELECT kind,raw_value,normalized_value FROM study_observations
        WHERE study_subject_id=? AND kind IN ('fatigue','concentration','difficulty')
        ORDER BY observed_at DESC,id DESC LIMIT 3
    """, (study_id,))
    demanding = 0
    for item in recent:
        raw = str(item.get("raw_value") or "").strip().lower()
        numeric = item.get("normalized_value")
        if item["kind"] == "fatigue" and (raw in {"high", "alta", "muito", "exhausted"} or (numeric is not None and float(numeric) >= 4)):
            demanding += 1
        elif item["kind"] == "concentration" and (raw in {"low", "baixa", "difícil"} or (numeric is not None and float(numeric) <= 1)):
            demanding += 1
        elif item["kind"] == "difficulty" and numeric is not None and float(numeric) >= 4:
            demanding += 1
    if demanding:
        # Um bloco longo vira blocos menores; o orçamento diário não aumenta.
        shortened = max(minimum, min(40, block))
        if shortened < block:
            block = shortened
            factors.append("blocos encurtados por fadiga, concentração ou dificuldade recente")
    frequency = min(len(profile["allowed_weekdays_list"]), max(0, math.ceil(daily / max(1, block)))) if daily else 0
    return block, frequency, factors


def _deadline_check_due(conn, profile: dict, reference: date) -> bool:
    deadline = profile.get("effective_deadline")
    if not deadline:
        return False
    deadline_day = date.fromisoformat(deadline)
    if not 0 <= (deadline_day - reference).days <= 5:
        return False
    existing = repo.one(conn, """
        SELECT id FROM study_observations
        WHERE study_subject_id=? AND kind='deadline_check'
          AND observed_at>=? AND observed_at<? LIMIT 1
    """, (profile["id"], (deadline_day - timedelta(days=5)).isoformat(), (deadline_day + timedelta(days=1)).isoformat()))
    return not bool(existing)


def ensure_baseline(conn, study_id: int, reference_date=None) -> dict:
    existing = repo.one(conn, """
        SELECT * FROM study_plan_baselines
        WHERE study_subject_id=? AND active=1 ORDER BY id DESC LIMIT 1
    """, (study_id,))
    if existing:
        return existing
    settings = _settings(conn)
    profile = _study_profile(conn, study_id)
    reference = date.fromisoformat(reference_date) if reference_date else _today()
    start, end, horizon_kind = _horizon(profile, settings, reference)
    eligible = _dates(start, end, profile["allowed_weekdays_list"])
    explicit = profile.get("explicit_effort_minutes")
    if explicit not in (None, ""):
        budget = max(0, int(explicit))
        source = "explicit_effort"
        reason = "Orçamento inicial baseado no esforço total informado; metas antigas não foram somadas."
    else:
        daily, factors = _initial_daily(profile, settings)
        budget = daily * len(eligible)
        # A carga curricular não vira esforço pessoal persistido. Quando
        # existe, funciona apenas como teto de segurança para a estimativa.
        workload_cap = profile.get("curriculum_workload_minutes")
        if workload_cap not in (None, "") and budget > int(workload_cap):
            budget = int(workload_cap)
            factors.append("estimativa limitada pela carga curricular disponível")
        source = "recurring_cycle" if horizon_kind == "recurring_cycle" else "adaptive_estimate"
        reason = "Estimativa inicial configurável: " + ", ".join(factors) + "."
    baseline_id = repo.insert(conn, "study_plan_baselines", {
        "study_subject_id": study_id,
        "policy_version": settings.get("rhythm_policy_version") or POLICY_VERSION,
        "objective": profile.get("objective") or "study",
        "start_date": start.isoformat(),
        "end_date": end.isoformat() if horizon_kind != "recurring_cycle" else None,
        "initial_budget_minutes": budget,
        "current_budget_minutes": budget,
        "source": source,
        "reason": reason,
    })
    return repo.one(conn, "SELECT * FROM study_plan_baselines WHERE id=?", (baseline_id,))


def _studied_minutes(conn, study_id: int, start: str) -> int:
    row = repo.one(conn, """
        SELECT COALESCE(SUM(duration_seconds),0) seconds
        FROM sessoes_estudo WHERE study_subject_id=? AND date>=?
    """, (study_id, start))
    return int((row or {}).get("seconds") or 0) // 60


def _planned_minutes(conn, study_id: int, start: str, end: str) -> int:
    row = repo.one(conn, """
        SELECT COALESCE(SUM(planned_duration_minutes),0) minutes
        FROM sessoes_planejadas
        WHERE study_subject_id=? AND status='planned' AND scheduled_date BETWEEN ? AND ?
    """, (study_id, start, end))
    return int((row or {}).get("minutes") or 0)


def _latest_snapshot(conn, study_id: int) -> dict | None:
    return repo.one(conn, """
        SELECT * FROM recommendation_snapshots
        WHERE study_subject_id=? ORDER BY calculated_at DESC,id DESC LIMIT 1
    """, (study_id,))


def calculate(conn, study_id: int, *, reference_date=None, feasible_minutes=None,
              persist=False, reason=None) -> dict:
    settings = _settings(conn)
    profile = _study_profile(conn, study_id)
    baseline = ensure_baseline(conn, study_id, reference_date)
    reference = date.fromisoformat(reference_date) if reference_date else _today()
    start, end, horizon_kind = _horizon(profile, settings, reference)
    eligible = _dates(start, end, profile["allowed_weekdays_list"])
    completed = _studied_minutes(conn, study_id, baseline["start_date"])
    need = max(0, int(baseline["current_budget_minutes"]) - completed)
    initial_daily, factors = _initial_daily(profile, settings)
    if profile.get("explicit_effort_minutes") not in (None, ""):
        recommended = math.ceil(need / max(1, len(eligible)))
        factors.append(f"{need} min restantes em {len(eligible)} dia(s) elegível(is)")
    else:
        recommended = min(initial_daily, math.ceil(need / max(1, len(eligible))) if need else 0)
    if profile.get("rhythm_mode") == "manual" and profile.get("manual_daily_minutes"):
        applied = int(profile["manual_daily_minutes"])
        factors.append("ritmo manual aplicado")
    else:
        applied = int(profile.get("daily_goal_minutes") or recommended)
    planned = _planned_minutes(conn, study_id, start.isoformat(), end.isoformat())
    feasible = need if feasible_minutes is None else max(0, int(feasible_minutes))
    allocated = min(need, planned)
    deficit = max(0, need - feasible)
    observation_count = repo.one(conn, "SELECT COUNT(*) count FROM study_observations WHERE study_subject_id=?", (study_id,))["count"]
    confidence = "initial" if not observation_count else "low" if observation_count < 3 else "medium" if observation_count < 6 else "high"
    previous = _latest_snapshot(conn, study_id)
    block, frequency, pattern_factors = _recommended_pattern(conn, study_id, profile, settings, recommended)
    factors.extend(pattern_factors)
    applied_block = int(profile.get("effective_block_minutes") or block)
    explanation = reason or (
        "Estimativa inicial; ajustando ao seu ritmo."
        if confidence == "initial" else
        "Recomendação recalculada com o histórico de observações disponível."
    )
    payload = {
        "study_subject_id": study_id,
        "subject_name": profile["name"],
        "baseline_id": baseline["id"],
        "policy_version": baseline["policy_version"],
        "horizon_start": start.isoformat(),
        "horizon_end": end.isoformat(),
        "horizon_kind": horizon_kind,
        "estimated_need_minutes": need,
        "feasible_minutes": feasible,
        "allocated_minutes": allocated,
        "deficit_minutes": deficit,
        "recommended_daily_minutes": max(0, recommended),
        "applied_daily_minutes": max(0, applied),
        "recommended_block_minutes": block,
        "applied_block_minutes": applied_block,
        "recommended_days_per_week": frequency,
        "eligible_days": len(eligible),
        "deadline_check_due": _deadline_check_due(conn, profile, reference),
        "confidence": confidence,
        "reason": explanation,
        "factors": factors,
        "previous": previous,
        "is_estimate": True,
    }
    if persist:
        snapshot_id = repo.insert(conn, "recommendation_snapshots", {
            "study_subject_id": study_id,
            "baseline_id": baseline["id"],
            "previous_snapshot_id": previous["id"] if previous else None,
            "policy_version": baseline["policy_version"],
            "calculated_at": _now(),
            "horizon_start": start.isoformat(),
            "horizon_end": end.isoformat(),
            "estimated_need_minutes": need,
            "feasible_minutes": feasible,
            "allocated_minutes": allocated,
            "deficit_minutes": deficit,
            "recommended_daily_minutes": max(0, recommended),
            "applied_daily_minutes": max(0, applied),
            "recommended_block_minutes": block,
            "applied_block_minutes": applied_block,
            "recommended_days_per_week": frequency,
            "confidence": confidence,
            "reason": explanation,
            "factors_json": json.dumps({"factors": factors, "eligible_days": len(eligible)}, ensure_ascii=False),
        })
        payload["id"] = snapshot_id
        payload["calculated_at"] = _now()
    elif previous:
        payload["id"] = previous["id"]
        payload["calculated_at"] = previous["calculated_at"]
    return payload


def history(conn, study_id: int) -> list[dict]:
    rows = repo.many(conn, """
        SELECT * FROM recommendation_snapshots
        WHERE study_subject_id=? ORDER BY calculated_at,id
    """, (study_id,))
    for row in rows:
        try:
            row["factors"] = json.loads(row.pop("factors_json") or "{}")
        except json.JSONDecodeError:
            row["factors"] = {}
    return rows


def _normalized(kind: str, raw_value, normalized_value=None):
    if normalized_value not in (None, ""):
        try:
            value = float(normalized_value)
        except (TypeError, ValueError) as error:
            raise AdaptivePlanningError("Valor normalizado inválido.", "invalid_observation") from error
    elif kind in {"mastery", "difficulty", "fatigue", "concentration"}:
        labels = {
            **MASTERY_VALUES,
            "low": 0, "baixa": 0, "medium": 3, "media": 3, "média": 3,
            "high": 5, "alta": 5, "exhausted": 5,
        }
        if str(raw_value).strip().lower() in labels:
            value = float(labels[str(raw_value).strip().lower()])
        else:
            try:
                value = float(raw_value)
            except (TypeError, ValueError) as error:
                raise AdaptivePlanningError("Avaliação de domínio inválida.", "invalid_observation") from error
        if not 0 <= value <= 5:
            raise AdaptivePlanningError("A avaliação deve ficar entre 0 e 5.", "invalid_observation")
    else:
        value = None
    return value


def _trend_adjustment(conn, study_id: int, baseline: dict, settings: dict) -> tuple[int, str] | None:
    latest = _latest_snapshot(conn, study_id)
    clauses = ["study_subject_id=?", "kind='mastery'", "normalized_value IS NOT NULL"]
    params = [study_id]
    if latest:
        clauses.append("observed_at>?")
        params.append(latest["calculated_at"])
    required = _integer(settings.get("rhythm_trend_observations"), 3, minimum=2)
    rows = repo.many(conn, "SELECT normalized_value FROM study_observations WHERE " + " AND ".join(clauses) + " ORDER BY observed_at DESC,id DESC LIMIT ?", (*params, required))
    if len(rows) < required:
        return None
    values = [float(row["normalized_value"]) for row in rows]
    step = _integer(settings.get("rhythm_change_step_minutes"), 15, minimum=1)
    if all(value >= 3 for value in values):
        return -step, f"{required} observações recentes indicam autonomia consistente"
    if all(value <= 1 for value in values):
        return step, f"{required} observações recentes indicam dificuldade persistente"
    return None


def record_observation(conn, study_id: int, values: dict) -> dict:
    profile = _study_profile(conn, study_id)
    baseline = ensure_baseline(conn, study_id)
    kind = str(values.get("kind") or "mastery")
    if kind not in {"mastery", "difficulty", "fatigue", "concentration", "new_content", "deadline_check"}:
        raise AdaptivePlanningError("Tipo de observação inválido.", "invalid_observation")
    source = str(values.get("source") or "self_report")
    if source not in {"self_report", "objective_evaluation", "system_check"}:
        raise AdaptivePlanningError("Origem da observação inválida.", "invalid_observation")
    key = values.get("idempotency_key")
    if key:
        existing = repo.one(conn, "SELECT * FROM study_observations WHERE idempotency_key=?", (str(key),))
        if existing:
            return {"observation": existing, "recommendation": calculate(conn, study_id), "idempotent": True}
    raw = values.get("raw_value", values.get("value"))
    normalized = _normalized(kind, raw, values.get("normalized_value"))
    observed_at = values.get("observed_at") or _now()
    if kind == "deadline_check":
        deadline = profile.get("effective_deadline")
        existing = repo.one(conn, """
            SELECT * FROM study_observations
            WHERE study_subject_id=? AND kind='deadline_check' AND observed_at>=?
            ORDER BY observed_at DESC,id DESC LIMIT 1
        """, (study_id, (date.fromisoformat(deadline) - timedelta(days=5)).isoformat() if deadline else baseline["start_date"]))
        if existing:
            return {"observation": existing, "recommendation": calculate(conn, study_id), "idempotent": True, "deadline_check_already_recorded": True}
    observation_id = repo.insert(conn, "study_observations", {
        "study_subject_id": study_id,
        "study_session_id": values.get("study_session_id"),
        "observed_at": observed_at,
        "kind": kind,
        "source": source,
        "raw_value": None if raw is None else str(raw),
        "normalized_value": normalized,
        "notes": values.get("notes"),
        "idempotency_key": str(key) if key else None,
    })
    if kind == "mastery" and normalized is not None:
        conn.execute(
            "UPDATE materias_estudo SET mastery_level=?,mastery_is_provisional=0,profile_version=profile_version+1,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
            (int(round(normalized)), study_id),
        )
    elif kind == "difficulty" and normalized is not None:
        difficulty = max(1, min(5, int(round(normalized))))
        conn.execute(
            "UPDATE materias_estudo SET difficulty=?,difficulty_is_provisional=0,profile_version=profile_version+1,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
            (difficulty, study_id),
        )
    settings = _settings(conn)
    adjustment = _trend_adjustment(conn, study_id, baseline, settings)
    persist = False
    reason = None
    if kind == "new_content":
        adjustment = (
            _integer(settings.get("rhythm_change_step_minutes"), 15, minimum=1),
            "Conteúdo novo informado; o orçamento futuro foi ampliado sem criar horas estudadas",
        )
    if kind == "deadline_check":
        answer = str(raw or "").strip().lower()
        if answer in {"needs_more", "need_more", "preciso_reforcar", "reforçar"}:
            adjustment = (_integer(settings.get("rhythm_change_step_minutes"), 15, minimum=1), "Checagem do prazo indicou necessidade de reforço")
        elif answer in {"difficult", "still_difficult", "dificil", "difícil"}:
            adjustment = (_integer(settings.get("rhythm_change_step_minutes"), 15, minimum=1) * 2, "Checagem do prazo indicou dificuldade persistente")
        else:
            # "Preparado" apenas registra a evidência; não cria reforço.
            adjustment = None
            reason = "Checagem do prazo registrada sem reforço adicional."
    if adjustment:
        daily_delta, reason = adjustment
        profile = _study_profile(conn, study_id)
        start, end, _ = _horizon(profile, settings, _today())
        remaining_days = len(_dates(start, end, profile["allowed_weekdays_list"]))
        budget_delta = daily_delta * remaining_days
        updated_budget = max(0, int(baseline["current_budget_minutes"]) + budget_delta)
        conn.execute(
            "UPDATE study_plan_baselines SET current_budget_minutes=?,reason=?,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
            (updated_budget, reason, baseline["id"]),
        )
        persist = True
    if kind in {"fatigue", "concentration", "difficulty", "deadline_check"}:
        persist = True
    recommendation = calculate(conn, study_id, persist=persist, reason=reason)
    auto_applied = False
    if persist and settings.get("adaptation_mode") == "automatic" and recommendation.get("id"):
        accept(conn, study_id, recommendation["id"], {
            "action": "auto_applied",
            "daily_minutes": recommendation["recommended_daily_minutes"],
            "block_minutes": recommendation["recommended_block_minutes"],
            "reason": reason or "Adaptação automática dentro dos limites configurados.",
            "idempotency_key": f"auto-observation-{observation_id}",
        })
        auto_applied = True
    return {
        "observation": repo.one(conn, "SELECT * FROM study_observations WHERE id=?", (observation_id,)),
        "recommendation": recommendation,
        "adjustment_applied": bool(adjustment),
        "auto_applied": auto_applied,
        "idempotent": False,
    }


def accept(conn, study_id: int, snapshot_id: int, values: dict) -> dict:
    snapshot = repo.one(conn, "SELECT * FROM recommendation_snapshots WHERE id=? AND study_subject_id=?", (snapshot_id, study_id))
    if not snapshot:
        raise AdaptivePlanningError("Recomendação não encontrada.", "recommendation_not_found")
    key = values.get("idempotency_key")
    if key:
        existing = repo.one(conn, "SELECT * FROM recommendation_decisions WHERE idempotency_key=?", (str(key),))
        if existing:
            return {"decision": existing, "study": _study_profile(conn, study_id), "idempotent": True}
    action = values.get("action") or "accepted"
    if action not in {"accepted", "auto_applied", "rejected", "undone"}:
        raise AdaptivePlanningError("Ação da recomendação inválida.", "invalid_recommendation_action")
    study = _study_profile(conn, study_id)
    previous = study.get("daily_goal_minutes")
    previous_block = study.get("effective_block_minutes")
    applied = values.get("daily_minutes", snapshot["recommended_daily_minutes"])
    applied = max(0, int(applied))
    applied_block = values.get("block_minutes", snapshot.get("recommended_block_minutes") or previous_block or 50)
    applied_block = max(1, int(applied_block))
    if action in {"accepted", "auto_applied"}:
        conn.execute(
            "UPDATE materias_estudo SET daily_goal_minutes=?,preferred_block_minutes=?,daily_goal_mode='deadline_paced',rhythm_mode='suggested',profile_version=profile_version+1,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
            (applied or None, applied_block, study_id),
        )
    decision_id = repo.insert(conn, "recommendation_decisions", {
        "recommendation_snapshot_id": snapshot_id,
        "action": action,
        "previous_daily_minutes": previous,
        "applied_daily_minutes": applied if action in {"accepted", "auto_applied"} else None,
        "previous_block_minutes": previous_block,
        "applied_block_minutes": applied_block if action in {"accepted", "auto_applied"} else None,
        "reason": values.get("reason"),
        "idempotency_key": str(key) if key else None,
    })
    return {
        "decision": repo.one(conn, "SELECT * FROM recommendation_decisions WHERE id=?", (decision_id,)),
        "study": _study_profile(conn, study_id),
        "idempotent": False,
    }
