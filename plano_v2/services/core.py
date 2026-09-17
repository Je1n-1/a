"""Regras de negócio. Nenhuma rota contém SQL ou decisões do produto."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
import json
from pathlib import Path
import re
import sqlite3
import unicodedata
from config import LOCAL_TIMEZONE
from database.repositories import core as repo
from services import canonical_links
from services import grade_import
from services import smart_planning


class DomainError(ValueError):
    def __init__(self, message, status=400, code="domain_error", blockers=None, details=None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.blockers = blockers
        self.details = details


def _canonical(operation):
    """Traduz erros do vínculo canônico para o contrato uniforme da API."""
    try:
        return operation()
    except canonical_links.CanonicalLinkError as error:
        raise DomainError(str(error), error.status, error.code, details=error.details) from error


def _local_now(): return datetime.now(LOCAL_TIMEZONE)
def _today(): return _local_now().date().isoformat()
def _now(): return _local_now().isoformat(timespec="seconds")
def _date(value, label="Data"):
    try: return date.fromisoformat(str(value))
    except ValueError as error: raise DomainError(f"{label} deve usar AAAA-MM-DD.") from error


def _optional_date(value):
    """Lê uma data legada sem deixar uma prévia inteira falhar.

    Os formulários atuais validam datas, mas importações antigas podem conter
    texto inválido. O gerador precisa explicar esse caso em vez de criar um
    bloco em uma data incerta ou responder com erro interno.
    """
    if value in (None, ""):
        return None, False
    try:
        return _date(value), False
    except DomainError:
        return None, True
def _week_bounds(reference=None):
    current = _date(reference) if reference else _local_now().date()
    start = current - timedelta(days=current.weekday())
    return start, start + timedelta(days=6)
def _need(value, label):
    if value is None or not str(value).strip(): raise DomainError(f"{label} é obrigatório.")
    return value
def _get(conn, table, ident):
    value = repo.one(conn, f"SELECT * FROM {table} WHERE id=?", (ident,))
    if not value: raise DomainError("Registro não encontrado.", 404)
    return value
def _fields(values, allowed):
    """Seleciona campos explicitamente enviados, inclusive ``null``.

    O cliente usa ``null`` para limpar datas, esforço, prazo e notas. Omitir
    um campo continua significando “não alterar”; enviar ``null`` agora tem o
    significado útil e previsível de removê-lo.
    """
    return {key: value for key, value in values.items() if key in allowed}


def _optional_minutes(value, label):
    if value in (None, ""):
        return None
    try:
        minutes = int(value)
    except (TypeError, ValueError) as error:
        raise DomainError(f"{label} deve ser informado em minutos como um número inteiro.") from error
    if minutes <= 0:
        raise DomainError(f"{label} deve ser maior que zero.")
    return minutes


def _optional_block_minutes(value):
    minutes = _optional_minutes(value, "Duração preferida do bloco")
    if minutes is not None and not 15 <= minutes <= 240:
        raise DomainError("Duração preferida do bloco deve ficar entre 15 e 240 minutos.")
    return minutes


def _optional_number(value, label):
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise DomainError(f"{label} deve ser um número.") from error
    if number < 0:
        raise DomainError(f"{label} não pode ser negativo.")
    return number


def _weekdays(value):
    """Normaliza os dias permitidos em uma lista ordenada de 0 (seg) a 6."""
    if value in (None, "", []):
        return []
    raw = value
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            raw = parsed if isinstance(parsed, list) else raw.split(",")
        except json.JSONDecodeError:
            raw = raw.split(",")
    if not isinstance(raw, (tuple, list, set)):
        raise DomainError("Dias permitidos devem ser uma lista de 0 a 6.")
    try:
        result = sorted({int(item) for item in raw if str(item).strip() != ""})
    except (TypeError, ValueError) as error:
        raise DomainError("Dias permitidos devem usar números de 0 a 6.") from error
    if any(day < 0 or day > 6 for day in result):
        raise DomainError("Dias permitidos devem ficar entre 0 (segunda) e 6 (domingo).")
    return result


def _weekdays_json(value):
    return json.dumps(_weekdays(value), separators=(",", ":"))


def _stored_weekdays(value):
    return _weekdays(value)


def _event(conn, curriculum_id, event_type, title, details=None):
    """Registra eventos objetivos para a linha do tempo da disciplina."""
    return repo.insert(conn, "curriculum_timeline_events", {
        "curriculum_subject_id": curriculum_id,
        "event_type": event_type,
        "title": title,
        "details": details,
    })


def _active_formation(conn, ident):
    formation = _get(conn, "formacoes", ident)
    if formation["archived_at"]:
        raise DomainError("Restaure a formação antes de fazer alterações.", 409, "formation_archived")
    return formation


FORMATION = {"name", "institution", "modality", "start_date", "expected_end_date", "status", "focus_priority"}
CURRICULUM = {
    "name", "code", "period", "workload_minutes", "academic_status", "sort_order",
    "start_date", "end_date", "notes", "review_status", "review_priority", "review_notes",
    "item_type", "deadline_date", "required_study_minutes", "priority_base",
    "preferred_block_minutes", "allowed_weekdays", "minimum_grade", "planning_enabled",
    "effort_is_provisional", "deadline_is_provisional",
}
STUDY = {
    "favorite", "priority", "difficulty", "weekly_goal_minutes", "start_date", "target_date",
    "status", "academic_period", "result", "final_score", "required_study_minutes",
    "minimum_weekly_minutes", "preferred_block_minutes", "allowed_weekdays",
}

ACADEMIC_STATUSES = tuple(grade_import.ACADEMIC_STATUSES)
REVIEW_STATUSES = ("none", "queued", "in_progress", "reviewed")
ITEM_TYPES = ("subject", "section")
STUDY_ARCHIVE_REASONS = ("manual", "formation", "curriculum", "removed_current")
TOPIC_STATUSES = ("not_started", "in_progress", "completed", "paused", "for_review")


def formations(conn, visibility="active"):
    if visibility not in {"active", "archived", "all"}:
        raise DomainError("Filtro de formações inválido.")
    where = {"active": "WHERE f.archived_at IS NULL", "archived": "WHERE f.archived_at IS NOT NULL", "all": ""}[visibility]
    # Os agregados são calculados por formação antes do SELECT principal para não
    # multiplicar disciplinas por estudos ativos no JOIN.
    sql = """
        WITH curriculum_stats AS (
            SELECT d.formation_id,
                COUNT(*) FILTER (WHERE d.archived_at IS NULL) AS curriculum_count,
                COUNT(*) FILTER (WHERE d.archived_at IS NULL AND d.item_type='subject') AS valid_subjects,
                COUNT(*) FILTER (WHERE d.archived_at IS NULL AND d.item_type='subject' AND d.academic_status='completed') AS completed_subjects,
                COUNT(*) FILTER (WHERE d.archived_at IS NULL AND d.item_type='subject' AND d.academic_status='exempted') AS exempted_subjects,
                COUNT(*) FILTER (WHERE d.archived_at IS NULL AND d.item_type='subject' AND d.academic_status='in_progress') AS in_progress_subjects,
                COUNT(*) FILTER (WHERE d.archived_at IS NULL AND d.item_type='subject' AND d.academic_status NOT IN ('completed','exempted')) AS pending_subjects,
                COUNT(*) FILTER (WHERE d.archived_at IS NULL AND d.item_type='subject' AND d.review_status IN ('queued','in_progress')) AS review_subjects,
                COUNT(*) FILTER (WHERE d.archived_at IS NULL AND d.item_type='subject' AND d.academic_status='failed') AS failed_subjects,
                COUNT(*) FILTER (WHERE d.archived_at IS NULL AND d.item_type='subject' AND d.academic_status='locked') AS locked_subjects,
                COUNT(*) FILTER (WHERE d.archived_at IS NULL AND d.item_type='subject' AND d.academic_status='available') AS available_subjects,
                COUNT(*) FILTER (WHERE d.archived_at IS NULL AND d.item_type='subject' AND d.academic_status='not_available') AS not_available_subjects
            FROM disciplinas_grade d GROUP BY d.formation_id
        ), study_stats AS (
            SELECT COALESCE(s.related_formation_id,d.formation_id) formation_id,
                COUNT(*) FILTER (WHERE s.status IN ('active','paused') AND s.archived_at IS NULL) AS active_studies
            FROM materias_estudo s LEFT JOIN disciplinas_grade d ON d.id=s.curriculum_subject_id
            GROUP BY COALESCE(s.related_formation_id,d.formation_id)
        )
        SELECT f.*, COALESCE(c.curriculum_count,0) curriculum_count,
            COALESCE(c.valid_subjects,0) valid_subjects,
            COALESCE(c.completed_subjects,0) completed_subjects,
            COALESCE(c.exempted_subjects,0) exempted_subjects,
            COALESCE(c.in_progress_subjects,0) in_progress_subjects,
            COALESCE(c.pending_subjects,0) pending_subjects,
            COALESCE(c.review_subjects,0) review_subjects,
            COALESCE(c.failed_subjects,0) failed_subjects,
            COALESCE(c.locked_subjects,0) locked_subjects,
            COALESCE(c.available_subjects,0) available_subjects,
            COALESCE(c.not_available_subjects,0) not_available_subjects,
            COALESCE(st.active_studies,0) active_studies
        FROM formacoes f
        LEFT JOIN curriculum_stats c ON c.formation_id=f.id
        LEFT JOIN study_stats st ON st.formation_id=f.id
    """ + where + " ORDER BY f.created_at DESC"
    values = repo.many(conn, sql)
    for formation in values:
        total = int(formation["valid_subjects"] or 0)
        satisfied = int(formation["completed_subjects"] or 0) + int(formation["exempted_subjects"] or 0)
        formation["academic_progress_percent"] = round(satisfied * 100 / total, 1) if total else 0
        formation["academic_progress"] = {
            "total": total, "completed": int(formation["completed_subjects"] or 0),
            "exempted": int(formation["exempted_subjects"] or 0),
            "in_progress": int(formation["in_progress_subjects"] or 0),
            "pending": int(formation["pending_subjects"] or 0),
            "review": int(formation["review_subjects"] or 0),
            "percent": formation["academic_progress_percent"],
        }
    return values


def _formation_data(values, current=None):
    data = _fields(values, FORMATION)
    if current is None and data.get("status") == "archived":
        raise DomainError("Use a ação Arquivar depois de criar a formação.", 400, "use_archive_action")
    for key in ("institution", "modality", "start_date", "expected_end_date"):
        if data.get(key) == "": data[key] = None
    candidate = {**(current or {}), **data}
    if "name" in candidate: data["name"] = _need(candidate["name"], "Nome")
    else: data["name"] = _need(data.get("name"), "Nome")
    if candidate.get("focus_priority") is not None:
        try: priority = int(candidate["focus_priority"])
        except (TypeError, ValueError) as error: raise DomainError("Prioridade de foco deve ser um número de 1 a 5.") from error
        if not 1 <= priority <= 5: raise DomainError("Prioridade de foco deve estar entre 1 e 5.")
        data["focus_priority"] = priority
    if candidate.get("status", "active") not in {"active", "paused", "completed", "cancelled", "archived"}:
        raise DomainError("Status da formação inválido.")
    start = candidate.get("start_date")
    end = candidate.get("expected_end_date")
    if start: _date(start, "Data de início")
    if end: _date(end, "Previsão de conclusão")
    if start and end and start > end: raise DomainError("A previsão de conclusão não pode ser anterior ao início.")
    return data


def create_formation(conn, values):
    data = _formation_data(values)
    data.setdefault("focus_priority", 3); data.setdefault("status", "active")
    return _get(conn, "formacoes", repo.insert(conn, "formacoes", data))


def change_formation(conn, ident, values):
    current = _active_formation(conn, ident)
    if values.get("status") == "archived":
        raise DomainError("Use a ação Arquivar para arquivar uma formação.", 400, "use_archive_action")
    data = _formation_data(values, current)
    repo.update(conn, "formacoes", ident, data); return _get(conn, "formacoes", ident)


def _formation_study_ids(conn, formation_id, active_only=False):
    status = " AND s.status IN ('active','paused')" if active_only else ""
    rows = repo.many(conn, """
        SELECT s.id FROM materias_estudo s
        LEFT JOIN disciplinas_grade d ON d.id=s.curriculum_subject_id
        WHERE (s.related_formation_id=? OR d.formation_id=?)
    """ + status, (formation_id, formation_id))
    return [row["id"] for row in rows]


def _cancel_future_planned(conn, study_ids):
    if not study_ids:
        return {"count": 0, "ids": []}
    markers = ",".join("?" for _ in study_ids)
    rows = conn.execute(
        "UPDATE sessoes_planejadas SET status='cancelled',updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') "
        f"WHERE study_subject_id IN ({markers}) AND status='planned' AND scheduled_date>=? RETURNING id",
        (*study_ids, _today()),
    ).fetchall()
    return {"count": len(rows), "ids": [row["id"] for row in rows]}


def _future_planned_by_source(conn, study_ids):
    """Resume blocos futuros sem apagar a intenção explícita do usuário.

    Arquivar um estudo ou disciplina tira o item do planejamento automático,
    mas não deve fazer um bloco manual desaparecer silenciosamente. O retorno
    permite que a interface explique a consequência antes e depois da ação.
    """
    if not study_ids:
        return {"automatic": [], "manual": []}
    markers = ",".join("?" for _ in study_ids)
    rows = repo.many(conn, f"""
        SELECT id,study_subject_id,topic_id,scheduled_date,start_time,
               planned_duration_minutes,source
        FROM sessoes_planejadas
        WHERE study_subject_id IN ({markers}) AND status='planned'
          AND scheduled_date>=?
        ORDER BY scheduled_date,start_time,id
    """, (*study_ids, _today()))
    return {
        "automatic": [row for row in rows if row.get("source") == "automatic"],
        "manual": [row for row in rows if row.get("source") != "automatic"],
    }


def _cancel_future_automatic_planned(conn, study_ids, reason="cancelado: item arquivado"):
    """Cancela somente blocos criados pelo motor e preserva os manuais."""
    preview = _future_planned_by_source(conn, study_ids)
    automatic = preview["automatic"]
    if automatic:
        ids = [row["id"] for row in automatic]
        markers = ",".join("?" for _ in ids)
        conn.execute(
            f"UPDATE sessoes_planejadas SET status='cancelled',selection_reason=?,"
            "updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') "
            f"WHERE id IN ({markers})",
            (reason, *ids),
        )
    return {
        "count": len(automatic), "ids": [row["id"] for row in automatic],
        "manual_preserved": len(preview["manual"]),
        "manual_ids": [row["id"] for row in preview["manual"]],
    }


def _archive_study_row(conn, ident, reason="manual", formation_id=None):
    study = _get(conn, "materias_estudo", ident)
    if study["status"] == "archived" or study["archived_at"]:
        return study
    if reason not in STUDY_ARCHIVE_REASONS:
        raise DomainError("Motivo de arquivamento inválido.")
    previous = study["status"] if study["status"] in {"active", "paused", "completed"} else "active"
    repo.update(conn, "materias_estudo", ident, {
        "status": "archived", "archived_at": _now(), "archive_reason": reason,
        "archived_by_formation_id": formation_id, "status_before_archive": previous,
    })
    return _get(conn, "materias_estudo", ident)


def _restore_study_row(conn, ident):
    study = _get(conn, "materias_estudo", ident)
    formation_id = study["related_formation_id"]
    if study["curriculum_subject_id"]:
        curriculum_item = _get(conn, "disciplinas_grade", study["curriculum_subject_id"])
        formation_id = curriculum_item["formation_id"]
        if curriculum_item["archived_at"]:
            raise DomainError("Restaure a disciplina antes de restaurar este estudo.", 409, "curriculum_archived")
    if formation_id:
        _active_formation(conn, formation_id)
    restored_status = study["status_before_archive"] or "active"
    repo.update(conn, "materias_estudo", ident, {
        "status": restored_status, "archived_at": None, "archive_reason": None,
        "archived_by_formation_id": None, "status_before_archive": None,
    })
    return _get(conn, "materias_estudo", ident)


def archive_formation(conn, ident, study_policy="archive_studies"):
    formation = _get(conn, "formacoes", ident)
    if formation["archived_at"]:
        raise DomainError("Esta formação já está arquivada.", 409, "formation_already_archived")
    if study_policy not in {"archive_studies", "hide_studies"}:
        raise DomainError("Escolha inválida para os estudos vinculados.", 400, "invalid_archive_policy")
    active_ids = _formation_study_ids(conn, ident, active_only=True)
    archived_ids = []
    preserved_shared_ids = []
    cancelled = {"count": 0, "ids": [], "manual_preserved": 0, "manual_ids": []}
    if study_policy == "archive_studies":
        for study_id in active_ids:
            # O estudo é canônico, mas a formação não é: se outra ocorrência
            # vinculada continua academicamente utilizável, arquivar esta
            # formação não pode interromper foco, sessões ou agenda dela.
            if _canonical(lambda: canonical_links.has_active_shared_subject_elsewhere(conn, study_id, ident)):
                preserved_shared_ids.append(study_id)
                continue
            _archive_study_row(conn, study_id, "formation", ident)
            archived_ids.append(study_id)
        # Arquivar uma formação é uma decisão explícita de suspender a agenda
        # dela. Os registros não são apagados: ficam cancelados no histórico.
        # Já os estudos compartilhados foram removidos de ``archived_ids`` e,
        # portanto, nenhum bloco deles é afetado.
        cancelled = _cancel_future_planned(conn, archived_ids)
    repo.update(conn, "formacoes", ident, {"status": "archived", "archived_at": _now()})
    saved = _get(conn, "formacoes", ident)
    return {
        **saved, "formation": saved, "study_policy": study_policy,
        "archived_studies": {"count": len(archived_ids), "ids": archived_ids},
        "preserved_shared_studies": {
            "count": len(preserved_shared_ids), "ids": preserved_shared_ids,
            "reason": "continuam vinculados a uma formação ativa",
        },
        "cancelled_future_blocks": cancelled,
    }


def restore_formation(conn, ident, restore_studies=False):
    formation = _get(conn, "formacoes", ident)
    if not formation["archived_at"]:
        raise DomainError("Esta formação já está ativa.", 409, "formation_already_active")
    repo.update(conn, "formacoes", ident, {"status": "active", "archived_at": None})
    restored_ids = []
    if _confirmed(restore_studies):
        for study_id in _formation_study_ids(conn, ident):
            study = _get(conn, "materias_estudo", study_id)
            if study["status"] == "archived" and study["archive_reason"] == "formation" and study["archived_by_formation_id"] == ident:
                _restore_study_row(conn, study_id)
                restored_ids.append(study_id)
    saved = _get(conn, "formacoes", ident)
    return {**saved, "formation": saved, "restored_studies": {"count": len(restored_ids), "ids": restored_ids}}


def archive_study(conn, ident, restore=False):
    if restore:
        return _restore_study_row(conn, ident)
    saved = _archive_study_row(conn, ident, "manual")
    # A confirmação de arquivamento é a escolha explícita de não manter
    # blocos automáticos deste estudo. Blocos manuais seguem preservados para
    # não reescrever a agenda do usuário ao restaurá-lo.
    return {
        **saved,
        "cancelled_future_blocks": _cancel_future_automatic_planned(conn, [ident]),
    }


def archive_curriculum(conn, ident, restore=False):
    current = _get(conn, "disciplinas_grade", ident)
    if restore:
        _active_formation(conn, current["formation_id"])
        repo.update(conn, "disciplinas_grade", ident, {"archived_at": None})
    else:
        _active_formation(conn, current["formation_id"])
        repo.update(conn, "disciplinas_grade", ident, {"archived_at": _now()})
    saved = _get(conn, "disciplinas_grade", ident)
    if restore:
        return saved
    studies_rows = repo.many(conn, "SELECT id FROM materias_estudo WHERE curriculum_subject_id=?", (ident,))
    cancellable_ids, preserved_shared_ids = [], []
    for row in studies_rows:
        if _canonical(lambda: canonical_links.has_active_shared_subject_elsewhere(conn, row["id"], current["formation_id"])):
            preserved_shared_ids.append(row["id"])
        else:
            cancellable_ids.append(row["id"])
    return {
        **saved,
        "cancelled_future_blocks": _cancel_future_automatic_planned(
            conn, cancellable_ids, "cancelado: disciplina arquivada",
        ),
        "preserved_shared_studies": {"count": len(preserved_shared_ids), "ids": preserved_shared_ids},
    }


def archive(conn, table, ident, restore=False):
    """Compatibilidade para as rotas antigas; regras específicas ficam acima."""
    if table == "formacoes":
        return restore_formation(conn, ident) if restore else archive_formation(conn, ident)
    if table == "materias_estudo":
        return archive_study(conn, ident, restore)
    if table == "disciplinas_grade":
        return archive_curriculum(conn, ident, restore)
    _get(conn, table, ident)
    repo.update(conn, table, ident, {"archived_at": None if restore else _now()})
    return _get(conn, table, ident)


def remove(conn, table, ident):
    _get(conn, table, ident)
    try: repo.delete(conn, table, ident)
    except sqlite3.IntegrityError as error: raise DomainError("Não é possível excluir porque há dados relacionados. Arquive o registro.", 409) from error


def formation_delete_blockers(conn, ident):
    """Conta vínculos que tornam insegura a exclusão definitiva de uma formação.

    A contagem inclui registros arquivados e históricos: eles ainda possuem chaves
    estrangeiras para a formação e, principalmente, não devem ser apagados como
    efeito colateral de uma ação na tela de Formações.
    """
    row = repo.one(conn, """
        WITH formation_studies AS (
            SELECT s.id
            FROM materias_estudo s
            LEFT JOIN disciplinas_grade d ON d.id=s.curriculum_subject_id
            WHERE s.related_formation_id=? OR d.formation_id=?
        ), formation_topics AS (
            SELECT t.id
            FROM topicos t
            WHERE t.study_subject_id IN (SELECT id FROM formation_studies)
               OR t.curriculum_subject_id IN (SELECT id FROM disciplinas_grade WHERE formation_id=?)
        )
        SELECT
            (SELECT COUNT(*) FROM disciplinas_grade WHERE formation_id=?) AS curriculum_subjects,
            (SELECT COUNT(*) FROM formation_studies) AS study_subjects,
            (SELECT COUNT(*) FROM formation_topics) AS topics,
            (SELECT COUNT(*) FROM sessoes_planejadas WHERE study_subject_id IN (SELECT id FROM formation_studies)) AS planned_sessions,
            (SELECT COUNT(*) FROM sessoes_estudo WHERE study_subject_id IN (SELECT id FROM formation_studies)) AS study_sessions,
            (SELECT COUNT(*) FROM anotacoes_estudo WHERE study_subject_id IN (SELECT id FROM formation_studies)) AS notes,
            (SELECT COUNT(*) FROM revisoes WHERE topic_id IN (SELECT id FROM formation_topics)) AS reviews,
            (SELECT COUNT(*) FROM avaliacoes WHERE study_subject_id IN (SELECT id FROM formation_studies) OR curriculum_subject_id IN (SELECT id FROM disciplinas_grade WHERE formation_id=?)) AS evaluations
    """, (ident, ident, ident, ident, ident))
    return {key: int(value or 0) for key, value in row.items()}


def delete_formation(conn, ident):
    formation = _get(conn, "formacoes", ident)
    blockers = formation_delete_blockers(conn, ident)
    if any(blockers.values()):
        labels = (
            ("curriculum_subjects", "disciplina da grade", "disciplinas da grade"),
            ("study_subjects", "estudo", "estudos"),
            ("planned_sessions", "bloco de planejamento", "blocos de planejamento"),
            ("study_sessions", "sessão de estudo registrada", "sessões de estudo registradas"),
            ("notes", "anotação", "anotações"),
            ("reviews", "revisão", "revisões"),
            ("evaluations", "avaliação", "avaliações"),
        )
        related = [f"{blockers[key]} {singular if blockers[key] == 1 else plural}" for key, singular, plural in labels if blockers[key]]
        raise DomainError(
            f"Não é possível excluir “{formation['name']}” definitivamente: a formação ainda possui "
            f"{', '.join(related)}. Arquive a formação para preservar seu histórico.",
            409,
            "formation_has_dependencies",
            blockers,
        )
    _create_destructive_backup(conn)
    repo.delete(conn, "formacoes", ident)
    _assert_foreign_keys(conn)


def _sql_ids(values):
    identifiers = [int(value) for value in values if value is not None]
    if not identifiers:
        return "(NULL)", []
    return "(" + ",".join("?" for _ in identifiers) + ")", identifiers


def _selected_ids(conn, sql, params=()):
    return [row["id"] for row in repo.many(conn, sql, params)]


def _count_ids(values):
    return {"count": len(values), "ids": values}


def _dependency_scope(conn, curriculum_ids=(), study_ids=()):
    curriculum_ids = list(dict.fromkeys(int(value) for value in curriculum_ids))
    study_ids = list(dict.fromkeys(int(value) for value in study_ids))
    if curriculum_ids:
        marks, params = _sql_ids(curriculum_ids)
        study_ids.extend(_selected_ids(conn, f"SELECT id FROM materias_estudo WHERE curriculum_subject_id IN {marks}", params))
    study_ids = list(dict.fromkeys(study_ids))
    marks, params = _sql_ids(study_ids)
    group_ids = _selected_ids(conn, f"SELECT id FROM grupos_topicos WHERE study_subject_id IN {marks}", params)
    curriculum_marks, curriculum_params = _sql_ids(curriculum_ids)
    topic_ids = _selected_ids(conn, f"SELECT id FROM topicos WHERE study_subject_id IN {marks} OR curriculum_subject_id IN {curriculum_marks}", (*params, *curriculum_params))
    planned_rows = repo.many(conn, f"SELECT id,status FROM sessoes_planejadas WHERE study_subject_id IN {marks}", params)
    session_ids = _selected_ids(conn, f"SELECT id FROM sessoes_estudo WHERE study_subject_id IN {marks}", params)
    note_ids = _selected_ids(conn, f"SELECT id FROM anotacoes_estudo WHERE study_subject_id IN {marks}", params)
    review_marks, review_params = _sql_ids(topic_ids)
    review_ids = _selected_ids(conn, f"SELECT id FROM revisoes WHERE topic_id IN {review_marks}", review_params)
    evaluation_ids = _selected_ids(conn, f"SELECT id FROM avaliacoes WHERE study_subject_id IN {marks} OR curriculum_subject_id IN {curriculum_marks}", (*params, *curriculum_params))
    evaluation_marks, evaluation_params = _sql_ids(evaluation_ids)
    link_ids = _selected_ids(conn, f"SELECT rowid id FROM avaliacao_topicos WHERE evaluation_id IN {evaluation_marks}", evaluation_params)
    history_marks, history_params = _sql_ids(curriculum_ids)
    history_ids = _selected_ids(conn, f"SELECT id FROM curriculum_status_history WHERE curriculum_subject_id IN {history_marks}", history_params)
    timeline_ids = _selected_ids(conn, f"SELECT id FROM curriculum_timeline_events WHERE curriculum_subject_id IN {history_marks}", history_params)
    by_status = {status: 0 for status in ("planned", "completed", "skipped", "rescheduled", "cancelled")}
    for row in planned_rows:
        by_status[row["status"]] = by_status.get(row["status"], 0) + 1
    return {
        "curriculum_subjects": _count_ids(curriculum_ids),
        "study_subjects": _count_ids(study_ids),
        "groups": _count_ids(group_ids), "topics": _count_ids(topic_ids),
        "planned_sessions": {**_count_ids([row["id"] for row in planned_rows]), "by_status": by_status},
        "study_sessions": _count_ids(session_ids), "notes": _count_ids(note_ids),
        "reviews": _count_ids(review_ids), "evaluations": _count_ids(evaluation_ids),
        "evaluation_topic_links": _count_ids(link_ids), "status_history": _count_ids(history_ids), "timeline_events": _count_ids(timeline_ids),
    }


def _dependencies_payload(entity, dependencies):
    return {
        "entity": entity, "dependencies": dependencies,
        "has_dependencies": any(data["count"] for data in dependencies.values()),
    }


def curriculum_dependencies(conn, ident):
    item = _get(conn, "disciplinas_grade", ident)
    return _dependencies_payload(item, _dependency_scope(conn, [ident]))


def study_dependencies(conn, ident):
    study = _get(conn, "materias_estudo", ident)
    return _dependencies_payload(study, _dependency_scope(conn, [], [study["id"]]))


def formation_dependencies(conn, ident):
    formation = _get(conn, "formacoes", ident)
    curriculum_ids = _selected_ids(conn, "SELECT id FROM disciplinas_grade WHERE formation_id=?", (ident,))
    direct_studies = _selected_ids(conn, "SELECT id FROM materias_estudo WHERE related_formation_id=?", (ident,))
    dependencies = _dependency_scope(conn, curriculum_ids, direct_studies)
    # A categoria explícita permite ao diálogo explicar que a formação contém
    # disciplinas mesmo quando elas ainda não possuem estudo atual.
    return _dependencies_payload(formation, dependencies)


def _database_backup_path(conn):
    row = conn.execute("PRAGMA database_list").fetchone()
    database_file = row[2] if row else ""
    if not database_file or database_file == ":memory:":
        return None
    source = Path(database_file)
    if not source.exists():
        return None
    stamp = _local_now().strftime("%Y%m%d-%H%M%S")
    candidate = source.with_name(f"{source.stem}.{stamp}.before-destructive-delete{source.suffix}")
    suffix = 2
    while candidate.exists():
        candidate = source.with_name(f"{source.stem}.{stamp}.before-destructive-delete-{suffix}{source.suffix}")
        suffix += 1
    return candidate


def _create_destructive_backup(conn):
    target = _database_backup_path(conn)
    if not target:
        return None
    try:
        target_conn = sqlite3.connect(target)
        try:
            conn.backup(target_conn)
        finally:
            target_conn.close()
    except sqlite3.Error as error:
        raise DomainError("Não foi possível criar a cópia de segurança antes da exclusão.", 500, "backup_failed") from error
    return str(target)


def _assert_foreign_keys(conn):
    violations = [tuple(row) for row in conn.execute("PRAGMA foreign_key_check").fetchall()]
    if violations:
        raise DomainError("A validação de integridade falhou; a exclusão foi desfeita.", 500, "foreign_key_check_failed", details={"violations": violations})


def _delete_study_graph(conn, study_ids):
    marks, params = _sql_ids(study_ids)
    if not study_ids:
        return
    topic_ids = _selected_ids(conn, f"SELECT id FROM topicos WHERE study_subject_id IN {marks}", params)
    canonical_topic_ids = _selected_ids(conn, f"SELECT id FROM topicos WHERE study_subject_id IN {marks} AND curriculum_subject_id IS NOT NULL", params)
    delete_topic_ids = [ident for ident in topic_ids if ident not in canonical_topic_ids]
    topic_marks, topic_params = _sql_ids(delete_topic_ids)
    evaluation_ids = _selected_ids(conn, f"SELECT id FROM avaliacoes WHERE study_subject_id IN {marks}", params)
    retained_evaluation_ids = _selected_ids(conn, f"SELECT id FROM avaliacoes WHERE study_subject_id IN {marks} AND curriculum_subject_id IS NOT NULL", params)
    delete_evaluation_ids = [ident for ident in evaluation_ids if ident not in retained_evaluation_ids]
    evaluation_marks, evaluation_params = _sql_ids(delete_evaluation_ids)
    # A ordem é deliberada: remove referências opcionais antes das entidades
    # referenciadas e nunca depende de uma cascata ampla para ocultar a lógica.
    conn.execute(f"DELETE FROM anotacoes_estudo WHERE study_subject_id IN {marks}", params)
    conn.execute(f"DELETE FROM avaliacao_topicos WHERE evaluation_id IN {evaluation_marks} OR topic_id IN {topic_marks}", (*evaluation_params, *topic_params))
    all_topic_marks, all_topic_params = _sql_ids(topic_ids)
    conn.execute(f"DELETE FROM revisoes WHERE topic_id IN {all_topic_marks}", all_topic_params)
    conn.execute(f"DELETE FROM sessoes_estudo WHERE study_subject_id IN {marks}", params)
    conn.execute(f"DELETE FROM sessoes_planejadas WHERE study_subject_id IN {marks}", params)
    conn.execute(f"DELETE FROM avaliacoes WHERE id IN {evaluation_marks}", evaluation_params)
    retained_eval_marks, retained_eval_params = _sql_ids(retained_evaluation_ids)
    conn.execute(f"UPDATE avaliacoes SET study_subject_id=NULL WHERE id IN {retained_eval_marks}", retained_eval_params)
    conn.execute(f"DELETE FROM topicos WHERE id IN {topic_marks}", topic_params)
    canonical_marks, canonical_params = _sql_ids(canonical_topic_ids)
    conn.execute(f"UPDATE topicos SET study_subject_id=NULL,group_id=NULL WHERE id IN {canonical_marks}", canonical_params)
    conn.execute(f"DELETE FROM grupos_topicos WHERE study_subject_id IN {marks}", params)
    conn.execute(f"DELETE FROM materias_estudo WHERE id IN {marks}", params)


def _delete_curriculum_graph(conn, curriculum_ids):
    marks, params = _sql_ids(curriculum_ids)
    study_ids = _selected_ids(conn, f"SELECT id FROM materias_estudo WHERE curriculum_subject_id IN {marks}", params)
    _delete_study_graph(conn, study_ids)
    topic_ids = _selected_ids(conn, f"SELECT id FROM topicos WHERE curriculum_subject_id IN {marks}", params)
    topic_marks, topic_params = _sql_ids(topic_ids)
    evaluation_ids = _selected_ids(conn, f"SELECT id FROM avaliacoes WHERE curriculum_subject_id IN {marks}", params)
    evaluation_marks, evaluation_params = _sql_ids(evaluation_ids)
    conn.execute(f"DELETE FROM avaliacao_topicos WHERE evaluation_id IN {evaluation_marks} OR topic_id IN {topic_marks}", (*evaluation_params, *topic_params))
    conn.execute(f"DELETE FROM revisoes WHERE topic_id IN {topic_marks}", topic_params)
    conn.execute(f"DELETE FROM topicos WHERE id IN {topic_marks}", topic_params)
    conn.execute(f"DELETE FROM avaliacoes WHERE id IN {evaluation_marks}", evaluation_params)
    conn.execute(f"DELETE FROM curriculum_timeline_events WHERE curriculum_subject_id IN {marks}", params)


def _require_destroy_confirmation(entity, confirmation, has_dependencies, include_dependencies):
    expected = entity["name"] if "name" in entity else entity.get("personal_name")
    if str(confirmation or "").strip() != str(expected or "").strip():
        raise DomainError(
            "Digite exatamente o nome do registro para confirmar a exclusão definitiva.", 400,
            "typed_confirmation_required", details={"expected_confirmation": expected},
        )
    if has_dependencies and not _confirmed(include_dependencies):
        raise DomainError(
            "Confirme que os dados dependentes exibidos na prévia também serão excluídos.", 400,
            "dependency_confirmation_required",
        )


def destructive_preview(conn, kind, ident):
    handlers = {"formation": formation_dependencies, "curriculum": curriculum_dependencies, "study": study_dependencies}
    if kind not in handlers: raise DomainError("Tipo de exclusão inválido.")
    preview = handlers[kind](conn, ident)
    expected = preview["entity"].get("name") or preview["entity"].get("personal_name")
    preview["required_confirmation"] = expected
    preview["destructive_action"] = True
    return preview


def destroy(conn, kind, ident, confirmation, include_dependencies=False):
    preview = destructive_preview(conn, kind, ident)
    entity = preview["entity"]
    _require_destroy_confirmation(entity, confirmation, preview["has_dependencies"], include_dependencies)
    backup = _create_destructive_backup(conn)
    dependencies = preview["dependencies"]
    if kind == "study":
        _delete_study_graph(conn, dependencies["study_subjects"]["ids"])
    elif kind == "curriculum":
        _delete_curriculum_graph(conn, dependencies["curriculum_subjects"]["ids"])
        marks, params = _sql_ids(dependencies["curriculum_subjects"]["ids"])
        conn.execute(f"DELETE FROM curriculum_status_history WHERE curriculum_subject_id IN {marks}", params)
        conn.execute(f"DELETE FROM disciplinas_grade WHERE id IN {marks}", params)
    elif kind == "formation":
        _delete_curriculum_graph(conn, dependencies["curriculum_subjects"]["ids"])
        marks, params = _sql_ids(dependencies["curriculum_subjects"]["ids"])
        conn.execute(f"DELETE FROM curriculum_status_history WHERE curriculum_subject_id IN {marks}", params)
        conn.execute(f"DELETE FROM disciplinas_grade WHERE id IN {marks}", params)
        conn.execute("DELETE FROM formacoes WHERE id=?", (ident,))
    else:
        raise DomainError("Tipo de exclusão inválido.")
    _assert_foreign_keys(conn)
    return {"deleted": True, "kind": kind, "id": ident, "backup": backup, "preview": preview}


def delete_curriculum(conn, ident):
    preview = curriculum_dependencies(conn, ident)
    # Histórico de status é técnico, mas ainda é dependência auditável: a remoção
    # simples continua permitida apenas quando não há nenhum vínculo.
    if preview["has_dependencies"]:
        raise DomainError("Não é possível excluir porque há dados relacionados. Consulte as dependências ou use a exclusão definitiva confirmada.", 409, "curriculum_has_dependencies", preview["dependencies"])
    _create_destructive_backup(conn)
    repo.delete(conn, "disciplinas_grade", ident); _assert_foreign_keys(conn)


def delete_study(conn, ident):
    preview = study_dependencies(conn, ident)
    if preview["has_dependencies"]:
        raise DomainError("Não é possível excluir porque há dados relacionados. Consulte as dependências ou use a exclusão definitiva confirmada.", 409, "study_has_dependencies", preview["dependencies"])
    _create_destructive_backup(conn)
    repo.delete(conn, "materias_estudo", ident); _assert_foreign_keys(conn)


def _curriculum_summary(conn, formation_id):
    totals = repo.one(conn, """
        SELECT
          COUNT(*) FILTER (WHERE archived_at IS NULL) all_active_items,
          COUNT(*) FILTER (WHERE archived_at IS NULL AND item_type='subject') total_subjects,
          COUNT(*) FILTER (WHERE archived_at IS NULL AND item_type='subject' AND academic_status='completed') completed,
          COUNT(*) FILTER (WHERE archived_at IS NULL AND item_type='subject' AND academic_status='exempted') exempted,
          COUNT(*) FILTER (WHERE archived_at IS NULL AND item_type='subject' AND academic_status='in_progress') in_progress,
          COUNT(*) FILTER (WHERE archived_at IS NULL AND item_type='subject' AND academic_status='failed') failed,
          COUNT(*) FILTER (WHERE archived_at IS NULL AND item_type='subject' AND academic_status='locked') locked,
          COUNT(*) FILTER (WHERE archived_at IS NULL AND item_type='subject' AND academic_status='available') available,
          COUNT(*) FILTER (WHERE archived_at IS NULL AND item_type='subject' AND academic_status='not_available') not_available,
          COUNT(*) FILTER (WHERE archived_at IS NULL AND item_type='subject' AND academic_status NOT IN ('completed','exempted')) pending,
          COUNT(*) FILTER (WHERE archived_at IS NULL AND item_type='subject' AND review_status IN ('queued','in_progress')) review,
          COUNT(*) FILTER (WHERE archived_at IS NOT NULL) archived,
          COUNT(*) FILTER (WHERE archived_at IS NULL AND item_type='section') sections
        FROM disciplinas_grade WHERE formation_id=?
    """, (formation_id,))
    summary = {key: int(value or 0) for key, value in totals.items()}
    summary["satisfied"] = summary["completed"] + summary["exempted"]
    summary["academic_progress_percent"] = round(summary["satisfied"] * 100 / summary["total_subjects"], 1) if summary["total_subjects"] else 0
    summary["by_status"] = {key: summary[key] for key in ACADEMIC_STATUSES}
    summary["by_review_status"] = {
        status: int(repo.one(conn, "SELECT COUNT(*) count FROM disciplinas_grade WHERE formation_id=? AND archived_at IS NULL AND item_type='subject' AND review_status=?", (formation_id, status))["count"])
        for status in REVIEW_STATUSES
    }
    periods = repo.many(conn, """
        SELECT COALESCE(NULLIF(period,''),'Sem período') period,
          COUNT(*) FILTER (WHERE item_type='subject') total_subjects,
          COUNT(*) FILTER (WHERE item_type='subject' AND academic_status='completed') completed,
          COUNT(*) FILTER (WHERE item_type='subject' AND academic_status='exempted') exempted,
          COUNT(*) FILTER (WHERE item_type='subject' AND academic_status='in_progress') in_progress,
          COUNT(*) FILTER (WHERE item_type='subject' AND academic_status NOT IN ('completed','exempted')) pending,
          COUNT(*) FILTER (WHERE item_type='subject' AND review_status IN ('queued','in_progress')) review
        FROM disciplinas_grade
        WHERE formation_id=? AND archived_at IS NULL
        GROUP BY COALESCE(NULLIF(period,''),'Sem período')
        ORDER BY MIN(sort_order), period
    """, (formation_id,))
    for period in periods:
        period["academic_progress_percent"] = round((period["completed"] + period["exempted"]) * 100 / period["total_subjects"], 1) if period["total_subjects"] else 0
    summary["by_period"] = periods
    return summary


def _curriculum_query(conn, formation_id, filters=None):
    filters = filters or {}
    clauses, params = ["d.formation_id=?"], [formation_id]
    visibility = filters.get("visibility")
    if visibility is None:
        visibility = "all" if filters.get("include_archived") else "active"
    if visibility not in {"active", "archived", "all"}:
        raise DomainError("Filtro de arquivamento da grade inválido.")
    if visibility == "active": clauses.append("d.archived_at IS NULL")
    elif visibility == "archived": clauses.append("d.archived_at IS NOT NULL")
    quick = filters.get("quick")
    quick_conditions = {
        "all": None, "available": "d.academic_status='available'", "in_progress": "d.academic_status='in_progress'",
        "review": "d.review_status IN ('queued','in_progress')", "completed": "d.academic_status='completed'",
        "pending": "d.academic_status NOT IN ('completed','exempted')", "failed": "d.academic_status='failed'",
        "locked": "d.academic_status='locked'", "exempted": "d.academic_status='exempted'", "archived": "d.archived_at IS NOT NULL",
    }
    if quick:
        if quick not in quick_conditions:
            raise DomainError("Filtro rápido da grade inválido.")
        if quick == "archived":
            clauses = [clause for clause in clauses if clause != "d.archived_at IS NULL"]
        if quick_conditions[quick]: clauses.append(quick_conditions[quick])
    for field, column, allowed in (
        ("academic_status", "d.academic_status", ACADEMIC_STATUSES),
        ("review_status", "d.review_status", REVIEW_STATUSES),
        ("item_type", "d.item_type", ITEM_TYPES),
    ):
        value = filters.get(field)
        if value:
            values = [item.strip() for item in str(value).split(",") if item.strip()]
            if not values or any(item not in allowed for item in values):
                raise DomainError(f"Filtro {field} inválido.")
            clauses.append(f"{column} IN ({','.join('?' for _ in values)})")
            params.extend(values)
    period = filters.get("period")
    if period:
        clauses.append("COALESCE(d.period,'')=?"); params.append(str(period))
    query = str(filters.get("q") or "").strip()
    if query:
        clauses.append("(d.name LIKE ? COLLATE NOCASE OR d.code LIKE ? COLLATE NOCASE)")
        params.extend([f"%{query}%", f"%{query}%"])
    order = filters.get("sort", "period")
    orders = {
        "period": "COALESCE(d.period,''),d.sort_order,d.name COLLATE NOCASE",
        "order": "d.sort_order,d.name COLLATE NOCASE", "name": "d.name COLLATE NOCASE",
        "status": "d.academic_status,d.name COLLATE NOCASE", "updated": "d.updated_at DESC,d.name COLLATE NOCASE",
    }
    if order not in orders: raise DomainError("Ordenação da grade inválida.")
    sql = """
        SELECT d.*, s.id active_study_id, s.status active_study_status
        FROM disciplinas_grade d
        LEFT JOIN materias_estudo s ON s.curriculum_subject_id=d.id
          AND s.status IN ('active','paused') AND s.archived_at IS NULL
        WHERE """ + " AND ".join(clauses) + " ORDER BY " + orders[order]
    return repo.many(conn, sql, params)


def curriculum(conn, formation_id, include_archived=False):
    _get(conn, "formacoes", formation_id)
    return _curriculum_query(conn, formation_id, {"include_archived": include_archived})


def curriculum_management(conn, formation_id, filters=None):
    formation = _get(conn, "formacoes", formation_id)
    items = _curriculum_query(conn, formation_id, filters)
    all_periods = repo.many(conn, "SELECT DISTINCT period FROM disciplinas_grade WHERE formation_id=? AND period IS NOT NULL AND trim(period)<>'' ORDER BY period", (formation_id,))
    return {
        "formation": formation, "items": items, "summary": _curriculum_summary(conn, formation_id),
        "periods": [row["period"] for row in all_periods], "filters": filters or {},
    }


def _curriculum_data(values, current=None):
    data = _fields(values, CURRICULUM)
    for key in ("code", "period", "start_date", "end_date", "deadline_date", "notes", "review_notes", "allowed_weekdays", "minimum_grade"):
        if data.get(key) == "":
            data[key] = None
    candidate = {**(current or {}), **data}
    if current is None:
        data["name"] = _need(data.get("name"), "Nome da disciplina")
    elif "name" in data:
        data["name"] = _need(data["name"], "Nome da disciplina")
    if "workload_minutes" in data and data["workload_minutes"] is not None:
        data["workload_minutes"] = _optional_minutes(data["workload_minutes"], "Carga horária")
    for key, label in (("required_study_minutes", "Esforço pessoal necessário"),):
        if key in data:
            data[key] = _optional_minutes(data[key], label)
    if "preferred_block_minutes" in data:
        data["preferred_block_minutes"] = _optional_block_minutes(data["preferred_block_minutes"])
    if "allowed_weekdays" in data:
        data["allowed_weekdays"] = _weekdays_json(data["allowed_weekdays"]) if data["allowed_weekdays"] is not None else None
    if "minimum_grade" in data:
        data["minimum_grade"] = _optional_number(data["minimum_grade"], "Nota mínima")
    if "priority_base" in data and data["priority_base"] not in (None, ""):
        try:
            base_priority = int(data["priority_base"])
        except (TypeError, ValueError) as error:
            raise DomainError("Prioridade-base deve ser um número de 1 a 5.") from error
        if not 1 <= base_priority <= 5:
            raise DomainError("Prioridade-base deve estar entre 1 e 5.")
        data["priority_base"] = base_priority
    if "planning_enabled" in data:
        data["planning_enabled"] = 1 if _confirmed(data["planning_enabled"]) else 0
    for key in ("effort_is_provisional", "deadline_is_provisional"):
        if key in data:
            data[key] = 1 if _confirmed(data[key]) else 0
    status = candidate.get("academic_status", "not_available")
    if status not in ACADEMIC_STATUSES:
        raise DomainError("Status acadêmico inválido.")
    review_status = candidate.get("review_status", "none")
    if review_status not in REVIEW_STATUSES:
        raise DomainError("Status de revisão inválido.")
    item_type = candidate.get("item_type", "subject")
    if item_type not in ITEM_TYPES:
        raise DomainError("Tipo de item curricular inválido.")
    if "review_priority" in data and data["review_priority"] not in (None, ""):
        try: priority = int(data["review_priority"])
        except (TypeError, ValueError) as error: raise DomainError("Prioridade de revisão deve ser um número de 1 a 5.") from error
        if not 1 <= priority <= 5: raise DomainError("Prioridade de revisão deve estar entre 1 e 5.")
        data["review_priority"] = priority
    elif data.get("review_priority") == "":
        data["review_priority"] = None
    if "sort_order" in data:
        try:
            order = int(data["sort_order"])
        except (TypeError, ValueError) as error:
            raise DomainError("Ordem deve ser um número inteiro igual ou maior que zero.") from error
        if order < 0:
            raise DomainError("Ordem deve ser igual ou maior que zero.")
        data["sort_order"] = order
    start, end, deadline = candidate.get("start_date"), candidate.get("end_date"), candidate.get("deadline_date")
    if start:
        _date(start, "Data de início")
    if end:
        _date(end, "Data de término")
    if deadline:
        _date(deadline, "Prazo principal")
    if start and end and start > end:
        raise DomainError("A data de término não pode ser anterior à data de início.")
    if start and deadline and start > deadline:
        raise DomainError("O prazo principal não pode ser anterior à data de início.")
    return data


def create_curriculum(conn, formation_id, values):
    _active_formation(conn, formation_id)
    data = _curriculum_data(values)
    data.update({"formation_id": formation_id})
    if "planning_enabled" in data:
        data["planning_opt_out"] = 0 if data["planning_enabled"] else 1
    data.setdefault("academic_status", "not_available"); data.setdefault("review_status", "none")
    data.setdefault("item_type", "subject"); data.setdefault("sort_order", 0)
    try: ident = repo.insert(conn, "disciplinas_grade", data)
    except sqlite3.IntegrityError as error: raise DomainError("Já existe uma disciplina com esse nome nesta formação.", 409) from error
    return _get(conn, "disciplinas_grade", ident)


def _record_curriculum_status(conn, current, saved, origin="manual", notes=None):
    if current["academic_status"] == saved["academic_status"] and current["review_status"] == saved["review_status"]:
        return None
    return repo.insert(conn, "curriculum_status_history", {
        "curriculum_subject_id": saved["id"],
        "previous_academic_status": current["academic_status"], "academic_status": saved["academic_status"],
        "previous_review_status": current["review_status"], "review_status": saved["review_status"],
        "origin": origin, "notes": notes,
    })


def change_curriculum_status(conn, ident, values, origin="manual", notes=None):
    current = _get(conn, "disciplinas_grade", ident)
    _active_formation(conn, current["formation_id"])
    if current["archived_at"]:
        raise DomainError("Restaure a disciplina antes de alterar seu estado.", 409, "curriculum_archived")
    data = _curriculum_data(values, current)
    status_data = _fields(data, {"academic_status", "review_status", "review_priority", "review_notes"})
    if status_data:
        repo.update(conn, "disciplinas_grade", ident, status_data)
    saved = _get(conn, "disciplinas_grade", ident)
    _record_curriculum_status(conn, current, saved, origin, notes)
    return saved


def update_curriculum(conn, ident, values):
    current = _get(conn, "disciplinas_grade", ident)
    _active_formation(conn, current["formation_id"])
    if current["archived_at"]:
        raise DomainError("Restaure a disciplina antes de editá-la.", 409, "curriculum_archived")
    data = _curriculum_data(values, current)
    if "planning_enabled" in data:
        data["planning_opt_out"] = 0 if data["planning_enabled"] else 1
    if "required_study_minutes" in data and data["required_study_minutes"] is not None:
        distributed = sum(int(row.get("estimated_minutes") or 0) for row in _topic_owner_topics(conn, "curriculum", ident))
        if distributed > int(data["required_study_minutes"]):
            raise DomainError(
                f"O esforço total não pode ser reduzido para {int(data['required_study_minutes'])} min porque os tópicos já distribuem {distributed} min.",
                409,
                "topic_effort_overflow",
                details={"required_minutes": int(data["required_study_minutes"]), "distributed_minutes": distributed},
            )
    ordinary = {key: value for key, value in data.items() if key not in {"academic_status", "review_status", "review_priority", "review_notes"}}
    if ordinary: repo.update(conn, "disciplinas_grade", ident, ordinary)
    if any(key in data for key in {"academic_status", "review_status", "review_priority", "review_notes"}):
        saved = change_curriculum_status(conn, ident, data, "manual", values.get("status_notes"))
    else:
        saved = _get(conn, "disciplinas_grade", ident)
    schedule_keys = {"start_date", "end_date", "deadline_date", "workload_minutes", "required_study_minutes", "priority_base", "preferred_block_minutes", "allowed_weekdays", "planning_enabled", "planning_opt_out"}
    changed = [key for key in schedule_keys if key in data and current.get(key) != saved.get(key)]
    if changed:
        _event(conn, ident, "schedule_settings", "Configurações de prazo/esforço atualizadas", ", ".join(sorted(changed)))
    return saved


def curriculum_status_history(conn, ident):
    _get(conn, "disciplinas_grade", ident)
    return repo.many(conn, "SELECT * FROM curriculum_status_history WHERE curriculum_subject_id=? ORDER BY created_at DESC,id DESC", (ident,))


def _shared_study_context_for_curriculum(conn, curriculum_id):
    """Resolve o estudo e todas as ocorrências visíveis de uma disciplina."""
    resolved = _canonical(lambda: canonical_links.canonical_study_for_subject(conn, curriculum_id))
    if not resolved:
        return None, []
    linked = _canonical(lambda: canonical_links.linked_curriculum_subjects(conn, resolved["study"]["id"]))
    return resolved, linked


def curriculum_effort(conn, curriculum_id):
    item = _get(conn, "disciplinas_grade", curriculum_id)
    resolved, linked_curricula = _shared_study_context_for_curriculum(conn, curriculum_id)
    is_shared = len(linked_curricula) > 1
    studies_rows = repo.many(conn, "SELECT id,status FROM materias_estudo WHERE curriculum_subject_id=?", (curriculum_id,))
    # Uma ocorrência vinculada lê a mesma trilha de sessões e blocos do objeto
    # canônico, sem transformar seu próprio prazo/nota acadêmica em dado da
    # outra formação.
    if is_shared and resolved:
        study_ids = [resolved["study"]["id"]]
    else:
        study_ids = [row["id"] for row in studies_rows]
    marks, params = _ids_clause(study_ids)
    real = repo.one(conn, f"SELECT COALESCE(SUM(duration_seconds),0)/60 minutes FROM sessoes_estudo WHERE study_subject_id IN {marks}", params)["minutes"] if study_ids else 0
    planned_minutes = repo.one(conn, f"SELECT COALESCE(SUM(planned_duration_minutes),0) minutes FROM sessoes_planejadas WHERE study_subject_id IN {marks} AND status='planned' AND scheduled_date>=?", (*params, _today()))["minutes"] if study_ids else 0
    required = item.get("required_study_minutes")
    canonical_curriculum_id = resolved["study"].get("curriculum_subject_id") if resolved else None
    if is_shared and not required and canonical_curriculum_id:
        required = _get(conn, "disciplinas_grade", canonical_curriculum_id).get("required_study_minutes")
    remaining = max(0, int(required) - int(real or 0)) if required else None
    return {
        "required_study_minutes": required, "real_minutes": int(real or 0),
        "remaining_minutes": remaining, "future_planned_minutes": int(planned_minutes or 0),
        "unallocated_minutes": max(0, remaining - int(planned_minutes or 0)) if remaining is not None else None,
        "effort_progress_percent": round(int(real or 0) * 100 / int(required), 1) if required else None,
        "active_study_id": (resolved["study"]["id"] if is_shared and resolved["study"]["status"] in {"active", "paused"}
                            else next((row["id"] for row in studies_rows if row["status"] in {"active", "paused"}), None)),
        "is_shared_study": is_shared,
        "canonical_study_id": resolved["study"]["id"] if resolved else None,
        "canonical_curriculum_subject_id": canonical_curriculum_id,
        "shared_curriculum_subjects": linked_curricula,
    }


def curriculum_shared_study(conn, curriculum_id):
    """Estado, candidatas e auditoria do compartilhamento opt-in de estudo."""
    _get(conn, "disciplinas_grade", curriculum_id)
    linked = _canonical(lambda: canonical_links.canonical_study_for_subject(conn, curriculum_id))
    return {
        "link": linked,
        "candidates": _canonical(lambda: canonical_links.equivalence_candidates(conn, curriculum_id))["candidates"],
        "audit": _canonical(lambda: canonical_links.link_audit(conn, curriculum_id)),
        "automatic_linking": False,
    }


def link_curriculum_shared_study(conn, curriculum_id, values=None):
    values = values or {}
    canonical_study_id = values.get("canonical_study_id") or values.get("study_subject_id")
    try:
        canonical_study_id = int(canonical_study_id)
    except (TypeError, ValueError) as error:
        raise DomainError("Escolha o estudo canônico que será compartilhado.") from error
    return _canonical(lambda: canonical_links.link_curriculum_subject(conn, curriculum_id, canonical_study_id, values))


def unlink_curriculum_shared_study(conn, curriculum_id, values=None):
    return _canonical(lambda: canonical_links.unlink_curriculum_subject(conn, curriculum_id, values or {}))


def curriculum_schedule_settings(conn, curriculum_id):
    item = _get(conn, "disciplinas_grade", curriculum_id)
    return {
        "curriculum": item,
        "settings": {key: item.get(key) for key in (
            "start_date", "end_date", "deadline_date", "workload_minutes", "required_study_minutes",
            "priority_base", "preferred_block_minutes", "allowed_weekdays", "planning_enabled", "minimum_grade", "notes",
        )},
        "effort": curriculum_effort(conn, curriculum_id),
    }


def curriculum_detail(conn, curriculum_id):
    item = _get(conn, "disciplinas_grade", curriculum_id)
    content_data = contents(conn, curriculum_id)
    content_rows = content_data["contents"]
    archived_content_rows = [row for row in contents(conn, curriculum_id, include_archived=True)["contents"] if row.get("archived_at")]
    completed = sum(1 for row in content_rows if row["status"] == "completed")
    return {
        "curriculum": item, "effort": curriculum_effort(conn, curriculum_id),
        "topic_effort": content_data.get("effort_distribution"),
        "contents": content_rows, "archived_contents": archived_content_rows,
        "content_progress": {
            "total": len(content_rows), "completed": completed,
            "percent": round(completed * 100 / len(content_rows), 1) if content_rows else 0,
        },
        "evaluations": evaluation_summary(conn, curriculum_id),
        "history": curriculum_status_history(conn, curriculum_id),
        "shared_study": curriculum_shared_study(conn, curriculum_id),
    }


def curriculum_timeline(conn, curriculum_id):
    _get(conn, "disciplinas_grade", curriculum_id)
    resolved, linked_curricula = _shared_study_context_for_curriculum(conn, curriculum_id)
    shared_study_id = resolved["study"]["id"] if resolved and len(linked_curricula) > 1 else None
    events = []
    for row in curriculum_status_history(conn, curriculum_id):
        events.append({"type": "status", "date": row["created_at"], "title": "Estado acadêmico/revisão atualizado", "details": row.get("notes")})
    for row in repo.many(conn, "SELECT * FROM curriculum_timeline_events WHERE curriculum_subject_id=?", (curriculum_id,)):
        events.append({"type": row["event_type"], "date": row["created_at"], "title": row["title"], "details": row.get("details")})
    session_sql = "SELECT x.date,x.duration_seconds,t.name FROM sessoes_estudo x JOIN materias_estudo s ON s.id=x.study_subject_id LEFT JOIN topicos t ON t.id=x.topic_id WHERE "
    session_params = (shared_study_id,) if shared_study_id else (curriculum_id,)
    session_sql += "x.study_subject_id=?" if shared_study_id else "s.curriculum_subject_id=?"
    for row in repo.many(conn, session_sql, session_params):
        events.append({"type": "session", "date": row["date"], "title": f"Sessão realizada{': ' + row['name'] if row.get('name') else ''}", "details": f"{int(row['duration_seconds']) // 60} min"})
    planning_sql = "SELECT p.scheduled_date,p.status,t.name FROM sessoes_planejadas p JOIN materias_estudo s ON s.id=p.study_subject_id LEFT JOIN topicos t ON t.id=p.topic_id WHERE "
    planning_params = (shared_study_id,) if shared_study_id else (curriculum_id,)
    planning_sql += "p.study_subject_id=?" if shared_study_id else "s.curriculum_subject_id=?"
    planning_sql += " AND p.status IN ('cancelled','rescheduled')"
    for row in repo.many(conn, planning_sql, planning_params):
        events.append({"type": "planning", "date": row["scheduled_date"], "title": "Bloco cancelado" if row["status"] == "cancelled" else "Bloco reagendado", "details": row.get("name")})
    for row in evaluations(conn, curriculum_id=curriculum_id):
        events.append({"type": "evaluation", "date": row["date"], "title": f"Avaliação: {row['title']}", "details": row.get("score")})
    return sorted(events, key=lambda row: str(row["date"]), reverse=True)


def curriculum_import_preview(conn, formation_id, result):
    _get(conn, "formacoes", formation_id)
    existing = repo.many(conn, "SELECT id,name FROM disciplinas_grade WHERE formation_id=?", (formation_id,))
    return grade_import.annotate_duplicates(result, existing)


def _confirmed(value):
    return value in (True, 1, "1", "true", "True", "sim", "Sim")


def _duplicate_action(value):
    action = grade_import.normalized(value or "skip")
    aliases = {"skip": "skip", "ignore": "skip", "ignorar": "skip", "update": "update", "atualizar": "update", "keep both": "keep_both", "keep_both": "keep_both", "manter as duas": "keep_both"}
    return aliases.get(action)


def _import_payload_item(value, index):
    if not isinstance(value, dict):
        return None, {"row": index + 1, "name": "", "errors": ["Linha de importação inválida."]}
    row = grade_import.normalize_row(
        value,
        source="Prévia confirmada",
        source_index=index + 1,
        default_order=index + 1,
    )
    return row, None


def _curriculum_item_from_preview(row):
    return {
        "name": row["name"],
        "code": row["code"],
        "period": row["period"],
        "workload_minutes": row["workload_minutes"],
        "academic_status": row["academic_status"],
        "sort_order": row["sort_order"],
        "start_date": row["start_date"],
        "end_date": row["end_date"],
        "notes": row["notes"],
    }


def import_curriculum(conn, formation_id, items, confirmed=False):
    _active_formation(conn, formation_id)
    if not _confirmed(confirmed):
        raise DomainError("Revise a prévia e confirme a importação antes de gravar a grade.", 400, "import_confirmation_required")
    if not isinstance(items, list):
        raise DomainError("As disciplinas da importação devem ser uma lista.")
    if len(items) > grade_import.MAX_ROWS:
        raise DomainError(f"A importação aceita no máximo {grade_import.MAX_ROWS} linhas.")

    existing_rows = repo.many(conn, "SELECT * FROM disciplinas_grade WHERE formation_id=?", (formation_id,))
    existing = {grade_import.normalized_name(row["name"]): row for row in existing_rows}
    planned, skipped, errors, seen = [], [], [], set()
    for index, value in enumerate(items):
        row, row_error = _import_payload_item(value, index)
        if row_error:
            errors.append(row_error)
            continue
        if not row["include"]:
            skipped.append({"row": index + 1, "name": row["name"], "reason": "not_selected"})
            continue
        if row["errors"]:
            errors.append({"row": index + 1, "name": row["name"], "errors": row["errors"]})
            continue
        key = grade_import.normalized_name(row["name"])
        action = _duplicate_action(value.get("duplicate_action"))
        if not action:
            errors.append({"row": index + 1, "name": row["name"], "errors": ["Ação de duplicidade inválida."]})
            continue
        if key in seen:
            if action == "skip":
                skipped.append({"row": index + 1, "name": row["name"], "reason": "duplicate_in_preview"})
                continue
            errors.append({"row": index + 1, "name": row["name"], "errors": ["Há outra linha selecionada com o mesmo nome; renomeie ou ignore uma delas."]})
            continue
        if key in existing:
            if action == "skip":
                skipped.append({"row": index + 1, "name": row["name"], "reason": "duplicate", "existing_id": existing[key]["id"]})
                continue
            if action == "keep_both":
                errors.append({"row": index + 1, "name": row["name"], "errors": ["Para manter as duas disciplinas, renomeie esta linha antes de confirmar."]})
                continue
            planned.append(("update", existing[key]["id"], row))
            seen.add(key)
            continue
        seen.add(key)
        planned.append(("insert", None, row))
    if errors:
        raise DomainError("Corrija as linhas destacadas antes de confirmar a importação.", 400, "curriculum_import_invalid", details={"rows": errors})

    inserted, updated = [], []
    for operation, existing_id, row in planned:
        values = _curriculum_item_from_preview(row)
        if operation == "insert":
            inserted.append(create_curriculum(conn, formation_id, values))
        else:
            previous = _get(conn, "disciplinas_grade", existing_id)
            data = _curriculum_data(values, previous)
            ordinary = {key: value for key, value in data.items() if key not in {"academic_status", "review_status", "review_priority", "review_notes"}}
            if ordinary:
                repo.update(conn, "disciplinas_grade", existing_id, ordinary)
            if any(key in data for key in {"academic_status", "review_status", "review_priority", "review_notes"}):
                updated.append(change_curriculum_status(conn, existing_id, data, "import"))
            else:
                updated.append(_get(conn, "disciplinas_grade", existing_id))
    return {
        "inserted": inserted,
        "updated": updated,
        "skipped": skipped,
        "summary": {"requested": len(items), "inserted": len(inserted), "updated": len(updated), "skipped": len(skipped)},
    }


def _comparison_key(value):
    raw = unicodedata.normalize("NFKD", str(value or ""))
    raw = "".join(character for character in raw if not unicodedata.combining(character))
    raw = raw.casefold()
    return re.sub(r"\s+", " ", re.sub(r"[^\w]+", " ", raw)).strip()


def _candidate_summary(conn, item):
    dependencies = _dependency_scope(conn, [item["id"]])
    return {
        "id": item["id"], "name": item["name"], "code": item["code"], "period": item["period"],
        "workload_minutes": item["workload_minutes"], "academic_status": item["academic_status"],
        "review_status": item["review_status"], "review_priority": item["review_priority"],
        "item_type": item["item_type"], "archived_at": item["archived_at"],
        "dependencies": {key: value["count"] for key, value in dependencies.items()},
    }


def duplicate_candidates(conn, formation_id):
    _get(conn, "formacoes", formation_id)
    rows = repo.many(conn, "SELECT * FROM disciplinas_grade WHERE formation_id=? AND item_type='subject' ORDER BY sort_order,name", (formation_id,))
    full_keys = {_comparison_key(row["name"]) for row in rows}
    groups = defaultdict(list)
    for row in rows:
        key = _comparison_key(row["name"])
        trailing = re.fullmatch(r"(.+?)\s+(\d{2,4})", key)
        if trailing and trailing.group(1) in full_keys:
            # Só retira o número quando há uma disciplina irmã com o nome-base;
            # assim Cálculo I e Circuitos II nunca perdem seu identificador.
            key = trailing.group(1)
        groups[key].append(row)
    candidates = []
    for key, items in groups.items():
        if len(items) < 2: continue
        candidates.append({
            "comparison_key": key,
            "candidates": [_candidate_summary(conn, item) for item in items],
            "requires_manual_merge": True,
        })
    return {"formation_id": formation_id, "groups": candidates, "count": len(candidates)}


def structural_candidates(conn, formation_id):
    _get(conn, "formacoes", formation_id)
    rows = repo.many(conn, """
        SELECT * FROM disciplinas_grade
        WHERE formation_id=? AND item_type='subject' AND name LIKE 'UCFC %' COLLATE NOCASE
        ORDER BY sort_order,name
    """, (formation_id,))
    return {"formation_id": formation_id, "items": [_candidate_summary(conn, item) for item in rows], "count": len(rows)}


def merge_curriculum(conn, formation_id, primary_id, duplicate_ids, preserve=None, confirmation=None):
    _active_formation(conn, formation_id)
    try:
        primary_id = int(primary_id)
        duplicate_ids = [int(item) for item in duplicate_ids or [] if int(item) != primary_id]
    except (TypeError, ValueError) as error:
        raise DomainError("Seleção de possíveis duplicidades inválida.") from error
    duplicate_ids = list(dict.fromkeys(duplicate_ids))
    if not duplicate_ids: raise DomainError("Escolha ao menos um registro duplicado para mesclar.")
    primary = _get(conn, "disciplinas_grade", primary_id)
    if primary["formation_id"] != formation_id:
        raise DomainError("O registro principal não pertence a esta formação.", 409, "cross_formation_merge")
    marks, params = _sql_ids(duplicate_ids)
    duplicates = repo.many(conn, f"SELECT * FROM disciplinas_grade WHERE id IN {marks}", params)
    if len(duplicates) != len(duplicate_ids) or any(item["formation_id"] != formation_id for item in duplicates):
        raise DomainError("Possíveis duplicidades de outra formação não podem ser mescladas.", 409, "cross_formation_merge")
    if str(confirmation or "").strip() != primary["name"].strip():
        raise DomainError("Digite exatamente o nome do registro principal para confirmar a mesclagem.", 400, "typed_confirmation_required", details={"expected_confirmation": primary["name"]})
    all_ids = [primary_id, *duplicate_ids]
    all_marks, all_params = _sql_ids(all_ids)
    active_studies = repo.many(conn, f"SELECT id,curriculum_subject_id FROM materias_estudo WHERE curriculum_subject_id IN {all_marks} AND status IN ('active','paused') AND archived_at IS NULL", all_params)
    if len(active_studies) > 1:
        raise DomainError("Há mais de um estudo atual entre os registros escolhidos. Arquive ou encerre um deles antes de mesclar.", 409, "merge_active_study_conflict", details={"study_ids": [item["id"] for item in active_studies]})
    data = _curriculum_data(preserve or {}, primary)
    # Uma cópia datada é criada antes de redirecionar vínculos e eliminar linhas.
    backup = _create_destructive_backup(conn)
    conn.execute(f"UPDATE materias_estudo SET curriculum_subject_id=? WHERE curriculum_subject_id IN {marks}", (primary_id, *params))
    conn.execute(f"UPDATE topicos SET curriculum_subject_id=? WHERE curriculum_subject_id IN {marks}", (primary_id, *params))
    conn.execute(f"UPDATE avaliacoes SET curriculum_subject_id=? WHERE curriculum_subject_id IN {marks}", (primary_id, *params))
    conn.execute(f"UPDATE curriculum_timeline_events SET curriculum_subject_id=? WHERE curriculum_subject_id IN {marks}", (primary_id, *params))
    conn.execute(f"UPDATE curriculum_status_history SET curriculum_subject_id=? WHERE curriculum_subject_id IN {marks}", (primary_id, *params))
    conn.execute(f"DELETE FROM disciplinas_grade WHERE id IN {marks}", params)
    ordinary = {key: value for key, value in data.items() if key not in {"academic_status", "review_status", "review_priority", "review_notes"}}
    if ordinary: repo.update(conn, "disciplinas_grade", primary_id, ordinary)
    if any(key in data for key in {"academic_status", "review_status", "review_priority", "review_notes"}):
        change_curriculum_status(conn, primary_id, data, "merge", (preserve or {}).get("history_notes"))
    saved = _get(conn, "disciplinas_grade", primary_id)
    _assert_foreign_keys(conn)
    return {"primary": saved, "merged_ids": duplicate_ids, "backup": backup}


def _batch_curriculum_ids(conn, formation_id, values):
    raw_ids = values.get("ids", values.get("curriculum_ids", []))
    if not isinstance(raw_ids, list) or not raw_ids:
        raise DomainError("Selecione ao menos uma disciplina.")
    try: ids = list(dict.fromkeys(int(item) for item in raw_ids))
    except (TypeError, ValueError) as error: raise DomainError("Seleção de disciplinas inválida.") from error
    marks, params = _sql_ids(ids)
    actual = _selected_ids(conn, f"SELECT id FROM disciplinas_grade WHERE formation_id=? AND id IN {marks}", (formation_id, *params))
    if len(actual) != len(ids):
        raise DomainError("Todas as disciplinas selecionadas devem pertencer à mesma formação.", 409, "cross_formation_batch")
    return ids


def curriculum_batch_preview(conn, formation_id, values):
    _get(conn, "formacoes", formation_id)
    ids = _batch_curriculum_ids(conn, formation_id, values)
    action = values.get("action")
    dependencies = _dependency_scope(conn, ids)
    expected = f"EXCLUIR {len(ids)} DISCIPLINAS"
    return {
        "formation_id": formation_id, "ids": ids, "action": action, "affected": len(ids),
        "dependencies": dependencies, "has_dependencies": any(value["count"] for value in dependencies.values()),
        "required_confirmation": expected if action in {"destroy", "delete"} else None,
    }


def curriculum_batch(conn, formation_id, values):
    _active_formation(conn, formation_id)
    preview = curriculum_batch_preview(conn, formation_id, values)
    ids, action = preview["ids"], values.get("action")
    if action == "set_status":
        status = values.get("academic_status")
        for ident in ids: change_curriculum_status(conn, ident, {"academic_status": status}, "manual", values.get("notes"))
    elif action == "set_review":
        status = values.get("review_status")
        for ident in ids: change_curriculum_status(conn, ident, {"review_status": status, "review_priority": values.get("review_priority"), "review_notes": values.get("review_notes")}, "review", values.get("notes"))
    elif action == "archive":
        for ident in ids: archive_curriculum(conn, ident)
    elif action == "restore":
        for ident in ids: archive_curriculum(conn, ident, True)
    elif action == "classify":
        item_type = values.get("item_type")
        if item_type not in ITEM_TYPES: raise DomainError("Tipo de item curricular inválido.")
        for ident in ids: update_curriculum(conn, ident, {"item_type": item_type})
    elif action in {"destroy", "delete"}:
        expected = preview["required_confirmation"]
        if str(values.get("confirmation") or "").strip() != expected:
            raise DomainError("Digite a confirmação exibida para excluir as disciplinas selecionadas.", 400, "typed_confirmation_required", details={"expected_confirmation": expected})
        if preview["has_dependencies"] and not _confirmed(values.get("include_dependencies")):
            raise DomainError("Confirme a exclusão dos dados dependentes exibidos na prévia.", 400, "dependency_confirmation_required")
        backup = _create_destructive_backup(conn)
        _delete_curriculum_graph(conn, ids)
        marks, params = _sql_ids(ids)
        conn.execute(f"DELETE FROM curriculum_status_history WHERE curriculum_subject_id IN {marks}", params)
        conn.execute(f"DELETE FROM disciplinas_grade WHERE id IN {marks}", params)
        _assert_foreign_keys(conn)
        preview["backup"] = backup
    else:
        raise DomainError("Ação em lote inválida.")
    return {"affected": len(ids), "action": action, "preview": preview, "summary": _curriculum_summary(conn, formation_id)}


def _study_formation_id(study, curriculum_item=None):
    return study["related_formation_id"] or (curriculum_item or {}).get("formation_id")


def _active_shared_context(conn, study_id):
    """Ocorrências acadêmicas que ainda autorizam um estudo canônico.

    A disciplina de origem pode ter sido arquivada sem que o estudo pessoal
    compartilhado deixe de ser válido na outra formação. Esta consulta pequena
    mantém essa regra em um único lugar para Foco, Estudos atuais e o
    planejador não discordarem.
    """
    context = _canonical(lambda: canonical_links.planning_contexts(conn, [study_id])).get(study_id, {})
    return [entry for entry in context.get("linked_subjects", []) if entry.get("planning_active")]


def _assert_study_accessible(conn, ident, require_current=False, *, intent=None):
    """Valida os pais do estudo e a permissão acadêmica da ação.

    O estado acadêmico pertence à disciplina curricular, não ao navegador. Ao
    centralizar esta regra, um link antigo ou uma chamada direta da API não
    consegue criar foco/bloco para matéria bloqueada, futura ou dispensada.
    ``intent='review'`` é a única exceção para disciplina já concluída.
    """
    study = _get(conn, "materias_estudo", ident)
    if study["archived_at"] or study["status"] == "archived":
        raise DomainError("Este estudo está arquivado. Restaure-o antes de iniciar o foco.", 409, "study_archived")
    curriculum_item = _get(conn, "disciplinas_grade", study["curriculum_subject_id"]) if study["curriculum_subject_id"] else None
    active_shared = _active_shared_context(conn, ident) if curriculum_item else []
    has_active_shared = bool(active_shared)
    if curriculum_item and curriculum_item["archived_at"] and not has_active_shared:
        raise DomainError("A disciplina deste estudo está arquivada. Restaure-a antes de iniciar o foco.", 409, "archived_parent")
    if curriculum_item and intent:
        academic_status = curriculum_item.get("academic_status")
        if academic_status in {"not_available", "locked", "exempted", "failed"} and not has_active_shared:
            raise DomainError(
                "Esta disciplina não está academicamente liberada para estudo, foco ou planejamento.",
                409,
                "curriculum_not_studyable",
                details={"academic_status": academic_status, "intent": intent},
            )
        if academic_status == "completed" and intent != "review" and not has_active_shared:
            raise DomainError(
                "Disciplina concluída só pode receber registros de revisão.",
                409,
                "curriculum_completed_review_only",
                details={"academic_status": academic_status, "intent": intent},
            )
    formation_id = _study_formation_id(study, curriculum_item)
    if formation_id and _get(conn, "formacoes", formation_id)["archived_at"] and not has_active_shared:
        raise DomainError("A formação deste estudo está arquivada. Restaure-a antes de iniciar o foco.", 409, "archived_parent")
    if require_current and study["status"] not in {"active", "paused"}:
        raise DomainError("Este estudo não está nos estudos atuais.", 409, "study_not_current")
    return study


def studies(conn, include_archived=False, week_reference=None, visibility=None, formation_id=None, q=None, review=None):
    """Lista estudos respeitando o arquivamento próprio e de seus pais.

    ``include_archived`` permanece aceito para a interface anterior; os filtros
    novos usam ``visibility`` e nunca fazem um estudo ativo sob pai arquivado
    parecer atual.
    """
    week_start, week_end = _week_bounds(week_reference)
    if visibility is None:
        visibility = "all" if include_archived else "active"
    if visibility not in {"active", "paused", "review", "completed", "archived", "all"}:
        raise DomainError("Filtro de estudos inválido.")
    shared_parent_active = """EXISTS (
        SELECT 1
        FROM curriculum_study_links sl
        JOIN disciplinas_grade sd ON sd.id=sl.curriculum_subject_id
        JOIN formacoes sf ON sf.id=sd.formation_id
        WHERE sl.canonical_study_id=s.id
          AND sd.archived_at IS NULL AND sf.archived_at IS NULL AND sf.status='active'
          AND sd.academic_status IN ('available','in_progress')
    )"""
    primary_parent_active = "(d.id IS NULL OR (d.archived_at IS NULL AND (f.id IS NULL OR (f.archived_at IS NULL AND f.status='active'))))"
    parent_active = f"s.archived_at IS NULL AND s.status<>'archived' AND ({primary_parent_active} OR {shared_parent_active})"
    clauses, params = [], []
    if visibility == "active": clauses.append(parent_active + " AND s.status='active'")
    elif visibility == "paused": clauses.append(parent_active + " AND s.status='paused'")
    elif visibility == "review": clauses.append(parent_active + " AND d.review_status IN ('queued','in_progress')")
    elif visibility == "completed": clauses.append(parent_active + " AND s.status='completed'")
    elif visibility == "archived": clauses.append(
        f"s.archived_at IS NOT NULL OR s.status='archived' OR ((d.archived_at IS NOT NULL OR f.archived_at IS NOT NULL) AND NOT {shared_parent_active})"
    )
    if formation_id not in (None, ""):
        try: selected_formation = int(formation_id)
        except (TypeError, ValueError) as error: raise DomainError("Formação do filtro é inválida.") from error
        clauses.append(
            "(COALESCE(s.related_formation_id,d.formation_id)=? OR EXISTS ("
            "SELECT 1 FROM curriculum_study_links sl JOIN disciplinas_grade sd ON sd.id=sl.curriculum_subject_id "
            "WHERE sl.canonical_study_id=s.id AND sd.formation_id=?))"
        )
        params.extend((selected_formation, selected_formation))
    if q and str(q).strip():
        clauses.append("COALESCE(d.name,s.personal_name) LIKE ? COLLATE NOCASE"); params.append(f"%{str(q).strip()}%")
    if review:
        if review not in REVIEW_STATUSES: raise DomainError("Filtro de revisão inválido.")
        clauses.append("COALESCE(d.review_status,'none')=?"); params.append(review)
    where = (" WHERE " + " AND ".join(f"({clause})" for clause in clauses)) if clauses else ""
    sql = """
        SELECT s.*, COALESCE(d.name,s.personal_name) name, f.name formation_name,
          d.academic_status, d.review_status, d.item_type, d.archived_at curriculum_archived_at,
          d.start_date curriculum_start_date,d.end_date curriculum_end_date,d.deadline_date,
          d.required_study_minutes curriculum_required_study_minutes,d.priority_base,
          d.preferred_block_minutes curriculum_preferred_block_minutes,d.allowed_weekdays curriculum_allowed_weekdays,
          f.archived_at formation_archived_at,
          CASE WHEN s.archived_at IS NOT NULL OR s.status='archived' THEN 'study_archived'
               WHEN d.archived_at IS NOT NULL THEN 'curriculum_archived'
               WHEN f.archived_at IS NOT NULL THEN 'formation_archived'
               ELSE NULL END visibility_reason,
          COALESCE((SELECT ROUND(AVG(t.mastery),1) FROM topicos t WHERE (t.study_subject_id=s.id OR (d.id IS NOT NULL AND t.curriculum_subject_id=d.id)) AND t.archived_at IS NULL),0) mastery_average,
          (SELECT COUNT(*) FROM topicos t WHERE (t.study_subject_id=s.id OR (d.id IS NOT NULL AND t.curriculum_subject_id=d.id)) AND t.archived_at IS NULL AND t.status<>'completed') pending_topics,
          (SELECT COUNT(*) FROM topicos t WHERE (t.study_subject_id=s.id OR (d.id IS NOT NULL AND t.curriculum_subject_id=d.id)) AND t.archived_at IS NULL) topic_count,
          (SELECT COUNT(*) FROM topicos t WHERE (t.study_subject_id=s.id OR (d.id IS NOT NULL AND t.curriculum_subject_id=d.id)) AND t.archived_at IS NULL AND t.status='completed') completed_topics,
          COALESCE((SELECT SUM(x.duration_seconds) FROM sessoes_estudo x WHERE x.study_subject_id=s.id AND x.date BETWEEN ? AND ?),0) week_seconds,
          COALESCE((SELECT SUM(p.planned_duration_minutes) FROM sessoes_planejadas p WHERE p.study_subject_id=s.id AND p.status='planned' AND p.scheduled_date BETWEEN ? AND ?),0) planned_week_minutes
        FROM materias_estudo s
        LEFT JOIN disciplinas_grade d ON d.id=s.curriculum_subject_id
        LEFT JOIN formacoes f ON f.id=COALESCE(s.related_formation_id,d.formation_id)
    """ + where + " ORDER BY s.favorite DESC,s.priority DESC,s.created_at DESC"
    values = repo.many(conn, sql, (week_start.isoformat(), week_end.isoformat(), week_start.isoformat(), week_end.isoformat(), *params))
    shared_contexts = _canonical(lambda: canonical_links.planning_contexts(conn, [value["id"] for value in values]))
    for value in values:
        context = shared_contexts.get(value["id"], {})
        if context.get("linked_subjects") and any(item.get("planning_active") for item in context["linked_subjects"]):
            # A origem pode estar arquivada, mas o mesmo estudo continua atual
            # porque outra ocorrência vinculada permanece ativa.
            if value.get("visibility_reason") in {"curriculum_archived", "formation_archived"}:
                value["visibility_reason"] = None
        value["progress_percent"] = round(value["completed_topics"] * 100 / value["topic_count"]) if value["topic_count"] else 0
        value["visibility_reason_label"] = {
            "study_archived": "Estudo arquivado", "curriculum_archived": "Disciplina arquivada",
            "formation_archived": "Formação arquivada",
        }.get(value["visibility_reason"])
        value["canonical_study_id"] = value["id"]
        value["shared_curriculum_subjects"] = context.get("linked_subjects", [])
        value["shared_formation_names"] = context.get("formation_names", [])
        value["is_shared_study"] = len(context.get("linked_subjects", [])) > 1
    return values


def _provisional_effort_minutes(conn, curriculum_item):
    """Estimativa inicial explicável para uma disciplina recém-iniciada.

    A carga institucional é o melhor indício disponível. Sem ela, usam-se as
    estimativas de tópicos já cadastrados; se elas também não existirem, o
    sistema assume 10 h apenas como perfil provisório — nunca como dado
    acadêmico definitivo.
    """
    workload = int(curriculum_item.get("workload_minutes") or 0)
    if workload > 0:
        return workload, "carga curricular"
    topic_total = repo.one(
        conn,
        "SELECT COALESCE(SUM(estimated_minutes),0) minutes FROM topicos "
        "WHERE curriculum_subject_id=? AND archived_at IS NULL",
        (curriculum_item["id"],),
    )
    if topic_total and int(topic_total["minutes"] or 0) > 0:
        return int(topic_total["minutes"]), "estimativa dos tópicos"
    configured = _nonnegative_setting_minutes(settings(conn), "provisional_effort_minutes")
    return configured or 10 * 60, "estimativa inicial de 10 h"


def _provisional_deadline(conn, start_day):
    configured = _nonnegative_setting_minutes(settings(conn), "provisional_deadline_days")
    # O horizonte não tenta fingir que é uma data acadêmica. Ele apenas torna a
    # disciplina visível e planejável até o usuário confirmar o prazo real.
    days = configured or 56
    return start_day + timedelta(days=max(1, days))


def _start_curriculum_profile(conn, curriculum_item, values):
    """Monta o perfil canônico sem gravar nada.

    O formulário compacto pode usar aliases antigos (`target_date`, `priority`)
    sem que a interface precise conhecer a tabela de origem. Valores existentes
    sempre vencem a estimativa automática, a menos que o usuário envie uma
    alteração explícita.
    """
    schedule_values = dict(values or {})
    if "target_date" in schedule_values and "deadline_date" not in schedule_values:
        schedule_values["deadline_date"] = schedule_values["target_date"]
    if "priority" in schedule_values and "priority_base" not in schedule_values:
        schedule_values["priority_base"] = schedule_values["priority"]
    candidate_data = _curriculum_data(schedule_values, curriculum_item)
    start_value = candidate_data.get("start_date", curriculum_item.get("start_date")) or _today()
    start_day = _date(start_value, "Data de início")

    effort_mode = str(schedule_values.get("effort_mode") or schedule_values.get("effort_source") or "automatic").strip().lower()
    aliases = {
        "manual": "manual", "personal": "manual", "workload": "workload",
        "carga": "workload", "automatic": "automatic", "auto": "automatic",
    }
    if effort_mode not in aliases:
        raise DomainError("Modo de estimativa de esforço inválido.")
    effort_mode = aliases[effort_mode]

    explicit_effort = candidate_data.get("required_study_minutes") if "required_study_minutes" in candidate_data else None
    existing_effort = curriculum_item.get("required_study_minutes")
    effort_note = None
    if explicit_effort is not None:
        effort = int(explicit_effort)
        effort_provisional = bool(candidate_data.get("effort_is_provisional", False))
    elif existing_effort:
        effort = int(existing_effort)
        effort_provisional = bool(curriculum_item.get("effort_is_provisional"))
    elif effort_mode == "manual":
        raise DomainError("Informe o esforço pessoal para usar a estimativa manual.", 400, "manual_effort_required")
    elif effort_mode == "workload" and int(candidate_data.get("workload_minutes") or curriculum_item.get("workload_minutes") or 0) > 0:
        effort = int(candidate_data.get("workload_minutes") or curriculum_item.get("workload_minutes"))
        effort_provisional, effort_note = True, "carga curricular"
    else:
        effort, effort_note = _provisional_effort_minutes(conn, {**curriculum_item, **candidate_data})
        effort_provisional = True

    explicit_deadline = candidate_data.get("deadline_date") if "deadline_date" in candidate_data else None
    existing_deadline = curriculum_item.get("deadline_date") or curriculum_item.get("end_date")
    if explicit_deadline:
        deadline_day = _date(explicit_deadline, "Prazo")
        deadline_provisional = bool(candidate_data.get("deadline_is_provisional", False))
    elif existing_deadline:
        deadline_day = _date(existing_deadline, "Prazo")
        deadline_provisional = bool(curriculum_item.get("deadline_is_provisional"))
    else:
        deadline_day = _provisional_deadline(conn, start_day)
        deadline_provisional = True
    if deadline_day < start_day:
        raise DomainError("O prazo não pode ser anterior à data de início.")

    profile = {
        "start_date": start_day.isoformat(),
        "deadline_date": deadline_day.isoformat(),
        "required_study_minutes": effort,
        "priority_base": int(candidate_data.get("priority_base", curriculum_item.get("priority_base") or 3)),
        "preferred_block_minutes": candidate_data.get("preferred_block_minutes", curriculum_item.get("preferred_block_minutes")) or planning_preferences(conn)["default_session_minutes"],
        "allowed_weekdays": candidate_data.get("allowed_weekdays", curriculum_item.get("allowed_weekdays")),
        "planning_enabled": 1,
        "planning_opt_out": 0,
        "effort_is_provisional": 1 if effort_provisional else 0,
        "deadline_is_provisional": 1 if deadline_provisional else 0,
        "planning_profile_configured_at": _now(),
    }
    # Campos institucionais só são alterados quando foram enviados; esforço e
    # prazo pertencem ao perfil pessoal de planejamento acima.
    for key in ("workload_minutes", "end_date", "minimum_grade", "notes", "code", "period"):
        if key in candidate_data:
            profile[key] = candidate_data[key]
    return profile, {
        "effort_mode": effort_mode,
        "effort_is_provisional": bool(profile["effort_is_provisional"]),
        "deadline_is_provisional": bool(profile["deadline_is_provisional"]),
        "effort_basis": effort_note or "valor já salvo",
        "deadline_label": "Prazo ainda não definido — horizonte provisório aplicado" if deadline_provisional else "Prazo informado",
    }


def start_curriculum_study(conn, curriculum_id, values=None):
    """Inicia uma disciplina em uma única transação, inclusive se ela era futura.

    Esta é a porta oficial para o fluxo Grade → Estudos atuais → Planejamento.
    Um SAVEPOINT torna a função atômica também para integrações que a chamam
    diretamente, fora do wrapper HTTP da aplicação.
    """
    values = values or {}
    conn.execute("SAVEPOINT start_curriculum_study")
    try:
        curriculum_item = _get(conn, "disciplinas_grade", curriculum_id)
        _active_formation(conn, curriculum_item["formation_id"])
        if curriculum_item["archived_at"]:
            raise DomainError("Restaure a disciplina antes de iniciá-la.", 409, "curriculum_archived")
        if curriculum_item["item_type"] != "subject":
            raise DomainError("Uma linha estrutural não pode ser iniciada como disciplina.", 409, "curriculum_section")
        if curriculum_item["academic_status"] in {"locked", "exempted", "completed"}:
            raise DomainError("Esta disciplina não pode ser iniciada no estado acadêmico atual.", 409, "curriculum_not_startable")

        profile, profile_info = _start_curriculum_profile(conn, curriculum_item, values)
        previous = dict(curriculum_item)
        profile["academic_status"] = "in_progress"
        repo.update(conn, "disciplinas_grade", curriculum_id, profile)
        saved_curriculum = _get(conn, "disciplinas_grade", curriculum_id)
        # A tabela de histórico preserva um conjunto fechado de origens já
        # existente. O evento abaixo mantém o detalhe de "início" sem tentar
        # ampliar esse enum por uma migração incompatível.
        _record_curriculum_status(conn, previous, saved_curriculum, "manual", "Disciplina iniciada com perfil de planejamento")
        _event(conn, curriculum_id, "schedule_settings", "Perfil de planejamento iniciado", json.dumps(profile_info, ensure_ascii=False))

        shared_link = _canonical(lambda: canonical_links.canonical_study_for_subject(conn, curriculum_id))
        current = shared_link["study"] if shared_link and shared_link.get("kind") == "linked" else repo.one(
            conn,
            "SELECT * FROM materias_estudo WHERE curriculum_subject_id=? AND status IN ('active','paused') AND archived_at IS NULL ORDER BY id LIMIT 1",
            (curriculum_id,),
        )
        created = False
        if current:
            if not shared_link and current["status"] == "paused" and values.get("keep_paused") not in (True, "true", "1", 1):
                repo.update(conn, "materias_estudo", current["id"], {"status": "active"})
            study = _get(conn, "materias_estudo", current["id"])
        else:
            study_values = _study_data(values)
            study_values = {
                "origin": "curriculum", "curriculum_subject_id": curriculum_id,
                "priority": int(study_values.get("priority", saved_curriculum.get("priority_base") or 3)),
                "difficulty": int(study_values.get("difficulty", 3)),
                "weekly_goal_minutes": study_values.get("weekly_goal_minutes"),
                "start_date": profile["start_date"], "target_date": profile["deadline_date"],
                "status": "active", "academic_period": study_values.get("academic_period"),
            }
            study = _get(conn, "materias_estudo", repo.insert(conn, "materias_estudo", study_values))
            created = True

        first_topic_id = values.get("first_topic_id") or values.get("topic_id")
        if first_topic_id not in (None, ""):
            topic = _get(conn, "topicos", int(first_topic_id))
            if topic.get("archived_at") or topic.get("curriculum_subject_id") != curriculum_id:
                raise DomainError("O primeiro tópico precisa pertencer à disciplina e estar ativo.", 409, "start_topic_invalid")
            if topic.get("status") == "not_started":
                repo.update(conn, "topicos", topic["id"], {"status": "in_progress", "started_at": _today()})

        planning = planning_items(conn, profile["start_date"], profile["deadline_date"], item_id=study["id"])["items"]
        planning_item = next((item for item in planning if item["study_subject_id"] == study["id"]), None)
        notices = []
        if profile_info["effort_is_provisional"]:
            notices.append(f"Esforço provisório de {profile['required_study_minutes']} min criado a partir de {profile_info['effort_basis']}.")
        if profile_info["deadline_is_provisional"]:
            notices.append(f"Prazo provisório aplicado até {profile['deadline_date']}; confirme a data acadêmica quando souber.")
        conn.execute("RELEASE SAVEPOINT start_curriculum_study")
        return {
            "curriculum": saved_curriculum, "study": study, "created": created, "reused": not created,
            "profile": {**profile_info, **{key: profile[key] for key in ("start_date", "deadline_date", "required_study_minutes", "preferred_block_minutes", "allowed_weekdays", "priority_base")}},
            "planning_item": planning_item, "notices": notices,
            "shared_study": shared_link if shared_link and shared_link.get("kind") == "linked" else None,
        }
    except Exception:
        conn.execute("ROLLBACK TO SAVEPOINT start_curriculum_study")
        conn.execute("RELEASE SAVEPOINT start_curriculum_study")
        raise


def add_curriculum_study(conn, curriculum_id, values):
    curriculum_item = _get(conn, "disciplinas_grade", curriculum_id)
    _active_formation(conn, curriculum_item["formation_id"])
    if curriculum_item["archived_at"]:
        raise DomainError("Restaure a disciplina antes de adicioná-la aos estudos atuais.", 409, "curriculum_archived")
    if curriculum_item["item_type"] != "subject":
        raise DomainError("Uma linha estrutural não pode ser adicionada aos estudos atuais.", 409, "curriculum_section")
    linked = _canonical(lambda: canonical_links.canonical_study_for_subject(conn, curriculum_id))
    if linked and linked.get("kind") == "linked":
        # A ocorrência acadêmica entra em andamento, mas a demanda continua no
        # único estudo canônico; nunca criamos uma cópia silenciosa.
        return start_curriculum_study(conn, curriculum_id, values)["study"]
    if curriculum_item["academic_status"] == "not_available":
        # Compatibilidade para clientes antigos: o botão anterior passa a abrir
        # o mesmo fluxo atômico em vez de obrigar uma edição de estado separada.
        return start_curriculum_study(conn, curriculum_id, values)["study"]
    if curriculum_item["academic_status"] not in ("available", "in_progress"): raise DomainError("A disciplina precisa estar disponível para entrar nos estudos atuais.")
    canonical_map = {
        "required_study_minutes": "required_study_minutes",
        "priority": "priority_base",
        "preferred_block_minutes": "preferred_block_minutes",
        "allowed_weekdays": "allowed_weekdays",
        "start_date": "start_date",
        "target_date": "deadline_date",
        "planning_enabled": "planning_enabled",
    }
    canonical_values = {target: values[source] for source, target in canonical_map.items() if source in values}
    canonical_values.setdefault("planning_enabled", 1)
    if canonical_values:
        curriculum_item = update_curriculum(conn, curriculum_id, canonical_values)
    data = _study_data(values)
    for key in canonical_map:
        data.pop(key, None)
    data.update({
        "origin": "curriculum", "curriculum_subject_id": curriculum_id,
        "priority": data.get("priority", curriculum_item.get("priority_base", 3)),
        "difficulty": data.get("difficulty", 3), "status": "active",
        "target_date": data.get("target_date") or curriculum_item.get("deadline_date") or curriculum_item.get("end_date"),
    })
    try: ident = repo.insert(conn, "materias_estudo", data)
    except sqlite3.IntegrityError as error: raise DomainError("Esta disciplina já está nos estudos atuais.", 409) from error
    # A configuração de esforço/prazo da disciplina é canônica; o estudo atual
    # guarda somente o estado operacional e preferências próprias.
    change_curriculum_status(conn, curriculum_id, {"academic_status":"in_progress"}, "manual")
    return _get(conn, "materias_estudo", ident)


def set_curriculum_review(conn, ident, values):
    current = _get(conn, "disciplinas_grade", ident)
    review_status = values.get("status", values.get("review_status"))
    if review_status not in REVIEW_STATUSES:
        raise DomainError("Status de revisão inválido.")
    review_values = {"review_status": review_status}
    if review_status == "none":
        # Desmarcar revisão remove a fila e seus metadados, mas não altera o
        # resultado acadêmico que a disciplina já possuía.
        repo.update(conn, "disciplinas_grade", ident, {"review_priority": None, "review_notes": None})
    else:
        review_values.update({
            "review_priority": values.get("priority", values.get("review_priority")),
            "review_notes": values.get("notes", values.get("review_notes")),
        })
    updated = change_curriculum_status(conn, ident, review_values, "review", values.get("history_notes"))
    if _confirmed(values.get("start_study")):
        study = start_curriculum_review(conn, ident, values)
        updated["study"] = study
    return updated


def start_curriculum_review(conn, curriculum_id, values=None):
    curriculum_item = _get(conn, "disciplinas_grade", curriculum_id)
    _active_formation(conn, curriculum_item["formation_id"])
    if curriculum_item["archived_at"]:
        raise DomainError("Restaure a disciplina antes de iniciar uma revisão.", 409, "curriculum_archived")
    if curriculum_item["item_type"] != "subject":
        raise DomainError("Uma linha estrutural não pode ser revisada.", 409, "curriculum_section")
    values = values or {}
    change_curriculum_status(conn, curriculum_id, {"review_status": "in_progress"}, "review")
    current = repo.one(conn, "SELECT * FROM materias_estudo WHERE curriculum_subject_id=? AND status IN ('active','paused') AND archived_at IS NULL", (curriculum_id,))
    if current:
        return current
    # Uma revisão não é uma nova matrícula: preservar academic_status é crucial.
    try:
        ident = repo.insert(conn, "materias_estudo", {
            "origin": "curriculum", "curriculum_subject_id": curriculum_id,
            "priority": values.get("priority", 3), "difficulty": values.get("difficulty", 3),
            "weekly_goal_minutes": values.get("weekly_goal_minutes"), "start_date": values.get("start_date") or _today(),
            "target_date": values.get("target_date"), "status": "active", "academic_period": values.get("academic_period"),
        })
    except sqlite3.IntegrityError as error:
        raise DomainError("Já existe um estudo atual para esta disciplina.", 409, "study_already_current") from error
    return _get(conn, "materias_estudo", ident)


def _study_data(values, current=None, include_identity=False):
    allowed = STUDY | ({"related_formation_id", "personal_name"} if include_identity else set())
    data = _fields(values, allowed)
    for key in ("start_date", "target_date", "academic_period", "allowed_weekdays", "personal_name", "related_formation_id"):
        if data.get(key) == "":
            data[key] = None
    candidate = {**(current or {}), **data}
    for key, label in (("required_study_minutes", "Esforço total"), ("minimum_weekly_minutes", "Mínimo semanal"), ("weekly_goal_minutes", "Meta semanal")):
        if key in data:
            data[key] = _optional_minutes(data[key], label)
    if "preferred_block_minutes" in data:
        data["preferred_block_minutes"] = _optional_block_minutes(data["preferred_block_minutes"])
    if "allowed_weekdays" in data:
        data["allowed_weekdays"] = _weekdays_json(data["allowed_weekdays"]) if data["allowed_weekdays"] is not None else None
    for key, label in (("priority", "Prioridade"), ("difficulty", "Dificuldade")):
        if key in data and data[key] not in (None, ""):
            try:
                value = int(data[key])
            except (TypeError, ValueError) as error:
                raise DomainError(f"{label} deve estar entre 1 e 5.") from error
            if not 1 <= value <= 5:
                raise DomainError(f"{label} deve estar entre 1 e 5.")
            data[key] = value
    start, target = candidate.get("start_date"), candidate.get("target_date")
    if start:
        _date(start, "Data de início")
    if target:
        _date(target, "Prazo")
    if start and target and start > target:
        raise DomainError("O prazo não pode ser anterior à data de início.")
    return data


def create_personal_study(conn, values):
    data = _study_data(values, include_identity=True)
    if data.get("related_formation_id"):
        _active_formation(conn, int(data["related_formation_id"]))
    data.update({"origin":"personal", "personal_name":_need(data.get("personal_name"), "Nome do estudo"), "priority":data.get("priority",3), "difficulty":data.get("difficulty",3), "status":"active"})
    return _get(conn, "materias_estudo", repo.insert(conn, "materias_estudo", data))


def update_study(conn, ident, values):
    study = _get(conn, "materias_estudo", ident); data = _study_data(values, study, include_identity=True)
    if study["archived_at"] or study["status"] == "archived":
        raise DomainError("Restaure o estudo antes de editá-lo.", 409, "study_archived")
    if data.get("status") == "archived":
        raise DomainError("Use a ação Arquivar para arquivar um estudo.", 400, "use_archive_action")
    if study["origin"] == "curriculum" and data.get("status") == "completed":
        raise DomainError("Use a ação Finalizar para encerrar um estudo curricular.", 400, "use_finish_action")
    if study["origin"] == "curriculum":
        # Não mantém uma cópia divergente do esforço, prazo ou dias permitidos
        # no Estudo atual. A grade curricular é a fonte oficial desses campos.
        canonical_map = {
            "required_study_minutes": "required_study_minutes",
            "priority": "priority_base",
            "preferred_block_minutes": "preferred_block_minutes",
            "allowed_weekdays": "allowed_weekdays",
            "start_date": "start_date",
            "target_date": "deadline_date",
            "planning_enabled": "planning_enabled",
        }
        canonical = {target: data.pop(source) for source, target in canonical_map.items() if source in data}
        if canonical:
            update_curriculum(conn, study["curriculum_subject_id"], canonical)
        data.pop("personal_name", None); data.pop("related_formation_id", None)
    elif data.get("related_formation_id"):
        _active_formation(conn, int(data["related_formation_id"]))
    repo.update(conn, "materias_estudo", ident, data); return _get(conn, "materias_estudo", ident)


def finish_study(conn, ident, result, final_score=None):
    study = _get(conn, "materias_estudo", ident)
    statuses = {"approved":"completed", "failed":"failed", "withdrawn":"available", "exempted":"exempted"}
    if study["origin"] != "curriculum" or result not in statuses: raise DomainError("Resultado acadêmico inválido.")
    _assert_study_accessible(conn, ident)
    repo.update(conn, "materias_estudo", ident, {"status":"completed", "completed_at":_today(), "result":result, "final_score":final_score})
    change_curriculum_status(conn, study["curriculum_subject_id"], {"academic_status":statuses[result]}, "finish_study", result)
    return _get(conn, "materias_estudo", ident)


def pause_study(conn, ident, resume=False):
    study = _assert_study_accessible(conn, ident)
    if resume:
        if study["status"] != "paused": raise DomainError("Somente um estudo pausado pode continuar.", 409, "study_not_paused")
        status = "active"
    else:
        if study["status"] != "active": raise DomainError("Somente um estudo ativo pode ser pausado.", 409, "study_not_active")
        status = "paused"
    repo.update(conn, "materias_estudo", ident, {"status": status})
    return _get(conn, "materias_estudo", ident)


def remove_current_study(conn, ident, resolution="available", cancel_future_blocks=True):
    study = _get(conn, "materias_estudo", ident)
    if study["origin"] != "curriculum":
        raise DomainError("Remover dos estudos atuais é uma ação exclusiva de uma disciplina curricular.", 400, "not_curriculum_study")
    if study["status"] not in {"active", "paused"} or study["archived_at"]:
        raise DomainError("Este estudo já não está nos estudos atuais.", 409, "study_not_current")
    resolution = {"in_progress": "keep_in_progress"}.get(resolution, resolution)
    resolutions = {
        "available": "available", "keep_in_progress": "in_progress", "approved": "completed",
        "failed": "failed", "withdrawn": "available", "exempted": "exempted",
    }
    if resolution not in resolutions:
        raise DomainError("Resultado para encerrar o estudo é inválido.")
    current = _get(conn, "disciplinas_grade", study["curriculum_subject_id"])
    _active_formation(conn, current["formation_id"])
    if current["archived_at"]:
        raise DomainError("Restaure a disciplina antes de encerrar o estudo.", 409, "curriculum_archived")
    _archive_study_row(conn, ident, "removed_current")
    if resolution in {"approved", "failed", "withdrawn", "exempted"}:
        repo.update(conn, "materias_estudo", ident, {"result": resolution, "completed_at": _today()})
    change_curriculum_status(conn, current["id"], {"academic_status": resolutions[resolution]}, "remove_current", resolution)
    cancelled = _cancel_future_planned(conn, [ident]) if _confirmed(cancel_future_blocks) else {"count": 0, "ids": []}
    return {"study": _get(conn, "materias_estudo", ident), "academic_status": resolutions[resolution], "cancelled_future_blocks": cancelled}


def new_academic_attempt(conn, ident, values=None):
    previous = _get(conn, "materias_estudo", ident)
    if previous["origin"] != "curriculum" or previous["result"] not in ("failed", "withdrawn"):
        raise DomainError("Uma nova tentativa só está disponível após reprovação ou retirada.", 409)
    _assert_study_accessible(conn, ident)
    curriculum_id = previous["curriculum_subject_id"]
    maximum = repo.one(conn, "SELECT MAX(attempt_number) attempt FROM materias_estudo WHERE curriculum_subject_id=?", (curriculum_id,))
    copied = {"origin":"curriculum", "curriculum_subject_id":curriculum_id, "priority":previous["priority"], "difficulty":previous["difficulty"], "weekly_goal_minutes":previous["weekly_goal_minutes"], "start_date":(values or {}).get("start_date") or _today(), "target_date":(values or {}).get("target_date"), "status":"active", "academic_period":(values or {}).get("academic_period") or previous["academic_period"], "attempt_number":int(maximum["attempt"] or 0) + 1}
    created = _get(conn, "materias_estudo", repo.insert(conn, "materias_estudo", copied))
    change_curriculum_status(conn, curriculum_id, {"academic_status":"in_progress"}, "new_attempt")
    return created


def _topic_owner(conn, topic):
    """Retorna a fonte de esforço compartilhada por um tópico.

    Tópicos curriculares pertencem à disciplina, mesmo quando também carregam
    o vínculo legado com um estudo atual. Tópicos pessoais pertencem ao estudo.
    Isso impede que as estimativas virem uma segunda carga de trabalho.
    """
    curriculum_id = topic.get("curriculum_subject_id")
    if curriculum_id:
        return "curriculum", int(curriculum_id)
    study_id = topic.get("study_subject_id")
    if not study_id:
        raise DomainError("O tópico não possui uma disciplina ou estudo de origem.", 409, "topic_without_owner")
    return "study", int(study_id)


def _topic_owner_topics(conn, owner_kind, owner_id, include_archived=False):
    if owner_kind == "curriculum":
        clause, params = "t.curriculum_subject_id=?", (owner_id,)
    elif owner_kind == "study":
        clause, params = "t.study_subject_id=? AND t.curriculum_subject_id IS NULL", (owner_id,)
    else:
        raise DomainError("Origem do tópico inválida.")
    archived = "" if include_archived else " AND t.archived_at IS NULL"
    return repo.many(conn, "SELECT t.* FROM topicos t WHERE " + clause + archived + " ORDER BY t.sort_order,t.id", params)


def _topic_owner_total(conn, owner_kind, owner_id):
    if owner_kind == "curriculum":
        return _get(conn, "disciplinas_grade", owner_id).get("required_study_minutes")
    return _get(conn, "materias_estudo", owner_id).get("required_study_minutes")


def _topic_dependencies_map(conn, topic_ids):
    if not topic_ids:
        return {}
    marks, params = _sql_ids(topic_ids)
    rows = repo.many(conn, f"SELECT topic_id,prerequisite_topic_id FROM topic_dependencies WHERE topic_id IN {marks}", params)
    values = defaultdict(list)
    for row in rows:
        values[row["topic_id"]].append(row["prerequisite_topic_id"])
    return {ident: sorted(items) for ident, items in values.items()}


def _topic_metrics_rows(conn, rows, *, future_start=None, future_end=None):
    """Anexa métricas derivadas sem persistir cópias no frontend.

    Tempo real vem exclusivamente de ``sessoes_estudo`` e cobertura futura de
    ``sessoes_planejadas``. As estimativas continuam sendo uma repartição do
    esforço total do dono, não uma nova demanda acumulada.
    """
    if not rows:
        return []
    topic_ids = [row["id"] for row in rows]
    marks, params = _sql_ids(topic_ids)
    real_rows = repo.many(conn, f"SELECT topic_id,COALESCE(SUM(duration_seconds),0)/60 minutes,COUNT(*) session_count,MAX(date) last_activity FROM sessoes_estudo WHERE topic_id IN {marks} GROUP BY topic_id", params)
    planned_clause = f"topic_id IN {marks} AND status='planned' AND scheduled_date>=?"
    planned_params = [*params, future_start or _today()]
    if future_end:
        planned_clause += " AND scheduled_date<=?"
        planned_params.append(future_end)
    planned_rows = repo.many(conn, "SELECT topic_id,COALESCE(SUM(planned_duration_minutes),0) minutes FROM sessoes_planejadas WHERE " + planned_clause + " GROUP BY topic_id", planned_params)
    review_rows = repo.many(conn, f"SELECT topic_id,MIN(due_date) due_date,COUNT(*) count FROM revisoes WHERE topic_id IN {marks} AND status='pending' GROUP BY topic_id", params)
    evaluation_rows = repo.many(conn, f"""
        SELECT link.topic_id,MIN(COALESCE(e.delivery_date,e.date)) due_date,COUNT(*) count
        FROM avaliacao_topicos link JOIN avaliacoes e ON e.id=link.evaluation_id
        WHERE link.topic_id IN {marks} AND e.status NOT IN ('cancelled','corrected')
        GROUP BY link.topic_id
    """, params)
    real = {row["topic_id"]: row for row in real_rows}
    planned = {row["topic_id"]: int(row["minutes"] or 0) for row in planned_rows}
    reviews_by_topic = {row["topic_id"]: row for row in review_rows}
    evaluations_by_topic = {row["topic_id"]: row for row in evaluation_rows}
    dependencies = _topic_dependencies_map(conn, topic_ids)

    # Primeiro obtém a parcela explícita de cada dono. A parte não distribuída
    # recebe apenas uma sugestão proporcional/pelo peso; nada é salvo aqui.
    grouped = defaultdict(list)
    for row in rows:
        grouped[_topic_owner(conn, row)].append(row)
    suggested = {}
    for owner, owner_rows in grouped.items():
        required = _topic_owner_total(conn, *owner)
        explicit = sum(int(row.get("estimated_minutes") or 0) for row in owner_rows)
        available = max(0, int(required or 0) - explicit)
        missing = [row for row in owner_rows if not row.get("estimated_minutes")]
        total_weight = sum(int(row.get("effort_weight") or 2) for row in missing)
        for row in owner_rows:
            if row.get("estimated_minutes"):
                suggested[row["id"]] = int(row["estimated_minutes"])
            elif required and total_weight:
                # O último ajuste é feito na distribuição explícita; para a
                # visualização uma divisão arredondada é suficiente e não muda
                # o esforço salvo da disciplina.
                suggested[row["id"]] = round(available * int(row.get("effort_weight") or 2) / total_weight)
            else:
                suggested[row["id"]] = None

    values = []
    for raw in rows:
        row = dict(raw)
        metric = real.get(row["id"], {})
        estimate = int(row["estimated_minutes"] or 0) if row.get("estimated_minutes") else None
        effective_estimate = estimate if estimate is not None else suggested.get(row["id"])
        actual = int(metric.get("minutes") or 0)
        future = int(planned.get(row["id"], 0))
        remaining = max(0, int(effective_estimate or 0) - actual) if effective_estimate is not None else None
        due = reviews_by_topic.get(row["id"])
        evaluation = evaluations_by_topic.get(row["id"])
        row.update({
            "lifecycle_state": "archived" if row.get("archived_at") else row.get("status"),
            "real_minutes": actual,
            "future_planned_minutes": future,
            "session_count": int(metric.get("session_count") or 0),
            "last_activity": metric.get("last_activity") or row.get("last_session_date"),
            "prerequisite_topic_ids": dependencies.get(row["id"], []),
            "pending_review_count": int(due.get("count") or 0) if due else 0,
            "next_review_date": due.get("due_date") if due else None,
            "pending_evaluation_count": int(evaluation.get("count") or 0) if evaluation else 0,
            "next_evaluation_date": evaluation.get("due_date") if evaluation else None,
            "suggested_estimated_minutes": suggested.get(row["id"]),
            "effective_estimated_minutes": effective_estimate,
            "remaining_minutes": remaining,
            "unallocated_minutes": max(0, remaining - future) if remaining is not None else None,
            "planned_coverage_minutes": min(remaining, future) if remaining is not None else future,
            "effort_progress_percent": round(actual * 100 / effective_estimate, 1) if effective_estimate else None,
            "estimate_delta_minutes": actual - effective_estimate if effective_estimate is not None else None,
            "economy_minutes": max(0, effective_estimate - actual) if row.get("status") == "completed" and effective_estimate is not None else 0,
            "overrun_minutes": max(0, actual - effective_estimate) if effective_estimate is not None else 0,
        })
        values.append(row)
    return values


def _topic_effort_summary(conn, owner_kind, owner_id, *, future_end=None):
    owner_rows = _topic_owner_topics(conn, owner_kind, owner_id)
    rows = _topic_metrics_rows(conn, owner_rows, future_end=future_end)
    required = _topic_owner_total(conn, owner_kind, owner_id)
    distributed = sum(int(row.get("estimated_minutes") or 0) for row in rows)
    required_value = int(required) if required else None
    return {
        "owner_kind": owner_kind,
        "owner_id": int(owner_id),
        "required_study_minutes": required_value,
        "distributed_minutes": distributed,
        "undistributed_minutes": max(0, required_value - distributed) if required_value is not None else None,
        "over_distributed_minutes": max(0, distributed - required_value) if required_value is not None else 0,
        "topics": rows,
    }


def topic_effort_summary_for_curriculum(conn, curriculum_id):
    _get(conn, "disciplinas_grade", curriculum_id)
    return _topic_effort_summary(conn, "curriculum", curriculum_id)


def topic_effort_summary_for_study(conn, study_id):
    _get(conn, "materias_estudo", study_id)
    return _topic_effort_summary(conn, "study", study_id)


def _assert_topic_estimates_fit(conn, owner_kind, owner_id, *, replacing_topic_id=None, replacement_minutes=None, additional_minutes=None):
    required = _topic_owner_total(conn, owner_kind, owner_id)
    if not required:
        return
    rows = _topic_owner_topics(conn, owner_kind, owner_id)
    distributed = 0
    for row in rows:
        if replacing_topic_id and row["id"] == replacing_topic_id:
            distributed += int(replacement_minutes or 0)
        else:
            distributed += int(row.get("estimated_minutes") or 0)
    if replacing_topic_id and not any(row["id"] == replacing_topic_id for row in rows):
        distributed += int(replacement_minutes or 0)
    if additional_minutes is not None:
        distributed += int(additional_minutes or 0)
    if distributed > int(required):
        raise DomainError(
            f"As estimativas dos tópicos somariam {distributed} min, acima do esforço total de {int(required)} min.",
            409,
            "topic_effort_overflow",
            details={"required_minutes": int(required), "distributed_minutes": distributed},
        )


def _distribution_values(rows, total, mode):
    if not rows:
        return {}
    if mode == "proportional":
        weights = {row["id"]: 1 for row in rows}
    elif mode == "weight":
        weights = {row["id"]: int(row.get("effort_weight") or 2) for row in rows}
    else:
        raise DomainError("Modo de distribuição inválido.")
    weight_total = sum(weights.values())
    allocated, remainder = {}, int(total)
    for index, row in enumerate(rows):
        if index == len(rows) - 1:
            amount = remainder
        else:
            amount = int(total * weights[row["id"]] / weight_total)
            remainder -= amount
        allocated[row["id"]] = amount
    return allocated


def distribute_topic_effort(conn, owner_kind, owner_id, values):
    """Prévia/aplicação explícita da divisão do esforço entre tópicos."""
    if owner_kind not in {"curriculum", "study"}:
        raise DomainError("Origem do tópico inválida.")
    required = _topic_owner_total(conn, owner_kind, owner_id)
    if not required:
        raise DomainError("Defina o esforço pessoal total antes de distribuí-lo entre tópicos.", 409, "topic_effort_missing")
    rows = _topic_owner_topics(conn, owner_kind, owner_id)
    if not rows:
        raise DomainError("Cadastre ao menos um tópico antes de distribuir o esforço.", 409, "topic_missing")
    mode = str(values.get("mode") or "proportional")
    if mode == "manual":
        raw = values.get("estimates")
        if not isinstance(raw, dict):
            raise DomainError("A distribuição manual exige estimativas por tópico.")
        proposed = {}
        known = {row["id"] for row in rows}
        for key, value in raw.items():
            try:
                topic_id = int(key)
            except (TypeError, ValueError) as error:
                raise DomainError("Identificador de tópico inválido.") from error
            if topic_id not in known:
                raise DomainError("Um tópico informado não pertence a esta disciplina.")
            proposed[topic_id] = _optional_minutes(value, "Estimativa do tópico") or 0
        proposed = {row["id"]: proposed.get(row["id"], int(row.get("estimated_minutes") or 0)) for row in rows}
    else:
        proposed = _distribution_values(rows, int(required), mode)
    distributed = sum(proposed.values())
    if distributed > int(required):
        raise DomainError("A distribuição ultrapassa o esforço pessoal da disciplina.", 409, "topic_effort_overflow")
    result = {
        "mode": mode,
        "required_study_minutes": int(required),
        "distributed_minutes": distributed,
        "undistributed_minutes": max(0, int(required) - distributed),
        "proposed_estimates": [{"topic_id": row["id"], "name": row["name"], "estimated_minutes": proposed[row["id"]]} for row in rows],
        "applied": False,
    }
    if _confirmed(values.get("apply")):
        for row in rows:
            repo.update(conn, "topicos", row["id"], {"estimated_minutes": proposed[row["id"]] or None})
        result["applied"] = True
        result["summary"] = _topic_effort_summary(conn, owner_kind, owner_id)
    return result


def _requested_prerequisites(values):
    if "prerequisite_topic_ids" in values:
        raw = values.get("prerequisite_topic_ids")
    elif "prerequisite_topic_id" in values:
        raw = values.get("prerequisite_topic_id")
    else:
        return None
    if raw in (None, "", []):
        return []
    if isinstance(raw, str):
        raw = [item.strip() for item in raw.split(",") if item.strip()]
    if not isinstance(raw, (list, tuple, set)):
        raw = [raw]
    try:
        values = sorted({int(item) for item in raw})
    except (TypeError, ValueError) as error:
        raise DomainError("Pré-requisito de tópico inválido.") from error
    if any(item <= 0 for item in values):
        raise DomainError("Pré-requisito de tópico inválido.")
    return values


def _topics_share_owner(conn, left, right):
    return _topic_owner(conn, left) == _topic_owner(conn, right)


def _dependency_would_cycle(conn, topic_id, prerequisite_ids):
    graph = _topic_dependencies_map(conn, [row["id"] for row in repo.many(conn, "SELECT id FROM topicos")])
    graph[topic_id] = list(prerequisite_ids)
    visiting, visited = set(), set()

    def visit(current):
        if current == topic_id and visiting:
            return True
        if current in visited:
            return False
        if current in visiting:
            return False
        visiting.add(current)
        result = any(visit(next_id) for next_id in graph.get(current, []))
        visiting.remove(current)
        visited.add(current)
        return result

    return any(visit(prerequisite) for prerequisite in prerequisite_ids)


def set_topic_dependencies(conn, topic_id, values):
    requested = _requested_prerequisites(values)
    topic = _get(conn, "topicos", topic_id)
    if requested is None:
        return topic
    if topic_id in requested:
        raise DomainError("Um tópico não pode depender dele mesmo.")
    prerequisites = [_get(conn, "topicos", ident) for ident in requested]
    if any(not _topics_share_owner(conn, topic, prerequisite) for prerequisite in prerequisites):
        raise DomainError("O pré-requisito precisa pertencer à mesma disciplina ou estudo.")
    if _dependency_would_cycle(conn, topic_id, requested):
        raise DomainError("Esta dependência criaria um ciclo entre tópicos.", 409, "topic_dependency_cycle")
    conn.execute("DELETE FROM topic_dependencies WHERE topic_id=?", (topic_id,))
    for prerequisite_id in requested:
        conn.execute("INSERT INTO topic_dependencies(topic_id,prerequisite_topic_id) VALUES (?,?)", (topic_id, prerequisite_id))
    return _get(conn, "topicos", topic_id)


def reorder_topics(conn, owner_kind, owner_id, values):
    rows = _topic_owner_topics(conn, owner_kind, owner_id)
    ordered = values.get("topic_ids", values.get("ids"))
    if not isinstance(ordered, list):
        raise DomainError("Informe a nova ordem dos tópicos.")
    try:
        ids = [int(item) for item in ordered]
    except (TypeError, ValueError) as error:
        raise DomainError("A ordem dos tópicos é inválida.") from error
    known = [row["id"] for row in rows]
    if len(ids) != len(set(ids)) or set(ids) != set(known):
        raise DomainError("A nova ordem deve conter cada tópico visível exatamente uma vez.")
    for index, topic_id in enumerate(ids):
        repo.update(conn, "topicos", topic_id, {"sort_order": index})
    return _topic_effort_summary(conn, owner_kind, owner_id)


def subject_detail(conn, ident):
    study = _get(conn, "materias_estudo", ident)
    groups = repo.many(conn, "SELECT * FROM grupos_topicos WHERE study_subject_id=? AND archived_at IS NULL ORDER BY sort_order,name", (ident,))
    topics = _contents_for_study(conn, ident)
    nested = defaultdict(list)
    for topic in topics: nested[topic["group_id"]].append(topic)
    study["groups"] = [{**group, "topics":nested.pop(group["id"], [])} for group in groups]
    study["ungrouped_topics"] = nested.get(None, [])
    study["contents"] = topics
    owner = ("curriculum", study["curriculum_subject_id"]) if study.get("curriculum_subject_id") else ("study", ident)
    study["topic_effort"] = _topic_effort_summary(conn, *owner)
    return study


def create_group(conn, study_id, values):
    _get(conn, "materias_estudo", study_id)
    return _get(conn, "grupos_topicos", repo.insert(conn, "grupos_topicos", {"study_subject_id":study_id,"name":_need(values.get("name"),"Nome da unidade"),"sort_order":values.get("sort_order",0)}))


def create_topic(conn, study_id, values):
    _get(conn, "materias_estudo", study_id); group_id = values.get("group_id")
    if group_id and _get(conn, "grupos_topicos", group_id)["study_subject_id"] != study_id: raise DomainError("A unidade precisa pertencer ao mesmo estudo.")
    study = _get(conn, "materias_estudo", study_id)
    data = _content_data(values)
    data.update({"study_subject_id":study_id,"curriculum_subject_id":study.get("curriculum_subject_id"),"name":_need(data.get("name"),"Nome do tópico")}); data.setdefault("status","not_started"); data.setdefault("mastery",0); data.setdefault("sort_order",0)
    if data["status"] == "completed":
        data.setdefault("started_at", _now()); data.setdefault("completed_at", _today())
    elif data["status"] == "in_progress":
        data.setdefault("started_at", _now())
    elif data["status"] == "for_review":
        data["review_requested"] = 1
    data["manual_mastery"] = data["mastery"]
    owner = ("curriculum", study["curriculum_subject_id"]) if study.get("curriculum_subject_id") else ("study", study_id)
    _assert_topic_estimates_fit(conn, *owner, additional_minutes=data.get("estimated_minutes"))
    saved = _get(conn, "topicos", repo.insert(conn,"topicos",data))
    set_topic_dependencies(conn, saved["id"], values)
    saved = _get(conn, "topicos", saved["id"])
    if saved.get("curriculum_subject_id"):
        _event(conn, saved["curriculum_subject_id"], "content", f"Conteúdo adicionado: {saved['name']}")
    return saved


def update_topic(conn, ident, values):
    topic = _get(conn,"topicos",ident); data = _content_data(values)
    if data.get("group_id") and (not topic.get("study_subject_id") or _get(conn,"grupos_topicos",data["group_id"])["study_subject_id"] != topic["study_subject_id"]): raise DomainError("A unidade precisa pertencer ao mesmo estudo.")
    if "estimated_minutes" in data:
        _assert_topic_estimates_fit(conn, *_topic_owner(conn, topic), replacing_topic_id=ident, replacement_minutes=data["estimated_minutes"])
    if "mastery" in data: data["manual_mastery"] = data["mastery"]
    will_complete_topic = bool(data.get("status") == "completed" and topic.get("status") != "completed")
    if will_complete_topic:
        _require_future_topic_resolution(conn, topic, values.get("future_blocks_action"))
    if data.get("status") == "completed":
        data["completed_at"] = _today(); data.setdefault("started_at", topic.get("started_at") or _now())
    if data.get("status") == "in_progress" and not topic.get("started_at"):
        data["started_at"] = _now()
    if data.get("status") == "for_review":
        data["review_requested"] = 1
    if "status" in data and data["status"] != "completed": data["completed_at"] = None
    repo.update(conn,"topicos",ident,data)
    set_topic_dependencies(conn, ident, values)
    saved = _get(conn,"topicos",ident)
    if saved.get("curriculum_subject_id") and any(key in data for key in {"status","name","estimated_minutes","unit","effort_weight"}):
        _event(conn, saved["curriculum_subject_id"], "content", f"Conteúdo atualizado: {saved['name']}", data.get("status"))
    if will_complete_topic:
        saved["future_blocks"] = _resolve_completed_topic_blocks(conn, saved, values.get("future_blocks_action"))
    return saved


def _content_data(values):
    data = _fields(values, {"name", "description", "group_id", "unit", "difficulty", "estimated_minutes", "sort_order", "mastery", "status", "effort_weight", "observations", "review_requested"})
    for key in ("description", "unit", "group_id", "difficulty", "estimated_minutes", "observations"):
        if data.get(key) == "": data[key] = None
    if "estimated_minutes" in data:
        data["estimated_minutes"] = _optional_minutes(data["estimated_minutes"], "Tempo estimado")
    if "difficulty" in data and data["difficulty"] is not None:
        try: difficulty = int(data["difficulty"])
        except (TypeError, ValueError) as error: raise DomainError("Dificuldade deve estar entre 1 e 5.") from error
        if not 1 <= difficulty <= 5: raise DomainError("Dificuldade deve estar entre 1 e 5.")
        data["difficulty"] = difficulty
    if "sort_order" in data:
        try: data["sort_order"] = int(data["sort_order"])
        except (TypeError, ValueError) as error: raise DomainError("Ordem do conteúdo deve ser um número inteiro.") from error
    if "mastery" in data:
        try: mastery = int(data["mastery"])
        except (TypeError, ValueError) as error: raise DomainError("Domínio deve estar entre 0 e 5.") from error
        if not 0 <= mastery <= 5: raise DomainError("Domínio deve estar entre 0 e 5.")
        data["mastery"] = mastery
    if "effort_weight" in data:
        try: weight = int(data["effort_weight"])
        except (TypeError, ValueError) as error: raise DomainError("Peso do tópico deve ser simples, normal ou complexo.") from error
        if weight not in {1, 2, 3}: raise DomainError("Peso do tópico deve ficar entre 1 (simples) e 3 (complexo).")
        data["effort_weight"] = weight
    if "review_requested" in data:
        data["review_requested"] = 1 if _confirmed(data["review_requested"]) else 0
    if "status" in data and data["status"] not in TOPIC_STATUSES:
        raise DomainError("Status do conteúdo inválido.")
    return data


def _topic_matches_study(conn, topic, study_id):
    if topic.get("study_subject_id") == study_id:
        return True
    study = _get(conn, "materias_estudo", study_id)
    return bool(topic.get("curriculum_subject_id") and study.get("curriculum_subject_id") == topic.get("curriculum_subject_id"))


def _assert_topic_available_for_work(topic):
    if topic.get("archived_at"):
        raise DomainError("Este tópico está arquivado. Restaure-o antes de registrar, focar ou planejar.", 409, "topic_archived")
    return topic


def _contents_for_study(conn, study_id, include_archived=False):
    study = _get(conn, "materias_estudo", study_id)
    clause, params = "(t.study_subject_id=?", [study_id]
    if study.get("curriculum_subject_id"):
        clause += " OR t.curriculum_subject_id=?)"
        params.append(study["curriculum_subject_id"])
    else:
        clause += ")"
    if not include_archived: clause += " AND t.archived_at IS NULL"
    rows = repo.many(conn, "SELECT t.* FROM topicos t WHERE " + clause + " ORDER BY COALESCE(t.unit,''),t.sort_order,t.name", params)
    return _topic_metrics_rows(conn, rows)


def contents(conn, curriculum_id, include_archived=False):
    item = _get(conn, "disciplinas_grade", curriculum_id)
    resolved, linked_curricula = _shared_study_context_for_curriculum(conn, curriculum_id)
    shared_study_id = resolved["study"]["id"] if resolved and len(linked_curricula) > 1 else None
    if shared_study_id:
        linked_ids = [row["id"] for row in linked_curricula]
        marks = ",".join("?" for _ in linked_ids)
        where = f"(t.study_subject_id=? OR t.curriculum_subject_id IN ({marks}))"
        params = (shared_study_id, *linked_ids)
    else:
        where, params = "t.curriculum_subject_id=?", (curriculum_id,)
    if not include_archived:
        where += " AND t.archived_at IS NULL"
    rows = repo.many(conn, "SELECT t.* FROM topicos t WHERE " + where + " ORDER BY COALESCE(t.unit,''),t.sort_order,t.name", params)
    enriched = _topic_metrics_rows(conn, rows)
    return {
        "curriculum": item, "contents": enriched,
        "effort_distribution": _topic_effort_summary(conn, "curriculum", curriculum_id),
        "shared_study": ({"canonical_study_id": shared_study_id, "curriculum_subjects": linked_curricula} if shared_study_id else None),
    }


def create_content(conn, curriculum_id, values):
    item = _get(conn, "disciplinas_grade", curriculum_id)
    _active_formation(conn, item["formation_id"])
    if item["archived_at"]: raise DomainError("Restaure a disciplina antes de adicionar conteúdos.", 409, "curriculum_archived")
    data = _content_data(values)
    if data.get("group_id"):
        raise DomainError("Use Unidade para agrupar conteúdos da disciplina.")
    data.update({"curriculum_subject_id": curriculum_id, "name": _need(data.get("name"), "Título do conteúdo")})
    data.setdefault("status", "not_started"); data.setdefault("mastery", 0); data.setdefault("manual_mastery", data["mastery"]); data.setdefault("sort_order", 0)
    if data["status"] == "completed":
        data.setdefault("started_at", _now()); data.setdefault("completed_at", _today())
    elif data["status"] == "in_progress":
        data.setdefault("started_at", _now())
    elif data["status"] == "for_review":
        data["review_requested"] = 1
    _assert_topic_estimates_fit(conn, "curriculum", curriculum_id, additional_minutes=data.get("estimated_minutes"))
    saved = _get(conn, "topicos", repo.insert(conn, "topicos", data))
    set_topic_dependencies(conn, saved["id"], values)
    saved = _get(conn, "topicos", saved["id"])
    _event(conn, curriculum_id, "content", f"Conteúdo adicionado: {saved['name']}")
    return saved


def update_content(conn, ident, values):
    _get(conn, "topicos", ident)
    return update_topic(conn, ident, values)


def archive_topic(conn, ident, restore=False):
    """Arquiva qualquer tópico sem destruir o histórico nem blocos manuais."""
    topic = _get(conn, "topicos", ident)
    repo.update(conn, "topicos", ident, {"archived_at": None if restore else _now()})
    saved = _get(conn, "topicos", ident)
    if topic.get("curriculum_subject_id"):
        _event(conn, topic["curriculum_subject_id"], "content", ("Conteúdo restaurado: " if restore else "Conteúdo arquivado: ") + topic["name"])
    if restore:
        return saved
    rows = _future_topic_blocks(conn, ident)
    automatic = [row for row in rows if row.get("source") == "automatic"]
    if automatic:
        ids = [row["id"] for row in automatic]
        markers = ",".join("?" for _ in ids)
        conn.execute(
            f"UPDATE sessoes_planejadas SET status='cancelled',selection_reason=?,"
            "updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') "
            f"WHERE id IN ({markers})",
            ("cancelado: tópico arquivado", *ids),
        )
    saved["cancelled_future_blocks"] = {
        "count": len(automatic), "ids": [row["id"] for row in automatic],
        "manual_preserved": len(rows) - len(automatic),
        "manual_ids": [row["id"] for row in rows if row.get("source") != "automatic"],
    }
    return saved


def archive_content(conn, ident, restore=False):
    content = _get(conn, "topicos", ident)
    if not content.get("curriculum_subject_id"):
        raise DomainError("Este conteúdo não pertence diretamente a uma disciplina curricular.")
    return archive_topic(conn, ident, restore)


def delete_content(conn, ident):
    content = _get(conn, "topicos", ident)
    try: repo.delete(conn, "topicos", ident)
    except sqlite3.IntegrityError as error:
        raise DomainError("Não é possível excluir este conteúdo porque há sessões, blocos, avaliações ou histórico relacionados. Arquive-o para preservá-los.", 409, "content_has_dependencies") from error
    if content.get("curriculum_subject_id"):
        _event(conn, content["curriculum_subject_id"], "content", f"Conteúdo excluído: {content['name']}")


def content_history(conn, ident):
    content = _get(conn, "topicos", ident)
    return {
        "content": content,
        "sessions": repo.many(conn, "SELECT x.* FROM sessoes_estudo x WHERE x.topic_id=? ORDER BY x.date DESC,x.id DESC", (ident,)),
        "planned": repo.many(conn, "SELECT p.* FROM sessoes_planejadas p WHERE p.topic_id=? ORDER BY p.scheduled_date DESC,p.id DESC", (ident,)),
    }


def _recalculate_mastery(conn, topic_id):
    if not topic_id: return
    last = repo.one(conn,"SELECT mastery_after FROM sessoes_estudo WHERE topic_id=? AND mastery_after IS NOT NULL ORDER BY date DESC,id DESC LIMIT 1",(topic_id,))
    repo.update(conn,"topicos",topic_id,{"mastery":last["mastery_after"] if last else _get(conn,"topicos",topic_id)["manual_mastery"]})


def create_session(conn, values):
    study_id = _need(values.get("study_subject_id"),"Matéria")
    topic_id = values.get("topic_id")
    seconds=int(_need(values.get("duration_seconds"),"Duração"))
    if seconds<=0: raise DomainError("A duração deve ser maior que zero.")
    data=_fields(values,{"study_subject_id","topic_id","planned_session_id","date","started_at","ended_at","duration_seconds","entry_method","mastery_before","mastery_after","progress_level","notes"})
    data.update({"study_subject_id":study_id,"duration_seconds":seconds,"date":data.get("date",_today()),"entry_method":data.get("entry_method","manual")})
    _assert_study_accessible(conn, study_id, intent="review" if data["entry_method"] == "review" else "session")
    topic = _assert_topic_available_for_work(_get(conn,"topicos",topic_id)) if topic_id else None
    if topic_id and not _topic_matches_study(conn, topic, study_id): raise DomainError("O conteúdo precisa pertencer à matéria selecionada.")
    _date(data["date"])
    if data.get("mastery_after") is not None and not 0 <= int(data["mastery_after"]) <= 5: raise DomainError("Domínio deve estar entre 0 e 5.")
    completed = values.get("topic_completed") in (True,1,"1","true","True","sim")
    will_complete_topic = bool(completed and topic and topic.get("status") != "completed")
    if completed and not topic_id:
        raise DomainError("Concluir tópico exige selecionar um tópico.")
    if will_complete_topic:
        _require_future_topic_resolution(conn, topic, values.get("future_blocks_action"))
    planned_id = data.get("planned_session_id")
    if planned_id:
        planned_item = planned_detail(conn, planned_id)
        if planned_item["study_subject_id"] != study_id: raise DomainError("A sessão planejada precisa pertencer à mesma matéria.")
        # A transição condicional é feita antes da inserção, na mesma transação.
        # Assim, duas requisições quase simultâneas não conseguem registrar duas
        # sessões para o mesmo bloco planejado.
        claimed = conn.execute(
            "UPDATE sessoes_planejadas SET status='completed',updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') "
            "WHERE id=? AND status IN ('planned','skipped')",
            (planned_id,),
        ).rowcount
        if not claimed:
            fresh = planned_detail(conn, planned_id)
            if fresh["status"] == "completed":
                raise DomainError("Esta sessão planejada já foi concluída.", 409, "planned_already_completed")
            raise DomainError("Esta sessão planejada não está disponível para conclusão.", 409, "planned_not_active")
    if topic_id and data.get("mastery_before") is None: data["mastery_before"]=topic["mastery"]
    if data.get("started_at") and data.get("ended_at"):
        data["duration_seconds"] = max(1, int((datetime.fromisoformat(str(data["ended_at"]).replace("Z","+00:00")) - datetime.fromisoformat(str(data["started_at"]).replace("Z","+00:00"))).total_seconds()))
    ident=repo.insert(conn,"sessoes_estudo",data); _recalculate_mastery(conn,topic_id)
    if completed:
        repo.update(conn,"topicos",topic_id,{"status":"completed","completed_at":data["date"],"last_session_date":data["date"],"started_at":topic.get("started_at") or _now()})
    if topic_id and data["entry_method"] != "review":
        topic = _get(conn,"topicos",topic_id)
        if topic["status"] == "not_started": repo.update(conn,"topicos",topic_id,{"status":"in_progress","started_at":topic.get("started_at") or _now()})
        repo.update(conn,"topicos",topic_id,{"last_session_date":data["date"]})
        _start_review_chain(conn, topic_id, ident, _date(data["date"]))
    session = _get(conn,"sessoes_estudo",ident)
    if topic_id:
        topic = _get(conn, "topicos", topic_id)
        if topic.get("curriculum_subject_id"):
            _event(conn, topic["curriculum_subject_id"], "content", f"Sessão registrada: {topic['name']}", f"{int(data['duration_seconds']) // 60} min")
    if completed:
        session["topic_completed"] = True
        if will_complete_topic:
            session["future_blocks"] = _resolve_completed_topic_blocks(conn, topic, values.get("future_blocks_action"))
    return session


def update_session(conn, ident, values):
    old=_get(conn,"sessoes_estudo",ident); data=_fields(values,{"study_subject_id","date","started_at","ended_at","duration_seconds","entry_method","mastery_before","mastery_after","progress_level","notes","topic_id"})
    topic_id=data.get("topic_id",old["topic_id"]); study_id=data.get("study_subject_id",old["study_subject_id"])
    entry_method = data.get("entry_method", old["entry_method"])
    _assert_study_accessible(conn, study_id, intent="review" if entry_method == "review" else "session")
    topic = _get(conn,"topicos",topic_id) if topic_id else None
    if topic_id and not _topic_matches_study(conn, topic, study_id): raise DomainError("O conteúdo precisa pertencer à matéria selecionada.")
    if data.get("started_at") and data.get("ended_at"): data["duration_seconds"] = max(1,int((datetime.fromisoformat(str(data["ended_at"]).replace("Z","+00:00"))-datetime.fromisoformat(str(data["started_at"]).replace("Z","+00:00"))).total_seconds()))
    if "duration_seconds" in data and int(data["duration_seconds"])<=0: raise DomainError("A duração deve ser maior que zero.")
    if "date" in data: _date(data["date"])
    if data.get("mastery_after") is not None and not 0 <= int(data["mastery_after"]) <= 5: raise DomainError("Domínio deve estar entre 0 e 5.")
    completed = values.get("topic_completed") in (True,1,"1","true","True","sim")
    will_complete_topic = bool(completed and topic and topic.get("status") != "completed")
    if completed and not topic_id:
        raise DomainError("Concluir tópico exige selecionar um tópico.")
    if will_complete_topic:
        _require_future_topic_resolution(conn, topic, values.get("future_blocks_action"))
    changed_source = any(key in data for key in ("topic_id","date","entry_method"))
    if changed_source: conn.execute("UPDATE revisoes SET status='cancelled' WHERE root_session_id=? AND status='pending'",(ident,))
    repo.update(conn,"sessoes_estudo",ident,data); _recalculate_mastery(conn,old["topic_id"]); _recalculate_mastery(conn,topic_id)
    if changed_source and topic_id and entry_method != "review": _start_review_chain(conn,topic_id,ident,_date(data.get("date",old["date"])))
    if completed:
        repo.update(conn,"topicos",topic_id,{"status":"completed","completed_at":data.get("date",old["date"]),"last_session_date":data.get("date",old["date"])})
    saved = _get(conn,"sessoes_estudo",ident)
    if will_complete_topic:
        saved["topic_completed"] = True
        saved["future_blocks"] = _resolve_completed_topic_blocks(conn, topic, values.get("future_blocks_action"))
    return saved


def delete_session(conn, ident):
    old=_get(conn,"sessoes_estudo",ident); conn.execute("UPDATE revisoes SET status='cancelled' WHERE root_session_id=? AND status='pending'",(ident,)); remove(conn,"sessoes_estudo",ident); _recalculate_mastery(conn,old["topic_id"])


def _timestamp(value, label="Horário"):
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError) as error:
            raise DomainError(f"{label} inválido.") from error
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=LOCAL_TIMEZONE)
    return parsed.astimezone(LOCAL_TIMEZONE)


def _focus_elapsed_seconds(focus, now=None):
    accumulated = max(0, int(focus.get("accumulated_seconds") or 0))
    if focus.get("status") != "running" or not focus.get("last_resumed_at"):
        return accumulated
    current = _timestamp(now or _local_now())
    resumed = _timestamp(focus["last_resumed_at"], "Horário de retomada")
    return accumulated + max(0, int((current - resumed).total_seconds()))


def _focus_recovery_limit_seconds(conn):
    raw = settings(conn).get("focus_recovery_minutes")
    try:
        minutes = int(raw) if raw not in (None, "") else 8 * 60
    except (TypeError, ValueError):
        minutes = 8 * 60
    return max(15, minutes) * 60


def _focus_row(conn, ident):
    row = repo.one(conn, """
        SELECT fs.*,COALESCE(d.name,s.personal_name) subject_name,t.name topic_name,
          COALESCE(p.planned_duration_minutes,fs.planned_duration_minutes) planned_duration_minutes,
          p.scheduled_date,p.start_time,p.status planned_status
        FROM sessoes_foco fs
        JOIN materias_estudo s ON s.id=fs.study_subject_id
        LEFT JOIN disciplinas_grade d ON d.id=s.curriculum_subject_id
        LEFT JOIN topicos t ON t.id=fs.topic_id
        LEFT JOIN sessoes_planejadas p ON p.id=fs.planned_session_id
        WHERE fs.id=?
    """, (ident,))
    if not row:
        raise DomainError("Sessão de foco não encontrada.", 404, "focus_not_found")
    return row


def _focus_snapshot(conn, focus, *, check_recovery=True):
    """Retorna a sessão oficial e detecta intervalos anormalmente longos."""
    if check_recovery and focus["status"] == "running":
        elapsed = _focus_elapsed_seconds(focus)
        if elapsed > _focus_recovery_limit_seconds(conn):
            now = _now()
            conn.execute(
                "UPDATE sessoes_foco SET status='recovery_required',accumulated_seconds=?,paused_at=?,"
                "last_resumed_at=NULL,recovery_required_at=?,version=version+1,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=? AND status='running'",
                (elapsed, now, now, focus["id"]),
            )
            focus = _focus_row(conn, focus["id"])
    snapshot = dict(focus)
    snapshot["elapsed_seconds"] = _focus_elapsed_seconds(snapshot)
    snapshot["recovery_limit_seconds"] = _focus_recovery_limit_seconds(conn)
    snapshot["recovery_required"] = snapshot["status"] == "recovery_required"
    snapshot["is_active"] = snapshot["status"] in {"running", "paused", "recovery_required"}
    return snapshot


def _focus_assert_version(focus, values):
    expected = values.get("version")
    if expected in (None, ""):
        return
    try:
        expected = int(expected)
    except (TypeError, ValueError) as error:
        raise DomainError("Versão da sessão de foco inválida.") from error
    if expected != int(focus["version"]):
        raise DomainError(
            "Esta sessão foi atualizada em outra aba. Os dados mais recentes foram preservados.",
            409,
            "focus_version_conflict",
            details={"focus_session_id": focus["id"], "version": focus["version"]},
        )


def _next_topic_for(conn, topic):
    owner_kind, owner_id = _topic_owner(conn, topic)
    rows = _topic_metrics_rows(conn, _topic_owner_topics(conn, owner_kind, owner_id))
    statuses = {row["id"]: row.get("status") for row in rows}
    candidates = [
        row for row in rows
        if row["id"] != topic["id"] and row.get("status") in {"in_progress", "not_started"}
        and all(statuses.get(prerequisite) == "completed" for prerequisite in row.get("prerequisite_topic_ids", []))
    ]
    rank = {"in_progress": 0, "not_started": 1}
    return min(candidates, key=lambda row: (rank[row["status"]], int(row.get("sort_order") or 0), row["id"])) if candidates else None


def _future_topic_blocks(conn, topic_id):
    return repo.many(conn, """
        SELECT p.*,COALESCE(d.name,s.personal_name) subject_name
        FROM sessoes_planejadas p JOIN materias_estudo s ON s.id=p.study_subject_id
        LEFT JOIN disciplinas_grade d ON d.id=s.curriculum_subject_id
        WHERE p.topic_id=? AND p.status='planned' AND p.scheduled_date>=?
        ORDER BY p.scheduled_date,p.start_time,p.id
    """, (topic_id, _today()))


def _require_future_topic_resolution(conn, topic, action):
    """Impede que uma conclusão deixe blocos automáticos pendentes.

    Blocos manuais nunca são alterados por este fluxo: eles aparecem no retorno
    para que a interface possa pedir uma escolha separada ao usuário.
    """
    rows = _future_topic_blocks(conn, topic["id"])
    automatic = [row for row in rows if row["source"] == "automatic"]
    if automatic and action not in {"replan", "next_topic", "review"}:
        raise DomainError(
            "Escolha o destino dos blocos automáticos futuros deste tópico.",
            409,
            "future_topic_blocks_need_resolution",
            details={
                "automatic_blocks": automatic,
                "manual_blocks": [row for row in rows if row["source"] == "manual"],
                "allowed_actions": ["replan", "next_topic", "review"],
            },
        )


def _resolve_completed_topic_blocks(conn, topic, action):
    rows = _future_topic_blocks(conn, topic["id"])
    automatic = [row for row in rows if row["source"] == "automatic"]
    manual = [row for row in rows if row["source"] == "manual"]
    if not automatic:
        return {"automatic_changed": 0, "manual_preserved": len(manual), "action": action or "none", "next_topic": None}
    if action not in {"replan", "next_topic", "review"}:
        raise DomainError(
            "Escolha como tratar os blocos automáticos futuros deste tópico antes de concluir.",
            409,
            "future_topic_blocks_need_resolution",
            details={
                "automatic_blocks": automatic,
                "manual_blocks": manual,
                "allowed_actions": ["replan", "next_topic", "review"],
            },
        )
    if action == "replan":
        conn.execute(
            "UPDATE sessoes_planejadas SET status='cancelled',selection_reason=?,selection_context=?,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') "
            "WHERE topic_id=? AND source='automatic' AND status='planned' AND scheduled_date>=?",
            ("cancelado: tópico concluído", "replanejamento necessário", topic["id"], _today()),
        )
        return {"automatic_changed": len(automatic), "manual_preserved": len(manual), "action": action, "next_topic": None}
    if action == "next_topic":
        next_topic = _next_topic_for(conn, topic)
        if not next_topic:
            raise DomainError("Não há próximo tópico elegível para receber estes blocos. Escolha replanejar ou manter como revisão.", 409, "next_topic_missing")
        conn.execute(
            "UPDATE sessoes_planejadas SET topic_id=?,selection_reason=?,selection_context=?,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') "
            "WHERE topic_id=? AND source='automatic' AND status='planned' AND scheduled_date>=?",
            (next_topic["id"], "avançado após conclusão do tópico anterior", f"tópico anterior: {topic['id']}", topic["id"], _today()),
        )
        return {"automatic_changed": len(automatic), "manual_preserved": len(manual), "action": action, "next_topic": next_topic}
    conn.execute(
        "UPDATE sessoes_planejadas SET selection_reason=?,selection_context=?,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') "
        "WHERE topic_id=? AND source='automatic' AND status='planned' AND scheduled_date>=?",
        ("mantido como revisão após conclusão", "revisão explícita", topic["id"], _today()),
    )
    return {"automatic_changed": len(automatic), "manual_preserved": len(manual), "action": action, "next_topic": None}


def active_focus_session(conn):
    row = repo.one(conn, "SELECT id FROM sessoes_foco WHERE status IN ('running','paused','recovery_required') ORDER BY updated_at DESC,id DESC LIMIT 1")
    return _focus_snapshot(conn, _focus_row(conn, row["id"])) if row else None


def start_focus_session(conn, values):
    planned_id = values.get("planned_session_id", values.get("planned_id"))
    planned_item = planned_detail(conn, int(planned_id)) if planned_id not in (None, "") else None
    active = active_focus_session(conn)
    if active:
        if planned_item and active.get("planned_session_id") == planned_item["id"]:
            return {"session": active, "recovered": True}
        raise DomainError(
            f"Já existe uma sessão em andamento: {active['subject_name']}{' — ' + active['topic_name'] if active.get('topic_name') else ''}.",
            409,
            "focus_session_already_active",
            details={"active_session": active},
        )
    if planned_item:
        if planned_item["status"] != "planned":
            raise DomainError("Este bloco planejado não está disponível para foco.", 409, "planned_not_active")
        study_id = planned_item["study_subject_id"]
        topic_id = planned_item.get("topic_id")
    else:
        study_id = _need(values.get("study_subject_id", values.get("study_id")), "Matéria")
        topic_id = values.get("topic_id")
    study = _assert_study_accessible(conn, int(study_id), require_current=True, intent="focus")
    if topic_id not in (None, ""):
        topic = _assert_topic_available_for_work(_get(conn, "topicos", int(topic_id)))
        if not _topic_matches_study(conn, topic, study["id"]):
            raise DomainError("O tópico não pertence à matéria selecionada.")
    else:
        available = _topic_metrics_rows(conn, _contents_for_study(conn, study["id"]))
        statuses = {row["id"]: row.get("status") for row in available}
        topic = next((row for row in available if row.get("status") == "in_progress"), None)
        topic = topic or next((row for row in available if row.get("status") == "not_started" and all(statuses.get(prerequisite) == "completed" for prerequisite in row.get("prerequisite_topic_ids", []))), None)
        topic_id = topic["id"] if topic else None
    now = _now()
    duration = values.get("planned_duration_minutes")
    if planned_item:
        duration = planned_item.get("planned_duration_minutes")
    if duration not in (None, ""):
        try:
            duration = int(duration)
        except (TypeError, ValueError) as error:
            raise DomainError("Duração planejada inválida.") from error
        if duration <= 0:
            raise DomainError("A duração planejada deve ser maior que zero.")
    try:
        focus_id = repo.insert(conn, "sessoes_foco", {
            "study_subject_id": study["id"], "topic_id": int(topic_id) if topic_id else None,
            "planned_session_id": planned_item["id"] if planned_item else None,
            "planned_duration_minutes": duration,
            "status": "running", "started_at": now, "last_resumed_at": now,
        })
    except sqlite3.IntegrityError as error:
        active = active_focus_session(conn)
        if active:
            raise DomainError(
                f"Já existe uma sessão em andamento: {active['subject_name']}{' — ' + active['topic_name'] if active.get('topic_name') else ''}.",
                409,
                "focus_session_already_active",
                details={"active_session": active},
            ) from error
        raise
    return {"session": _focus_snapshot(conn, _focus_row(conn, focus_id)), "recovered": False}


def pause_focus_session(conn, ident, values=None):
    values = values or {}
    focus = _focus_row(conn, ident)
    if focus["status"] == "paused":
        return _focus_snapshot(conn, focus)
    _focus_assert_version(focus, values)
    if focus["status"] == "recovery_required":
        return _focus_snapshot(conn, focus)
    if focus["status"] != "running":
        raise DomainError("Esta sessão de foco não está em andamento.", 409, "focus_not_running")
    now = _now()
    elapsed = _focus_elapsed_seconds(focus)
    conn.execute(
        "UPDATE sessoes_foco SET status='paused',accumulated_seconds=?,paused_at=?,last_resumed_at=NULL,version=version+1,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
        (elapsed, now, ident),
    )
    return _focus_snapshot(conn, _focus_row(conn, ident))


def resume_focus_session(conn, ident, values=None):
    values = values or {}
    focus = _focus_row(conn, ident)
    if focus["status"] == "running":
        return _focus_snapshot(conn, focus)
    _focus_assert_version(focus, values)
    if focus["status"] == "recovery_required":
        raise DomainError("Confirme o período excepcional antes de retomar a sessão.", 409, "focus_recovery_required")
    if focus["status"] != "paused":
        raise DomainError("Esta sessão de foco não está pausada.", 409, "focus_not_paused")
    now = _now()
    conn.execute(
        "UPDATE sessoes_foco SET status='running',last_resumed_at=?,paused_at=NULL,version=version+1,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
        (now, ident),
    )
    return _focus_snapshot(conn, _focus_row(conn, ident))


def recover_focus_session(conn, ident, values):
    focus = _focus_row(conn, ident)
    _focus_assert_version(focus, values)
    if focus["status"] != "recovery_required":
        return _focus_snapshot(conn, focus)
    choice = values.get("choice")
    elapsed = int(focus.get("accumulated_seconds") or 0)
    if choice == "full":
        accepted = elapsed
    elif choice in {"planned", "discard_excess"}:
        accepted = min(elapsed, int(focus.get("planned_duration_minutes") or elapsed))
    elif choice == "actual":
        try:
            accepted = int(values.get("duration_seconds"))
        except (TypeError, ValueError) as error:
            raise DomainError("Informe a duração real em segundos.") from error
        if accepted < 0 or accepted > elapsed:
            raise DomainError("A duração real deve ficar entre zero e o tempo registrado.")
    else:
        raise DomainError("Escolha como tratar o período excepcional.")
    now = _now()
    status = "running" if _confirmed(values.get("resume")) else "paused"
    conn.execute(
        "UPDATE sessoes_foco SET status=?,accumulated_seconds=?,last_resumed_at=?,paused_at=?,recovery_required_at=NULL,version=version+1,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
        (status, accepted, now if status == "running" else None, None if status == "running" else now, ident),
    )
    return _focus_snapshot(conn, _focus_row(conn, ident))


def save_focus_note(conn, ident, values):
    focus = _focus_row(conn, ident)
    if focus["status"] in {"completed", "cancelled"}:
        raise DomainError("Esta sessão de foco já foi encerrada.", 409, "focus_closed")
    payload = {
        "study_subject_id": focus["study_subject_id"], "topic_id": focus.get("topic_id"),
        "planned_session_id": focus.get("planned_session_id"),
        "title": values.get("title") or f"Anotação de {focus['subject_name']}",
        "content_markdown": values.get("content_markdown", values.get("content", "")),
        "tags": values.get("tags", ""), "status": "draft",
    }
    note = autosave_note(conn, focus["note_id"], payload) if focus.get("note_id") else create_note(conn, payload)
    if not focus.get("note_id"):
        conn.execute("UPDATE sessoes_foco SET note_id=?,version=version+1,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?", (note["id"], ident))
    return {"note": note, "session": _focus_snapshot(conn, _focus_row(conn, ident))}


def finish_focus_session(conn, ident, values):
    focus = _focus_row(conn, ident)
    if focus["status"] == "completed":
        return {"session": _focus_snapshot(conn, focus, check_recovery=False), "study_session": _get(conn, "sessoes_estudo", focus["completed_study_session_id"]) if focus.get("completed_study_session_id") else None, "idempotent": True}
    _focus_assert_version(focus, values)
    if focus["status"] == "recovery_required":
        raise DomainError("Confirme o período excepcional antes de encerrar.", 409, "focus_recovery_required")
    if focus["status"] not in {"running", "paused"}:
        raise DomainError("Esta sessão de foco não pode ser encerrada.", 409, "focus_not_active")
    duration = _focus_elapsed_seconds(focus)
    if duration < 1:
        raise DomainError("Registre ao menos um segundo de foco antes de encerrar.")
    topic_outcome = values.get("topic_outcome", "continue")
    if topic_outcome not in {"continue", "completed", "advance", "review"}:
        raise DomainError("Resultado do tópico inválido.")
    topic = _get(conn, "topicos", focus["topic_id"]) if focus.get("topic_id") else None
    if topic_outcome in {"completed", "advance"} and not topic:
        raise DomainError("Concluir um tópico exige selecionar um tópico.")
    # A escolha sobre blocos futuros é explícita e é validada antes de criar a
    # sessão real, mantendo a finalização completamente transacional.
    if topic_outcome in {"completed", "advance"}:
        _require_future_topic_resolution(conn, topic, values.get("future_blocks_action"))
    # A transição condicional é o marcador de idempotência para sessões livres.
    # Em uma repetição/conflito, somente a primeira finalização pode criar a
    # sessão real; a outra observa o resultado já persistido.
    claimed = conn.execute(
        "UPDATE sessoes_foco SET status='finishing',accumulated_seconds=?,last_resumed_at=NULL,paused_at=?,version=version+1,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') "
        "WHERE id=? AND status IN ('running','paused')",
        (duration, _now(), ident),
    ).rowcount
    if not claimed:
        current = _focus_row(conn, ident)
        if current["status"] == "completed":
            return {"session": _focus_snapshot(conn, current, check_recovery=False), "study_session": _get(conn, "sessoes_estudo", current["completed_study_session_id"]) if current.get("completed_study_session_id") else None, "idempotent": True}
        raise DomainError("Esta sessão de foco está sendo encerrada em outra aba.", 409, "focus_finishing")
    focus = _focus_row(conn, ident)
    now = _local_now()
    created_session = create_session(conn, {
        "study_subject_id": focus["study_subject_id"], "topic_id": focus.get("topic_id"),
        "planned_session_id": focus.get("planned_session_id"), "date": now.date().isoformat(),
        "duration_seconds": duration, "entry_method": "timer", "notes": values.get("notes", ""),
        "topic_completed": topic_outcome in {"completed", "advance"},
        "future_blocks_action": values.get("future_blocks_action"),
    })
    future_result = created_session.get("future_blocks")
    repo.update(conn, "sessoes_estudo", created_session["id"], {"started_at": focus["started_at"], "ended_at": now.isoformat()})
    session = _get(conn, "sessoes_estudo", created_session["id"])
    if topic_outcome == "review" and topic:
        repo.update(conn, "topicos", topic["id"], {"status": "for_review", "review_requested": 1})
    note = None
    note_id = focus.get("note_id")
    if values.get("note") is not None:
        note_values = values["note"] if isinstance(values["note"], dict) else {}
        note = save_focus_note(conn, ident, note_values)["note"]
        note_id = note["id"]
    if note_id:
        note = finalize_note(conn, note_id, {"study_session_id": session["id"]})
    now_text = _now()
    conn.execute(
        "UPDATE sessoes_foco SET status='completed',accumulated_seconds=?,ended_at=?,last_resumed_at=NULL,paused_at=?,completed_study_session_id=?,version=version+1,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
        (duration, now_text, now_text, session["id"], ident),
    )
    payload = {
        "session": _focus_snapshot(conn, _focus_row(conn, ident), check_recovery=False),
        "study_session": session, "note": note, "future_blocks": future_result,
        "topic_outcome": topic_outcome, "replanning_recommended": bool(topic_outcome in {"completed", "advance"} or duration),
    }
    if topic:
        refreshed_topic = _topic_metrics_rows(conn, [_get(conn, "topicos", topic["id"])])[0]
        payload["topic_effort_result"] = {
            "topic_id": refreshed_topic["id"], "estimated_minutes": refreshed_topic.get("effective_estimated_minutes"),
            "real_minutes": refreshed_topic.get("real_minutes"),
            "economy_minutes": refreshed_topic.get("economy_minutes"),
            "overrun_minutes": refreshed_topic.get("overrun_minutes"),
            "remaining_minutes": refreshed_topic.get("remaining_minutes"),
            "status": refreshed_topic.get("status"),
        }
        if refreshed_topic.get("overrun_minutes") and refreshed_topic.get("status") != "completed":
            payload["topic_effort_alert"] = (
                f"{refreshed_topic['name']} já consumiu {int(refreshed_topic['overrun_minutes'])} min além da estimativa. "
                "O tópico continua em andamento e o ritmo foi recalculado sem alterar sua estimativa automaticamente."
            )
    if topic_outcome == "advance" and future_result and future_result.get("next_topic"):
        payload["next_topic"] = future_result["next_topic"]
    if topic_outcome in {"completed", "advance", "review"}:
        # Recalcula a prévia com os dados transacionais já atualizados, sem
        # aplicar ou apagar qualquer bloco manual. A interface pode apresentar
        # a proposta ao usuário em vez de preencher a folga automaticamente.
        try:
            payload["replanning_preview"] = generate_plan(conn, _today(), 7)
        except DomainError as error:
            payload["replanning_error"] = {"code": error.code, "message": str(error)}
    return payload


def cancel_focus_session(conn, ident, values=None):
    values = values or {}
    focus = _focus_row(conn, ident)
    if focus["status"] == "cancelled":
        return _focus_snapshot(conn, focus, check_recovery=False)
    _focus_assert_version(focus, values)
    if focus["status"] == "completed":
        raise DomainError("Uma sessão concluída não pode ser cancelada.", 409, "focus_completed")
    now = _now()
    conn.execute(
        "UPDATE sessoes_foco SET status='cancelled',accumulated_seconds=?,ended_at=?,last_resumed_at=NULL,paused_at=?,version=version+1,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
        (_focus_elapsed_seconds(focus), now, now, ident),
    )
    return _focus_snapshot(conn, _focus_row(conn, ident), check_recovery=False)


# Anotações são um registro próprio: uma sessão pode ter uma nota, mas um rascunho
# também sobrevive antes de existir uma sessão concluída.


def _note_id(value, label):
    if value is None or value == "":
        return None
    try:
        ident = int(value)
    except (TypeError, ValueError) as error:
        raise DomainError(f"{label} inválido.") from error
    if ident <= 0:
        raise DomainError(f"{label} inválido.")
    return ident


def _note_tags(value):
    if value is None:
        return ""
    if isinstance(value, str):
        items = value.split(",")
    elif isinstance(value, list):
        items = value
    else:
        raise DomainError("Tags devem ser uma lista ou texto separado por vírgulas.")
    cleaned, seen = [], set()
    for item in items:
        if not isinstance(item, str):
            raise DomainError("Cada tag deve ser um texto.")
        tag = " ".join(item.strip().lstrip("#").split())
        if not tag or tag.casefold() in seen:
            continue
        seen.add(tag.casefold())
        cleaned.append(tag)
    return ", ".join(cleaned)


def _note_content(value):
    if value is None:
        return ""
    if not isinstance(value, str):
        raise DomainError("O conteúdo da anotação deve ser texto em Markdown.")
    return value


def _default_note_title():
    return f"Anotação de estudo — {_today()}"


def _note_title(value, use_default=False):
    if value is None or (isinstance(value, str) and not value.strip()):
        if use_default:
            return _default_note_title()
        raise DomainError("Título é obrigatório.")
    if not isinstance(value, str):
        raise DomainError("Título deve ser texto.")
    return _need(value, "Título")


def _note_relationships(conn, study_subject_id, topic_id=None, planned_session_id=None, study_session_id=None):
    study_subject_id = _note_id(study_subject_id, "Matéria")
    if study_subject_id is None:
        raise DomainError("Matéria é obrigatória.")
    _get(conn, "materias_estudo", study_subject_id)
    topic_id = _note_id(topic_id, "Tópico")
    planned_session_id = _note_id(planned_session_id, "Sessão planejada")
    study_session_id = _note_id(study_session_id, "Sessão de estudo")
    if topic_id:
        topic = _get(conn, "topicos", topic_id)
        if not _topic_matches_study(conn, topic, study_subject_id):
            raise DomainError("O conteúdo precisa pertencer à matéria selecionada.")
    if planned_session_id:
        planned_item = planned_detail(conn, planned_session_id)
        if planned_item["study_subject_id"] != study_subject_id:
            raise DomainError("A sessão planejada precisa pertencer à matéria selecionada.")
    if study_session_id:
        session = _get(conn, "sessoes_estudo", study_session_id)
        if session["study_subject_id"] != study_subject_id:
            raise DomainError("A sessão de estudo precisa pertencer à matéria selecionada.")
    return {
        "study_subject_id": study_subject_id,
        "topic_id": topic_id,
        "planned_session_id": planned_session_id,
        "study_session_id": study_session_id,
    }


def _note_select(where="", params=()):
    sql = "SELECT n.*,COALESCE(d.name,s.personal_name) subject_name,t.name topic_name FROM anotacoes_estudo n JOIN materias_estudo s ON s.id=n.study_subject_id LEFT JOIN disciplinas_grade d ON d.id=s.curriculum_subject_id LEFT JOIN topicos t ON t.id=n.topic_id " + where
    return sql, params


def note_detail(conn, ident):
    sql, params = _note_select("WHERE n.id=?", (ident,))
    note = repo.one(conn, sql, params)
    if not note:
        raise DomainError("Anotação não encontrada.", 404, "note_not_found")
    return note


def create_note(conn, values):
    status = values.get("status", "draft")
    if status != "draft":
        raise DomainError("Crie a anotação como rascunho e use Finalizar após concluir a sessão.", 400, "use_note_finalize")
    links = _note_relationships(
        conn,
        values.get("study_subject_id"),
        values.get("topic_id"),
        values.get("planned_session_id"),
    )
    title = _note_title(values.get("title"), use_default=True)
    data = {
        **links,
        "title": title,
        "content_markdown": _note_content(values.get("content_markdown", "")),
        "tags": _note_tags(values.get("tags", "")),
        "status": "draft",
    }
    data.pop("study_session_id")
    return note_detail(conn, repo.insert(conn, "anotacoes_estudo", data))


def autosave_note(conn, ident, values):
    current = note_detail(conn, ident)
    data = {}
    if "title" in values:
        data["title"] = _note_title(values["title"])
    if "content_markdown" in values:
        data["content_markdown"] = _note_content(values["content_markdown"])
    if "tags" in values:
        data["tags"] = _note_tags(values["tags"])
    relationship_keys = {"topic_id", "planned_session_id"}
    if relationship_keys.intersection(values):
        if current["status"] == "final":
            raise DomainError("Uma anotação final não pode ser reassociada a outro tópico ou planejamento.", 409, "note_finalized")
        links = _note_relationships(
            conn,
            current["study_subject_id"],
            values.get("topic_id", current["topic_id"]),
            values.get("planned_session_id", current["planned_session_id"]),
        )
        data.update({key: links[key] for key in relationship_keys})
    repo.update(conn, "anotacoes_estudo", ident, data)
    return note_detail(conn, ident)


def finalize_note(conn, ident, values):
    current = note_detail(conn, ident)
    requested_session_id = _note_id(values.get("study_session_id"), "Sessão de estudo")
    effective_session_id = requested_session_id or current["study_session_id"]
    if not effective_session_id:
        raise DomainError("Informe a sessão concluída antes de finalizar a anotação.")
    _note_relationships(
        conn,
        current["study_subject_id"],
        current["topic_id"],
        current["planned_session_id"],
        effective_session_id,
    )
    if current["status"] == "final":
        if requested_session_id and requested_session_id != current["study_session_id"]:
            raise DomainError("A anotação já foi finalizada com outra sessão.", 409, "note_finalized")
        return current
    # A condição no UPDATE faz com que dois cliques quase simultâneos não possam
    # transformar o mesmo rascunho em duas finalizações diferentes.
    updated = conn.execute(
        "UPDATE anotacoes_estudo SET status='final',study_session_id=?,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=? AND status='draft'",
        (effective_session_id, ident),
    ).rowcount
    if not updated:
        fresh = note_detail(conn, ident)
        if fresh["status"] == "final" and (not requested_session_id or requested_session_id == fresh["study_session_id"]):
            return fresh
        raise DomainError("A anotação já foi finalizada com outra sessão.", 409, "note_finalized")
    return note_detail(conn, ident)


def delete_note(conn, ident):
    note = note_detail(conn, ident)
    if note["status"] != "draft":
        raise DomainError("Anotações finalizadas não podem ser descartadas por esta ação.", 409, "note_finalized")
    repo.delete(conn, "anotacoes_estudo", ident)


def notes(conn, study_subject_id=None, topic_id=None, start=None, end=None, status=None):
    clauses, params = [], []
    if study_subject_id not in (None, ""):
        subject_id = _note_id(study_subject_id, "Matéria")
        _get(conn, "materias_estudo", subject_id)
        clauses.append("n.study_subject_id=?"); params.append(subject_id)
    if topic_id not in (None, ""):
        topic_ident = _note_id(topic_id, "Tópico")
        _get(conn, "topicos", topic_ident)
        clauses.append("n.topic_id=?"); params.append(topic_ident)
    if start:
        _date(start, "Data inicial")
        clauses.append("substr(n.created_at,1,10)>=?"); params.append(start)
    if end:
        _date(end, "Data final")
        clauses.append("substr(n.created_at,1,10)<=?"); params.append(end)
    if start and end and start > end:
        raise DomainError("A data final não pode ser anterior à data inicial.")
    if status and status != "all":
        if status not in ("draft", "final"):
            raise DomainError("Filtro de status de anotações inválido.")
        clauses.append("n.status=?"); params.append(status)
    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    sql, query_params = _note_select(where + " ORDER BY n.updated_at DESC,n.id DESC", tuple(params))
    return repo.many(conn, sql, query_params)


def _note_tags_for_export(value):
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def _yaml_string(value):
    # JSON quoted strings are valid YAML scalars and escape line breaks/quotes safely.
    return json.dumps(str(value), ensure_ascii=False)


def _safe_note_filename_part(value, fallback):
    ascii_value = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii").lower()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_value).strip("-")
    return (slug or fallback)[:56].rstrip("-") or fallback


def note_markdown(conn, ident):
    note = note_detail(conn, ident)
    tags = _note_tags_for_export(note["tags"])
    lines = [
        "---",
        f"title: {_yaml_string(note['title'])}",
        f"date: {str(note['created_at'])[:10]}",
        f"subject: {_yaml_string(note['subject_name'])}",
        f"topic: {_yaml_string(note['topic_name'])}" if note["topic_name"] else "topic: null",
    ]
    if tags:
        lines.append("tags:")
        lines.extend(f"  - {_yaml_string(tag)}" for tag in tags)
    else:
        lines.append("tags: []")
    lines.extend([
        f"session_id: {note['study_session_id']}" if note["study_session_id"] else "session_id: null",
        "---",
        "",
        note["content_markdown"],
    ])
    filename = f"{int(note['id']):06d}-{_safe_note_filename_part(note['subject_name'], 'materia')}-{_safe_note_filename_part(note['title'], 'anotacao')}.md"
    return {"note": note, "filename": filename, "markdown": "\n".join(lines)}


def notes_for_obsidian_export(conn, identifiers):
    if not isinstance(identifiers, list) or not identifiers:
        raise DomainError("Selecione ao menos uma anotação para exportar.")
    selected, seen = [], set()
    for value in identifiers:
        ident = _note_id(value, "Anotação")
        if ident is None:
            raise DomainError("Anotação inválida.")
        if ident not in seen:
            seen.add(ident)
            selected.append(note_markdown(conn, ident))
    return selected


EVALUATION_TYPES = ("exam", "assignment", "activity", "project", "exercise_list", "recovery", "other")
EVALUATION_STATUSES = ("scheduled", "delivered", "corrected", "cancelled")


def _evaluation_data(values, current=None):
    data = _fields(values, {"title", "type", "date", "delivery_date", "weight", "max_score", "score", "status", "notes"})
    for key in ("delivery_date", "weight", "max_score", "score", "notes"):
        if data.get(key) == "": data[key] = None
    candidate = {**(current or {}), **data}
    if "title" in data or current is None: data["title"] = _need(candidate.get("title"), "Nome da avaliação")
    if "type" in data or current is None:
        kind = candidate.get("type", "exam")
        if kind not in EVALUATION_TYPES: raise DomainError("Tipo de avaliação inválido.")
        data["type"] = kind
    if "status" in data or current is None:
        status = candidate.get("status", "scheduled")
        if status == "completed": status = "corrected"  # compatibilidade com clientes antigos
        if status not in EVALUATION_STATUSES: raise DomainError("Status de avaliação inválido.")
        data["status"] = status
    if "date" in data or current is None:
        data["date"] = _need(candidate.get("date"), "Data prevista")
    _date(candidate.get("date"), "Data prevista")
    if candidate.get("delivery_date"):
        _date(candidate["delivery_date"], "Data de entrega")
        if candidate["delivery_date"] < candidate["date"]:
            raise DomainError("A data de entrega não pode ser anterior à data prevista.")
    for key, label in (("weight", "Peso"), ("max_score", "Nota máxima"), ("score", "Nota obtida")):
        if key in data:
            data[key] = _optional_number(data[key], label)
    candidate = {**(current or {}), **data}
    if candidate.get("max_score") is not None and candidate.get("max_score") <= 0:
        raise DomainError("Nota máxima deve ser maior que zero.")
    if candidate.get("score") is not None and candidate.get("max_score") is not None and candidate["score"] > candidate["max_score"]:
        raise DomainError("A nota obtida não pode ser maior que a nota máxima.")
    return data


def _evaluation_select(where="", params=()):
    sql = """
        SELECT e.*,COALESCE(d.name,sd.name,s.personal_name) subject_name,
          COALESCE(e.curriculum_subject_id,s.curriculum_subject_id) effective_curriculum_subject_id
        FROM avaliacoes e
        LEFT JOIN materias_estudo s ON s.id=e.study_subject_id
        LEFT JOIN disciplinas_grade sd ON sd.id=s.curriculum_subject_id
        LEFT JOIN disciplinas_grade d ON d.id=e.curriculum_subject_id
    """ + where
    return sql, params


def _evaluation_topics(conn, evaluation_id):
    return repo.many(conn, "SELECT t.* FROM avaliacao_topicos l JOIN topicos t ON t.id=l.topic_id WHERE l.evaluation_id=? ORDER BY COALESCE(t.unit,''),t.sort_order,t.name", (evaluation_id,))


def _evaluation_detail(conn, ident):
    sql, params = _evaluation_select(" WHERE e.id=?", (ident,))
    item = repo.one(conn, sql, params)
    if not item: raise DomainError("Avaliação não encontrada.", 404)
    item["contents"] = _evaluation_topics(conn, ident)
    return item


def evaluations(conn, study_id=None, curriculum_id=None):
    clauses, params = [], []
    if study_id:
        clauses.append("e.study_subject_id=?"); params.append(study_id)
    if curriculum_id:
        clauses.append("COALESCE(e.curriculum_subject_id,s.curriculum_subject_id)=?"); params.append(curriculum_id)
    sql, query_params = _evaluation_select((" WHERE " + " AND ".join(clauses) if clauses else "") + " ORDER BY e.date,e.id", tuple(params))
    rows = repo.many(conn, sql, query_params)
    for row in rows: row["contents"] = _evaluation_topics(conn, row["id"])
    return rows


def create_evaluation(conn, values):
    study_id = values.get("study_subject_id")
    curriculum_id = values.get("curriculum_subject_id")
    study = None
    if study_id not in (None, ""):
        study = _get(conn, "materias_estudo", int(study_id))
        curriculum_id = curriculum_id or study.get("curriculum_subject_id")
    if curriculum_id not in (None, ""):
        curriculum_id = int(curriculum_id)
        curriculum = _get(conn, "disciplinas_grade", curriculum_id)
        _active_formation(conn, curriculum["formation_id"])
    if not study and not curriculum_id:
        raise DomainError("Selecione a disciplina ou o estudo da avaliação.")
    data = _evaluation_data(values)
    data.update({"study_subject_id": int(study_id) if study_id not in (None, "") else None, "curriculum_subject_id": curriculum_id})
    ident = repo.insert(conn, "avaliacoes", data)
    for topic_id in values.get("topic_ids", values.get("content_ids", [])):
        topic = _get(conn, "topicos", topic_id)
        if study and not _topic_matches_study(conn, topic, study["id"]):
            raise DomainError("Todos os conteúdos precisam pertencer à matéria da avaliação.")
        if curriculum_id and topic.get("curriculum_subject_id") != curriculum_id:
            raise DomainError("Todos os conteúdos precisam pertencer à disciplina da avaliação.")
        conn.execute("INSERT INTO avaliacao_topicos(evaluation_id,topic_id) VALUES (?,?)", (ident, topic_id))
    saved = _evaluation_detail(conn, ident)
    if curriculum_id: _event(conn, curriculum_id, "evaluation", f"Avaliação cadastrada: {saved['title']}")
    return saved


def update_evaluation(conn, ident, values):
    current = _evaluation_detail(conn, ident)
    data = _evaluation_data(values, current)
    repo.update(conn, "avaliacoes", ident, data)
    if "topic_ids" in values or "content_ids" in values:
        ids = values.get("topic_ids", values.get("content_ids", []))
        if not isinstance(ids, list): raise DomainError("Os conteúdos da avaliação devem ser uma lista.")
        conn.execute("DELETE FROM avaliacao_topicos WHERE evaluation_id=?", (ident,))
        for topic_id in ids:
            topic = _get(conn, "topicos", topic_id)
            curriculum_id = current.get("effective_curriculum_subject_id")
            if curriculum_id and topic.get("curriculum_subject_id") != curriculum_id:
                raise DomainError("O conteúdo precisa pertencer à disciplina da avaliação.")
            conn.execute("INSERT INTO avaliacao_topicos(evaluation_id,topic_id) VALUES (?,?)", (ident, topic_id))
    saved = _evaluation_detail(conn, ident)
    if saved.get("effective_curriculum_subject_id"):
        _event(conn, saved["effective_curriculum_subject_id"], "evaluation", f"Avaliação atualizada: {saved['title']}")
    return saved


def delete_evaluation(conn, ident):
    current = _evaluation_detail(conn, ident)
    repo.delete(conn, "avaliacoes", ident)
    if current.get("effective_curriculum_subject_id"):
        _event(conn, current["effective_curriculum_subject_id"], "evaluation", f"Avaliação excluída: {current['title']}")


def evaluation_summary(conn, curriculum_id):
    item = _get(conn, "disciplinas_grade", curriculum_id)
    rows = evaluations(conn, curriculum_id=curriculum_id)
    today = _today()
    scored = [row for row in rows if row.get("score") is not None and row.get("max_score")]
    percentages = [row["score"] * 100 / row["max_score"] for row in scored if row["max_score"]]
    weighted = [row for row in scored if row.get("weight") is not None and row.get("max_score")]
    total_weight = sum(float(row["weight"]) for row in weighted)
    weighted_percent = (sum((row["score"] * 100 / row["max_score"]) * float(row["weight"]) for row in weighted) / total_weight) if weighted and total_weight else None
    return {
        "evaluations": rows,
        "next": [row for row in rows if row["status"] not in {"cancelled", "corrected"} and row["date"] >= today],
        "overdue": [row for row in rows if row["status"] not in {"cancelled", "corrected"} and (row.get("delivery_date") or row["date"]) < today],
        "simple_average_percent": round(sum(percentages) / len(percentages), 1) if percentages else None,
        "weighted_average_percent": round(weighted_percent, 1) if weighted_percent is not None else None,
        "minimum_grade": item.get("minimum_grade"),
    }


def _clock_minutes(value):
    try:
        parsed = datetime.strptime(str(value), "%H:%M")
    except ValueError as error:
        raise DomainError("Horário deve usar HH:MM.") from error
    return parsed.hour * 60 + parsed.minute


def _availability_data(values):
    weekday = int(_need(values.get("weekday"), "Dia"))
    start_time, end_time = _need(values.get("start_time"), "Hora inicial"), _need(values.get("end_time"), "Hora final")
    if not 0 <= weekday <= 6 or _clock_minutes(start_time) >= _clock_minutes(end_time):
        raise DomainError("Faixa de disponibilidade inválida.")
    return {"weekday":weekday, "start_time":start_time, "end_time":end_time, "enabled":1 if values.get("enabled",1) not in (False,0,"0","false") else 0}


def availability(conn): return repo.many(conn,"SELECT * FROM disponibilidades_semanais ORDER BY weekday,start_time")
def set_availability(conn, values):
    data = _availability_data(values)
    try: ident=repo.insert(conn,"disponibilidades_semanais",data)
    except sqlite3.IntegrityError as error: raise DomainError("Esta faixa se sobrepõe a uma disponibilidade existente.",409) from error
    return _get(conn,"disponibilidades_semanais",ident)


def update_availability(conn, ident, values):
    current = _get(conn,"disponibilidades_semanais",ident)
    data = _availability_data({**current, **_fields(values,{"weekday","start_time","end_time","enabled"})})
    try: repo.update(conn,"disponibilidades_semanais",ident,data)
    except sqlite3.IntegrityError as error: raise DomainError("Esta faixa se sobrepõe a uma disponibilidade existente.",409) from error
    return _get(conn,"disponibilidades_semanais",ident)


def set_availability_batch(conn, values):
    weekdays = values.get("weekdays")
    if not isinstance(weekdays, list) or not weekdays: raise DomainError("Selecione ao menos um dia.")
    days = sorted({int(day) for day in weekdays})
    if any(day < 0 or day > 6 for day in days): raise DomainError("Dia da semana inválido.")
    mode = values.get("mode", "append")
    if mode not in ("append", "replace"): raise DomainError("Modo de aplicação inválido.")
    item = _availability_data({**values, "weekday":days[0]})
    try:
        if mode == "replace": conn.execute(f"DELETE FROM disponibilidades_semanais WHERE weekday IN ({','.join('?' for _ in days)})", days)
        created = [_get(conn,"disponibilidades_semanais",repo.insert(conn,"disponibilidades_semanais",{**item,"weekday":day})) for day in days]
    except sqlite3.IntegrityError as error: raise DomainError("Uma faixa se sobrepõe a outra já cadastrada; nada foi alterado.",409) from error
    return {"mode":mode,"items":created}


def copy_availability(conn, values):
    source = int(_need(values.get("source_weekday"), "Dia de origem")); targets = values.get("target_weekdays")
    if not isinstance(targets, list) or not targets: raise DomainError("Selecione ao menos um dia de destino.")
    targets = sorted({int(day) for day in targets if int(day) != source})
    source_items = repo.many(conn,"SELECT * FROM disponibilidades_semanais WHERE weekday=? ORDER BY start_time",(source,))
    if not source_items: raise DomainError("O dia de origem não tem faixas para copiar.",404)
    try:
        if values.get("replace_existing") in (True,1,"1","true"): conn.execute(f"DELETE FROM disponibilidades_semanais WHERE weekday IN ({','.join('?' for _ in targets)})",targets)
        created = [_get(conn,"disponibilidades_semanais",repo.insert(conn,"disponibilidades_semanais",{"weekday":target,"start_time":item["start_time"],"end_time":item["end_time"],"enabled":item["enabled"]})) for target in targets for item in source_items]
    except sqlite3.IntegrityError as error: raise DomainError("A cópia criaria uma sobreposição; nada foi alterado.",409) from error
    return {"items":created}


def availability_exceptions(conn, start=None, end=None):
    clauses, params = [], []
    if start: clauses.append("date>=?"); params.append(start)
    if end: clauses.append("date<=?"); params.append(end)
    return repo.many(conn,"SELECT * FROM excecoes_disponibilidade"+(" WHERE "+" AND ".join(clauses) if clauses else "")+" ORDER BY date,start_time",params)


AVAILABILITY_INTERVAL_KINDS = ("available", "unavailable", "replace")


def _availability_interval_data(values, current=None):
    data = _fields(values, {"start_date", "end_date", "start_time", "end_time", "kind", "all_day"})
    candidate = {**(current or {}), **data}
    start = _need(candidate.get("start_date"), "Data inicial da disponibilidade")
    end = _need(candidate.get("end_date"), "Data final da disponibilidade")
    start_day = _date(start, "Data inicial da disponibilidade")
    end_day = _date(end, "Data final da disponibilidade")
    if end_day < start_day:
        raise DomainError("A data final da disponibilidade não pode ser anterior à inicial.")
    kind = str(candidate.get("kind") or "available")
    if kind not in AVAILABILITY_INTERVAL_KINDS:
        raise DomainError("Tipo de disponibilidade por intervalo inválido.")
    all_day = _confirmed(candidate.get("all_day"))
    if all_day:
        if kind != "unavailable":
            raise DomainError("Somente uma indisponibilidade pode ocupar o dia inteiro.")
        return {"start_date": start_day.isoformat(), "end_date": end_day.isoformat(), "start_time": None, "end_time": None, "kind": kind, "all_day": 1}
    start_time = _need(candidate.get("start_time"), "Hora inicial da disponibilidade")
    end_time = _need(candidate.get("end_time"), "Hora final da disponibilidade")
    if _clock_minutes(start_time) >= _clock_minutes(end_time):
        raise DomainError("Faixa de disponibilidade por intervalo inválida.")
    return {"start_date": start_day.isoformat(), "end_date": end_day.isoformat(), "start_time": start_time, "end_time": end_time, "kind": kind, "all_day": 0}


def availability_intervals(conn, start=None, end=None):
    clauses, params = [], []
    if start:
        selected = _date(start, "Início do filtro")
        clauses.append("end_date>=?"); params.append(selected.isoformat())
    if end:
        selected = _date(end, "Fim do filtro")
        clauses.append("start_date<=?"); params.append(selected.isoformat())
    return repo.many(
        conn,
        "SELECT * FROM disponibilidades_intervalos" + (" WHERE " + " AND ".join(clauses) if clauses else "") + " ORDER BY start_date,end_date,kind,start_time,id",
        params,
    )


def set_availability_interval(conn, values):
    data = _availability_interval_data(values)
    return _get(conn, "disponibilidades_intervalos", repo.insert(conn, "disponibilidades_intervalos", data))


def update_availability_interval(conn, ident, values):
    current = _get(conn, "disponibilidades_intervalos", ident)
    data = _availability_interval_data(values, current)
    repo.update(conn, "disponibilidades_intervalos", ident, data)
    return _get(conn, "disponibilidades_intervalos", ident)


def reset_availability_date(conn, selected_date):
    """Remove somente regras criadas para uma data, sem tocar na recorrência.

    Uma regra que cobre um período maior não é apagada por acidente: nesse caso
    a resposta informa que a alteração de intervalo ainda se aplica e a pessoa
    pode editá-la conscientemente.
    """
    day = _date(selected_date, "Data")
    legacy = conn.execute("DELETE FROM excecoes_disponibilidade WHERE date=?", (day.isoformat(),)).rowcount
    ranges = conn.execute(
        "DELETE FROM disponibilidades_intervalos WHERE start_date=? AND end_date=?",
        (day.isoformat(), day.isoformat()),
    ).rowcount
    inherited_ranges = repo.many(
        conn,
        "SELECT * FROM disponibilidades_intervalos WHERE start_date<? AND end_date>? ORDER BY start_date,id",
        (day.isoformat(), day.isoformat()),
    )
    return {
        "date": day.isoformat(), "removed_exceptions": legacy + ranges,
        "weekly_restored": not inherited_ranges,
        "inherited_interval_rules": inherited_ranges,
        "windows": availability_windows(conn, day),
    }


def availability_day(conn, selected_date):
    day = _date(selected_date, "Data")
    recurring = [row for row in availability(conn) if row["enabled"] and row["weekday"] == day.weekday()]
    legacy = availability_exceptions(conn, day.isoformat(), day.isoformat())
    ranges = availability_intervals(conn, day.isoformat(), day.isoformat())
    return {
        "date": day.isoformat(), "weekday": day.weekday(), "recurring": recurring,
        "exceptions": legacy, "intervals": ranges, "windows": availability_windows(conn, day),
        "uses_weekly_default": not any(row["kind"] == "replace" for row in ranges),
    }


def set_availability_exception(conn, values):
    data = _fields(values,{"date","start_time","end_time","kind"}); data.update({"date":_need(data.get("date"),"Data"),"start_time":_need(data.get("start_time"),"Hora inicial"),"end_time":_need(data.get("end_time"),"Hora final"),"kind":data.get("kind","unavailable")})
    if data["kind"] not in ("available","unavailable") or _clock_minutes(data["start_time"]) >= _clock_minutes(data["end_time"]): raise DomainError("Exceção de disponibilidade inválida.")
    return _get(conn,"excecoes_disponibilidade",repo.insert(conn,"excecoes_disponibilidade",data))


def update_availability_exception(conn, ident, values):
    current = _get(conn,"excecoes_disponibilidade",ident)
    data = {**current, **_fields(values,{"date","start_time","end_time","kind"})}
    validated = {key:data[key] for key in ("date","start_time","end_time","kind")}
    if validated["kind"] not in ("available","unavailable") or _clock_minutes(validated["start_time"]) >= _clock_minutes(validated["end_time"]): raise DomainError("Exceção de disponibilidade inválida.")
    repo.update(conn,"excecoes_disponibilidade",ident,validated); return _get(conn,"excecoes_disponibilidade",ident)


def _merge(intervals):
    result=[]
    for start,end in sorted(intervals):
        if result and start <= result[-1][1]: result[-1]=(result[-1][0],max(result[-1][1],end))
        else: result.append((start,end))
    return result


def _subtract(intervals, blocks):
    result=intervals
    for block_start,block_end in blocks:
        next_result=[]
        for start,end in result:
            if block_end <= start or block_start >= end: next_result.append((start,end))
            else:
                if start < block_start: next_result.append((start,block_start))
                if block_end < end: next_result.append((block_end,end))
        result=next_result
    return result


def _take_intervals(intervals, minutes):
    """Mantém somente o começo das janelas até o orçamento informado."""
    remaining = max(0, int(minutes or 0))
    result = []
    for start, end in intervals:
        if remaining <= 0:
            break
        amount = min(end - start, remaining)
        if amount > 0:
            result.append((start, start + amount))
            remaining -= amount
    return result


def _allocatable_minutes_with_breaks(intervals, preferences):
    """Quanto das faixas pode virar estudo respeitando blocos e pausas.

    O cálculo não inventa uma pausa no fim da faixa. Com 14:00–17:30, blocos
    preferidos de 50 min e pausa de 10 min, por exemplo, o resultado é
    50 + 50 + 50 + 30 = 180 min de estudo e 30 min de pausa.
    """
    pause = max(0, int(preferences.get("planning_break_minutes") or 0))
    preferred = max(1, int(preferences.get("default_session_minutes") or 50))
    minimum = max(1, int(preferences.get("minimum_session_minutes") or 25))
    maximum = max(minimum, int(preferences.get("maximum_session_minutes") or 120))
    total = 0
    for left, right in intervals:
        remaining = max(0, right - left)
        while remaining >= minimum:
            duration = min(preferred, maximum, remaining)
            if duration < minimum:
                break
            total += duration
            rest = remaining - duration
            # Só reserva pausa se ainda existir um bloco mínimo depois dela.
            if rest < pause + minimum:
                break
            remaining = rest - pause
    return total


def _is_future_planned_block(row, now=None):
    """Um bloco de hoje cujo horário já passou não é esforço futuro alocado."""
    now = now or _local_now()
    try:
        day = _date(row.get("scheduled_date"), "Data do bloco")
    except DomainError:
        return False
    if day > now.date():
        return True
    if day < now.date():
        return False
    if not row.get("start_time"):
        # Bloco flutuante do dia ainda exige decisão explícita; não o descartamos
        # silenciosamente só porque não possui uma hora fixa.
        return True
    return _clock_minutes(row["start_time"]) + int(row.get("planned_duration_minutes") or 0) > now.hour * 60 + now.minute


def _nonnegative_setting_minutes(values, key):
    raw = values.get(key)
    if raw in (None, ""):
        return 0
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return 0


def availability_windows(conn, current):
    """Resolve recorrência, período e exceção de data em uma única agenda.

    Ordem de composição: semanal → intervalo de substituição/adição → exceções
    datadas legadas. Indisponibilidades são aplicadas por último, portanto uma
    marcação de dia inteiro sempre prevalece sobre qualquer faixa disponível.
    """
    recurring = [(_clock_minutes(item["start_time"]), _clock_minutes(item["end_time"])) for item in availability(conn) if item["enabled"] and item["weekday"] == current.weekday()]
    exceptions = availability_exceptions(conn, current.isoformat(), current.isoformat())
    intervals = availability_intervals(conn, current.isoformat(), current.isoformat())
    replacement = [(_clock_minutes(item["start_time"]), _clock_minutes(item["end_time"])) for item in intervals if item["kind"] == "replace" and not item["all_day"]]
    additions = [(_clock_minutes(item["start_time"]), _clock_minutes(item["end_time"])) for item in intervals if item["kind"] == "available" and not item["all_day"]]
    legacy_additions = [(_clock_minutes(item["start_time"]), _clock_minutes(item["end_time"])) for item in exceptions if item["kind"] == "available"]
    windows = _merge((replacement if replacement else recurring) + additions + legacy_additions)
    blocked = [(_clock_minutes(item["start_time"]), _clock_minutes(item["end_time"])) for item in intervals if item["kind"] == "unavailable" and not item["all_day"]]
    blocked += [(_clock_minutes(item["start_time"]), _clock_minutes(item["end_time"])) for item in exceptions if item["kind"] == "unavailable"]
    if any(item["kind"] == "unavailable" and item["all_day"] for item in intervals):
        blocked.append((0, 24 * 60))
    return _subtract(windows, _merge(blocked))


def _with_planned_topic_context(conn, rows):
    fields = (
        "study_subject_id", "curriculum_subject_id", "group_id", "name", "description", "unit", "status",
        "mastery", "manual_mastery", "difficulty", "estimated_minutes", "effort_weight", "observations", "review_requested",
        "sort_order", "started_at", "completed_at", "last_session_date", "archived_at", "created_at", "updated_at",
    )
    # ``p.status`` é o estado do bloco; ``t.status`` é o estado do tópico.
    # Os aliases evitam que a chave homônima do SQLite faça o planejado parecer
    # um tópico "planned" e corrompa as métricas exibidas em Hoje/Planejamento.
    topic_rows = [
        {"id": row["topic_id"], **{key: row.get(f"topic_source_{key}") for key in fields}}
        for row in rows if row.get("topic_id") and row.get("topic_record_id")
    ]
    metrics = {row["id"]: row for row in _topic_metrics_rows(conn, topic_rows)}
    for row in rows:
        metric = metrics.get(row.get("topic_id"))
        if metric:
            row.update({
                "topic_progress_percent": metric.get("effort_progress_percent"),
                "topic_remaining_minutes": metric.get("remaining_minutes"),
                "topic_real_minutes": metric.get("real_minutes"),
                "topic_future_planned_minutes": metric.get("future_planned_minutes"),
                "topic_status": metric.get("status"),
            })
        row.pop("topic_record_id", None)
        for key in fields:
            row.pop(f"topic_source_{key}", None)
    return rows


def planned(conn,start,end):
    sql="""SELECT p.*,COALESCE(s.personal_name,d.name) subject_name,t.id topic_record_id,t.name topic_name,
        t.study_subject_id topic_source_study_subject_id,t.curriculum_subject_id topic_source_curriculum_subject_id,
        t.group_id topic_source_group_id,t.name topic_source_name,t.description topic_source_description,
        t.unit topic_source_unit,t.status topic_source_status,t.mastery topic_source_mastery,
        t.manual_mastery topic_source_manual_mastery,t.difficulty topic_source_difficulty,
        t.estimated_minutes topic_source_estimated_minutes,t.effort_weight topic_source_effort_weight,
        t.observations topic_source_observations,t.review_requested topic_source_review_requested,
        t.sort_order topic_source_sort_order,t.started_at topic_source_started_at,
        t.completed_at topic_source_completed_at,t.last_session_date topic_source_last_session_date,
        t.archived_at topic_source_archived_at,t.created_at topic_source_created_at,t.updated_at topic_source_updated_at,
        f.name formation_name,d.deadline_date
        FROM sessoes_planejadas p JOIN materias_estudo s ON s.id=p.study_subject_id
        LEFT JOIN disciplinas_grade d ON d.id=s.curriculum_subject_id
        LEFT JOIN formacoes f ON f.id=COALESCE(s.related_formation_id,d.formation_id)
        LEFT JOIN topicos t ON t.id=p.topic_id
        WHERE p.scheduled_date BETWEEN ? AND ? AND p.status='planned' AND s.archived_at IS NULL AND s.status<>'archived'
          AND (d.id IS NULL OR d.archived_at IS NULL) AND (f.id IS NULL OR f.archived_at IS NULL)
        ORDER BY p.scheduled_date,p.start_time"""
    return _with_planned_topic_context(conn, repo.many(conn,sql,(start,end)))


def planned_detail(conn, ident):
    row = repo.one(conn,"""SELECT p.*,COALESCE(s.personal_name,d.name) subject_name,t.id topic_record_id,t.name topic_name,
        t.study_subject_id topic_source_study_subject_id,t.curriculum_subject_id topic_source_curriculum_subject_id,
        t.group_id topic_source_group_id,t.name topic_source_name,t.description topic_source_description,
        t.unit topic_source_unit,t.status topic_source_status,t.mastery topic_source_mastery,
        t.manual_mastery topic_source_manual_mastery,t.difficulty topic_source_difficulty,
        t.estimated_minutes topic_source_estimated_minutes,t.effort_weight topic_source_effort_weight,
        t.observations topic_source_observations,t.review_requested topic_source_review_requested,
        t.sort_order topic_source_sort_order,t.started_at topic_source_started_at,
        t.completed_at topic_source_completed_at,t.last_session_date topic_source_last_session_date,
        t.archived_at topic_source_archived_at,t.created_at topic_source_created_at,t.updated_at topic_source_updated_at,
        f.name formation_name,d.deadline_date
        FROM sessoes_planejadas p JOIN materias_estudo s ON s.id=p.study_subject_id
        LEFT JOIN disciplinas_grade d ON d.id=s.curriculum_subject_id
        LEFT JOIN formacoes f ON f.id=COALESCE(s.related_formation_id,d.formation_id)
        LEFT JOIN topicos t ON t.id=p.topic_id WHERE p.id=?""",(ident,))
    if not row: raise DomainError("Sessão planejada não encontrada.",404)
    return _with_planned_topic_context(conn, [row])[0]


def delete_planned_day(conn, scheduled_date):
    """Remove, em uma única operação, os blocos ativos de uma data específica."""
    raw_date = str(scheduled_date)
    selected_date = _date(raw_date, "Data do planejamento")
    # ``date.fromisoformat`` também aceita a forma básica (AAAAMMDD), mas a rota
    # pública precisa manter um contrato inequívoco para datas.
    if raw_date != selected_date.isoformat():
        raise DomainError("Data do planejamento deve usar AAAA-MM-DD.")
    rows = conn.execute(
        "DELETE FROM sessoes_planejadas "
        "WHERE scheduled_date=? AND status='planned' "
        "RETURNING id",
        (selected_date.isoformat(),),
    ).fetchall()
    ids = sorted(row["id"] for row in rows)
    return {"deleted": len(ids), "ids": ids}


def _nearest_available_slots(conn, selected, duration, limit=3):
    values = []
    for offset in range(0, 15):
        current = selected + timedelta(days=offset)
        for start, end in availability_windows(conn, current):
            if end - start >= duration:
                values.append({"scheduled_date": current.isoformat(), "start_time": f"{start // 60:02d}:{start % 60:02d}"})
                if len(values) >= limit:
                    return values
    return values


def _assert_planned_slot(conn, candidate, ignore_id=None, *, validate_availability=False, allow_outside_availability=False):
    """Garante que nenhum bloco ativo ocupe o mesmo intervalo no mesmo dia."""
    selected = _date(candidate["scheduled_date"], "Data do planejamento")
    start_time = candidate.get("start_time")
    if not start_time:
        raise DomainError("Informe o horário do bloco para evitar sobreposição.", 400, "planned_time_required")
    start = _clock_minutes(start_time)
    end = start + int(candidate["planned_duration_minutes"])
    if end > 24 * 60:
        raise DomainError("O bloco não pode terminar depois da meia-noite.")
    rows = repo.many(conn, "SELECT id,start_time,planned_duration_minutes FROM sessoes_planejadas WHERE scheduled_date=? AND status='planned' AND start_time IS NOT NULL" + (" AND id<>?" if ignore_id else ""), (selected.isoformat(), ignore_id) if ignore_id else (selected.isoformat(),))
    for item in rows:
        other_start = _clock_minutes(item["start_time"])
        other_end = other_start + int(item["planned_duration_minutes"])
        if start < other_end and end > other_start:
            raise DomainError("Este horário se sobrepõe a outro bloco planejado.", 409, "planned_overlap", details={"conflict_id": item["id"]})
    if validate_availability and not allow_outside_availability:
        fits = any(start >= left and end <= right for left, right in availability_windows(conn, selected))
        if not fits:
            raise DomainError(
                "O bloco está fora da disponibilidade desta data. Confirme uma exceção manual ou escolha outra faixa.",
                409,
                "planned_outside_availability",
                details={"suggested_slots": _nearest_available_slots(conn, selected, int(candidate["planned_duration_minutes"]))},
            )


def create_planned(conn,values,source="manual"):
    study=int(_need(values.get("study_subject_id"),"Matéria")); _assert_study_accessible(conn, study, require_current=True, intent="planning")
    data=_fields(values,{"study_subject_id","topic_id","scheduled_date","start_time","planned_duration_minutes","selection_reason","selection_context"}); data.update({"study_subject_id":study,"scheduled_date":_need(data.get("scheduled_date"),"Data"),"planned_duration_minutes":int(_need(data.get("planned_duration_minutes"),"Duração")),"source":source})
    if data["planned_duration_minutes"] <= 0: raise DomainError("A duração deve ser maior que zero.")
    if data.get("topic_id"):
        topic = _assert_topic_available_for_work(_get(conn,"topicos",data["topic_id"]))
        if not _topic_matches_study(conn, topic, study): raise DomainError("O conteúdo precisa pertencer à matéria selecionada.")
    _assert_planned_slot(conn, data)
    return _get(conn,"sessoes_planejadas",repo.insert(conn,"sessoes_planejadas",data))


def update_planned(conn, ident, values):
    current = planned_detail(conn,ident)
    data = _fields(values,{"study_subject_id","topic_id","scheduled_date","start_time","planned_duration_minutes","status","selection_reason","selection_context"})
    requested_source = values.get("source")
    if requested_source is not None:
        restoring_automatic_source = requested_source == "automatic" and _confirmed(values.get("restore_automatic_source"))
        # A restauração é usada exclusivamente pelo desfazer de uma mudança
        # recém-feita. Ela também é idempotente: se o bloco permaneceu
        # automático, desfazer sua posição não pode falhar por tentar manter
        # a mesma origem.
        if requested_source == "automatic" and restoring_automatic_source and current["source"] in ("automatic", "manual"):
            data["source"] = "automatic"
        elif requested_source != "manual":
            raise DomainError("Um bloco manual não pode voltar a ser automático.", 400, "planned_source_invalid")
        elif current["source"] == "automatic":
            data["source"] = "manual"
        elif current["source"] != "manual":
            raise DomainError("Origem do bloco inválida.", 409, "planned_source_invalid")
    candidate = {**current, **data}
    if candidate["status"] not in ("planned","completed","skipped","rescheduled","cancelled"): raise DomainError("Status de planejamento inválido.")
    if int(candidate["planned_duration_minutes"]) <= 0: raise DomainError("A duração deve ser maior que zero.")
    # Cancelar ou preservar um bloco histórico continua possível mesmo se a
    # disciplina foi encerrada; criar/manter foco planejado exige permissão
    # acadêmica atual.
    if candidate["status"] in {"planned", "completed"}:
        _assert_study_accessible(conn, candidate["study_subject_id"], require_current=True, intent="planning")
    if candidate.get("topic_id") and not _topic_matches_study(conn, _get(conn,"topicos",candidate["topic_id"]), candidate["study_subject_id"]): raise DomainError("O conteúdo precisa pertencer à matéria selecionada.")
    if candidate["status"] == "planned":
        _assert_planned_slot(
            conn, candidate, ident,
            validate_availability=_confirmed(values.get("validate_availability")) or _confirmed(values.get("strict_availability")),
            allow_outside_availability=_confirmed(values.get("allow_outside_availability")),
        )
    if data.get("status") == "completed" and current["status"] != "completed":
        real_session = repo.one(conn, "SELECT id FROM sessoes_estudo WHERE planned_session_id=? LIMIT 1", (ident,))
        if not real_session:
            raise DomainError(
                "Conclua este bloco registrando uma sessão real; marcar a agenda não reduz o esforço.",
                409,
                "planned_completion_requires_session",
            )
    repo.update(conn,"sessoes_planejadas",ident,data); return planned_detail(conn,ident)


def reschedule_planned(conn, ident, values):
    current = planned_detail(conn,ident)
    if current["status"] not in ("planned","skipped"): raise DomainError("Somente uma sessão planejada ou não realizada pode ser reagendada.",409)
    next_item = create_planned(conn,{**current,**_fields(values,{"study_subject_id","topic_id","scheduled_date","start_time","planned_duration_minutes"})},current["source"])
    repo.update(conn,"sessoes_planejadas",ident,{"status":"rescheduled","rescheduled_to_id":next_item["id"]})
    return {"previous":planned_detail(conn,ident),"rescheduled":next_item}


def planning_preferences(conn):
    values = settings(conn)
    duration = int(values.get("default_session_minutes") or 50)
    pause = int(values.get("planning_break_minutes") or 10)
    minimum = int(values.get("minimum_session_minutes") or 25)
    maximum = int(values.get("maximum_session_minutes") or 120)
    if duration <= 0 or pause < 0 or minimum <= 0 or maximum < minimum:
        raise DomainError("As preferências do planejamento são inválidas.")
    return {
        "default_session_minutes": duration, "planning_break_minutes": pause,
        "minimum_session_minutes": minimum, "maximum_session_minutes": maximum,
    }


def _range_dates(start, end):
    cursor = _date(start)
    final = _date(end)
    while cursor <= final:
        yield cursor
        cursor += timedelta(days=1)


def _planned_rows_for_window(conn, start, end):
    return repo.many(conn, """
        SELECT p.* FROM sessoes_planejadas p
        JOIN materias_estudo s ON s.id=p.study_subject_id
        LEFT JOIN disciplinas_grade d ON d.id=s.curriculum_subject_id
        LEFT JOIN formacoes f ON f.id=COALESCE(s.related_formation_id,d.formation_id)
        WHERE p.status='planned' AND p.scheduled_date BETWEEN ? AND ?
          AND s.status<>'archived' AND s.archived_at IS NULL
          AND (d.id IS NULL OR d.archived_at IS NULL)
          AND (f.id IS NULL OR f.archived_at IS NULL)
        ORDER BY p.scheduled_date,p.start_time,p.id
    """, (start, end))


def _planning_windows(conn, start, end):
    """Janelas livres e um demonstrativo de capacidade líquida local.

    ``capacity_minutes`` e ``free_minutes`` permanecem como aliases legados do
    orçamento antes das pausas. Os campos ``net_*`` são a capacidade realmente
    alocável pelo motor, já descontando pausas, descanso, limite diário,
    compromissos e horário atual.
    """
    reserved = defaultdict(list)
    rows = _planned_rows_for_window(conn, start, end)
    now = _local_now()
    for row in rows:
        if row.get("start_time") and _is_future_planned_block(row, now):
            begin = _clock_minutes(row["start_time"])
            reserved[row["scheduled_date"]].append((begin, begin + int(row["planned_duration_minutes"])))
    preference_values = settings(conn)
    preferences = planning_preferences(conn)
    daily_limit = _nonnegative_setting_minutes(preference_values, "daily_max_study_minutes")
    rest_reserve = _nonnegative_setting_minutes(preference_values, "minimum_rest_minutes")
    windows, base_minutes, free_minutes, net_capacity, net_free = {}, 0, 0, 0, 0
    capacity_rows = []
    for current in _range_dates(start, end):
        values = availability_windows(conn, current)
        if current == now.date():
            now_minute = now.hour * 60 + now.minute
            values = [(max(left, now_minute), right) for left, right in values if right > now_minute]
        # No dia atual, períodos já transcorridos não são capacidade futura.
        # Assim, capacidade, livre e déficit usam o mesmo recorte temporal.
        raw_capacity = smart_planning.interval_minutes(values)
        # A reserva de descanso é deliberada: ela evita que a disponibilidade
        # inteira seja tratada como obrigação. O limite diário vale para a
        # soma de blocos existentes e futuros, inclusive os manuais.
        capacity_budget = max(0, raw_capacity - rest_reserve)
        if daily_limit:
            capacity_budget = min(capacity_budget, daily_limit)
        base_minutes += capacity_budget
        free = _subtract(values, reserved[current.isoformat()])
        already_planned = sum(
            int(row.get("planned_duration_minutes") or 0)
            for row in rows
            if row["scheduled_date"] == current.isoformat() and _is_future_planned_block(row, now)
        )
        free = _take_intervals(free, max(0, capacity_budget - already_planned))
        # A prévia é devolvida diretamente por ``/planning/items``. Datas em
        # chaves de dicionário não são serializáveis por JSON, então a mesma
        # forma ISO é usada tanto internamente quanto no contrato público.
        windows[current.isoformat()] = free
        free_minutes += smart_planning.interval_minutes(free)
        day_net_free = _allocatable_minutes_with_breaks(free, preferences)
        day_net_capacity = already_planned + day_net_free
        net_free += day_net_free
        net_capacity += day_net_capacity
        capacity_rows.append({
            "date": current.isoformat(), "gross_capacity_minutes": raw_capacity,
            "reserved_rest_minutes": min(rest_reserve, raw_capacity), "daily_limit_minutes": daily_limit or None,
            "budget_before_breaks_minutes": capacity_budget, "planned_minutes": already_planned,
            "free_before_breaks_minutes": smart_planning.interval_minutes(free),
            "net_capacity_minutes": day_net_capacity, "net_free_minutes": day_net_free,
            "break_minutes": int(preferences.get("planning_break_minutes") or 0),
        })
    planned_rows_future = [row for row in rows if _is_future_planned_block(row, now)]
    past_rows = [row for row in rows if not _is_future_planned_block(row, now)]
    planned_minutes = sum(int(row["planned_duration_minutes"] or 0) for row in planned_rows_future)
    past_unrealized = sum(int(row["planned_duration_minutes"] or 0) for row in past_rows)
    return {
        "windows": windows, "rows": rows, "capacity_rows": capacity_rows,
        "capacity_minutes": base_minutes, "free_minutes": free_minutes, "planned_minutes": planned_minutes,
        "gross_capacity_minutes": sum(row["gross_capacity_minutes"] for row in capacity_rows),
        "reserved_rest_minutes": sum(row["reserved_rest_minutes"] for row in capacity_rows),
        "net_capacity_minutes": net_capacity, "net_free_minutes": net_free,
        "past_unrealized_minutes": past_unrealized,
        "past_unrealized_blocks": [row["id"] for row in past_rows],
    }


def _planning_candidate_rows(conn, formation_id=None, item_id=None, kind=None):
    clauses, params = [], []
    if formation_id not in (None, ""):
        try:
            selected_formation = int(formation_id)
            clauses.append(
                "(COALESCE(s.related_formation_id,d.formation_id)=? OR EXISTS ("
                "SELECT 1 FROM curriculum_study_links sl JOIN disciplinas_grade sd ON sd.id=sl.curriculum_subject_id "
                "WHERE sl.canonical_study_id=s.id AND sd.formation_id=?))"
            )
            params.extend((selected_formation, selected_formation))
        except (TypeError, ValueError) as error:
            raise DomainError("Formação do planejamento é inválida.") from error
    if item_id not in (None, ""):
        try:
            clauses.append("s.id=?")
            params.append(int(item_id))
        except (TypeError, ValueError) as error:
            raise DomainError("Item do planejamento é inválido.") from error
    if kind not in (None, ""):
        if kind not in {"curriculum", "personal"}:
            raise DomainError("Tipo de item do planejamento é inválido.")
        clauses.append("s.origin=?")
        params.append(kind)
    return repo.many(conn, """
        SELECT s.*, d.name curriculum_name,d.code curriculum_code,d.formation_id,d.academic_status,d.review_status,
           d.start_date curriculum_start_date,d.end_date curriculum_end_date,d.deadline_date,
           d.workload_minutes curriculum_workload_minutes,d.required_study_minutes curriculum_required_study_minutes,
           d.priority_base,d.preferred_block_minutes curriculum_preferred_block_minutes,
           d.allowed_weekdays curriculum_allowed_weekdays,d.planning_enabled,d.planning_opt_out,d.minimum_grade,
           d.effort_is_provisional,d.deadline_is_provisional,d.planning_profile_configured_at,
          f.name formation_name,f.status formation_status,f.archived_at formation_archived_at,
          d.archived_at curriculum_archived_at
        FROM materias_estudo s
        LEFT JOIN disciplinas_grade d ON d.id=s.curriculum_subject_id
        LEFT JOIN formacoes f ON f.id=COALESCE(s.related_formation_id,d.formation_id)
        WHERE s.status='active' AND s.archived_at IS NULL
          AND (
            s.origin='personal'
            OR (
              -- A ocorrência de origem continua suficiente para um estudo
              -- curricular comum.
              (d.id IS NOT NULL AND d.archived_at IS NULL AND d.item_type='subject'
               AND f.archived_at IS NULL AND f.status='active'
               AND (d.academic_status='in_progress'
                    OR (d.academic_status='completed' AND d.review_status IN ('queued','in_progress'))))
              -- Um vínculo explícito mantém a demanda canônica disponível
              -- enquanto qualquer outra ocorrência ainda estiver utilizável.
              OR EXISTS (
                SELECT 1
                FROM curriculum_study_links sl
                JOIN disciplinas_grade sd ON sd.id=sl.curriculum_subject_id
                JOIN formacoes sf ON sf.id=sd.formation_id
                WHERE sl.canonical_study_id=s.id
                  AND sd.archived_at IS NULL AND sf.archived_at IS NULL AND sf.status='active'
                  AND sd.item_type='subject' AND sd.academic_status IN ('available','in_progress')
              )
            )
          )
        """ + (" AND " + " AND ".join(clauses) if clauses else "") + " ORDER BY s.created_at", params)


def _ids_clause(values):
    ids = [int(value) for value in values]
    return ("(" + ",".join("?" for _ in ids) + ")", ids) if ids else ("(NULL)", [])


def _minutes_by_study(conn, study_ids, start=None, end=None):
    marks, params = _ids_clause(study_ids)
    clauses = [f"study_subject_id IN {marks}" ]
    if start: clauses.append("date>=?"); params.append(start)
    if end: clauses.append("date<=?"); params.append(end)
    rows = repo.many(conn, "SELECT study_subject_id,COALESCE(SUM(duration_seconds),0)/60 minutes FROM sessoes_estudo WHERE " + " AND ".join(clauses) + " GROUP BY study_subject_id", params)
    return {row["study_subject_id"]: int(row["minutes"] or 0) for row in rows}


def _minutes_by_curriculum(conn, curriculum_ids, start=None, end=None):
    marks, params = _ids_clause(curriculum_ids)
    clauses = [f"s.curriculum_subject_id IN {marks}"]
    if start: clauses.append("x.date>=?"); params.append(start)
    if end: clauses.append("x.date<=?"); params.append(end)
    rows = repo.many(conn, "SELECT s.curriculum_subject_id,COALESCE(SUM(x.duration_seconds),0)/60 minutes FROM sessoes_estudo x JOIN materias_estudo s ON s.id=x.study_subject_id WHERE " + " AND ".join(clauses) + " GROUP BY s.curriculum_subject_id", params)
    return {row["curriculum_subject_id"]: int(row["minutes"] or 0) for row in rows}


def _planned_minutes_by_study(conn, study_ids, start, end):
    marks, params = _ids_clause(study_ids)
    rows = repo.many(conn, f"SELECT study_subject_id,COALESCE(SUM(planned_duration_minutes),0) minutes FROM sessoes_planejadas WHERE study_subject_id IN {marks} AND status='planned' AND scheduled_date BETWEEN ? AND ? GROUP BY study_subject_id", (*params, start, end))
    return {row["study_subject_id"]: int(row["minutes"] or 0) for row in rows}


def _planned_minutes_index(conn, study_ids, start, end, *, future_only=True):
    marks, params = _ids_clause(study_ids)
    rows = repo.many(conn, f"SELECT study_subject_id,scheduled_date,start_time,planned_duration_minutes FROM sessoes_planejadas WHERE study_subject_id IN {marks} AND status='planned' AND scheduled_date BETWEEN ? AND ?", (*params, start, end))
    values = defaultdict(list)
    now = _local_now()
    for row in rows:
        if not future_only or _is_future_planned_block(row, now):
            values[row["study_subject_id"]].append(row)
    return values


def _indexed_planned_minutes(index, study_id, start, end):
    return sum(int(row["planned_duration_minutes"] or 0) for row in index.get(study_id, []) if start <= row["scheduled_date"] <= end)


def _contents_by_owner(conn, study_ids, curriculum_ids, *, future_start=None, future_end=None):
    clauses, params = [], []
    study_marks, study_params = _ids_clause(study_ids)
    curriculum_marks, curriculum_params = _ids_clause(curriculum_ids)
    if study_ids: clauses.append(f"study_subject_id IN {study_marks}"); params.extend(study_params)
    if curriculum_ids: clauses.append(f"curriculum_subject_id IN {curriculum_marks}"); params.extend(curriculum_params)
    if not clauses: return {}, {}
    rows = repo.many(conn, "SELECT * FROM topicos WHERE archived_at IS NULL AND (" + " OR ".join(clauses) + ") ORDER BY CASE status WHEN 'in_progress' THEN 0 WHEN 'not_started' THEN 1 WHEN 'for_review' THEN 2 ELSE 3 END,sort_order,id", params)
    rows = _topic_metrics_rows(conn, rows, future_start=future_start, future_end=future_end)
    by_study, by_curriculum = defaultdict(list), defaultdict(list)
    for row in rows:
        if row.get("study_subject_id") is not None: by_study[row["study_subject_id"]].append(row)
        if row.get("curriculum_subject_id") is not None: by_curriculum[row["curriculum_subject_id"]].append(row)
    return by_study, by_curriculum


def _planning_topic_contents(contents, required, review_mode=False):
    """Prepara somente o saldo de cada tópico para a prévia atual.

    O saldo por tópico limita os blocos propostos, mas o total da disciplina
    continua sendo o limite principal. Assim não há dupla contagem entre a
    estimativa dos tópicos e o esforço pessoal definido na disciplina.
    """
    values = [dict(item) for item in contents]
    statuses = {item["id"]: item.get("status") for item in values}
    for item in values:
        effective = item.get("effective_estimated_minutes")
        actual = int(item.get("real_minutes") or 0)
        future = int(item.get("future_planned_minutes") or 0)
        remaining = max(0, int(effective or 0) - actual - future) if effective is not None else None
        # Passar da estimativa não conclui o tópico. Enquanto ele continuar em
        # andamento, o esforço total da disciplina é o limite e o tópico segue
        # elegível para receber um bloco adicional, sem alterar a estimativa
        # silenciosamente.
        item["planning_remaining_minutes"] = None if (
            item.get("status") == "in_progress" and effective is not None and actual >= int(effective)
        ) else remaining
        item["prerequisites_completed"] = all(statuses.get(prerequisite) == "completed" for prerequisite in item.get("prerequisite_topic_ids", []))
        item["review_mode"] = bool(review_mode)
    return values


def _evaluation_due_sets(conn, study_ids, curriculum_ids):
    today = _today(); threshold = (_local_now().date() + timedelta(days=14)).isoformat()
    study_marks, study_params = _ids_clause(study_ids)
    curriculum_marks, curriculum_params = _ids_clause(curriculum_ids)
    clauses, params = [], []
    if study_ids: clauses.append(f"e.study_subject_id IN {study_marks}"); params.extend(study_params)
    if curriculum_ids: clauses.append(f"e.curriculum_subject_id IN {curriculum_marks}"); params.extend(curriculum_params)
    if not clauses: return set(), set()
    rows = repo.many(conn, "SELECT e.study_subject_id,e.curriculum_subject_id FROM avaliacoes e WHERE e.status NOT IN ('cancelled','corrected') AND e.date BETWEEN ? AND ? AND (" + " OR ".join(clauses) + ")", (today, threshold, *params))
    return {row["study_subject_id"] for row in rows if row["study_subject_id"] is not None}, {row["curriculum_subject_id"] for row in rows if row["curriculum_subject_id"] is not None}


def _planning_evaluations_by_owner(conn, study_ids, curriculum_ids):
    """Carrega avaliações em lote para o DTO, evitando adivinhações no cliente."""
    study_marks, study_params = _ids_clause(study_ids)
    curriculum_marks, curriculum_params = _ids_clause(curriculum_ids)
    clauses, params = [], []
    if study_ids:
        clauses.append(f"e.study_subject_id IN {study_marks}")
        params.extend(study_params)
    if curriculum_ids:
        clauses.append(f"e.curriculum_subject_id IN {curriculum_marks}")
        params.extend(curriculum_params)
    if not clauses:
        return defaultdict(list), defaultdict(list)
    rows = repo.many(
        conn,
        "SELECT e.id,e.study_subject_id,e.curriculum_subject_id,e.title,e.type,e.date,e.delivery_date,e.status "
        "FROM avaliacoes e WHERE (" + " OR ".join(clauses) + ") ORDER BY e.date,e.id",
        params,
    )
    by_study, by_curriculum = defaultdict(list), defaultdict(list)
    for row in rows:
        if row.get("study_subject_id") is not None:
            by_study[row["study_subject_id"]].append(row)
        if row.get("curriculum_subject_id") is not None:
            by_curriculum[row["curriculum_subject_id"]].append(row)
    return by_study, by_curriculum


def _planning_blockers(item):
    messages = {
        "planning_disabled": "Planejamento automático foi desativado para esta disciplina.",
        "invalid_date": "Há uma data inválida no perfil de planejamento.",
        "deadline_expired": "O prazo desta disciplina já passou.",
        "deadline_before_start": "O prazo ocorre antes do início permitido.",
        "starts_after_period": "A disciplina começa após o período analisado.",
        "missing_effort_or_goal": "Ainda falta estimar esforço ou meta semanal.",
        "remaining_effort_zero": "O esforço planejado já foi cumprido em sessões reais.",
        "already_covered_by_future_blocks": "Os blocos futuros já cobrem a demanda restante.",
    }
    state = item.get("planning_state")
    return [] if state == "ready" else [{"code": state, "message": messages.get(state, "Este item ainda não está elegível para planejamento.")}]


def _effective_block_preference(row, curriculum_id, default_minutes):
    """Resolve a duração na ordem estudo atual → grade → preferência global."""
    study_value = row.get("preferred_block_minutes")
    if study_value not in (None, ""):
        return int(study_value), "current_study"
    curriculum_value = row.get("curriculum_preferred_block_minutes") if curriculum_id else None
    if curriculum_value not in (None, ""):
        return int(curriculum_value), "curriculum"
    return int(default_minutes), "global_default"


def _normalise_planning_item(item, row, evaluations):
    """Contrato único para qualquer consumidor de itens planejáveis.

    Os aliases legados continuam na resposta, mas nenhum consumidor precisa mais
    descobrir se prazo/esforço vieram da grade ou de ``materias_estudo``. O
    identificador canônico é a disciplina curricular quando existe; para um
    estudo paralelo ele é o próprio estudo.
    """
    curriculum_id = item.get("curriculum_subject_id")
    canonical_id = curriculum_id or item["study_subject_id"]
    shared_subjects = item.get("shared_curriculum_subjects", [])
    active_shared_subjects = [subject for subject in shared_subjects if subject.get("planning_active")]
    # Em um estudo compartilhado, o estado acadêmico exibido aponta para uma
    # ocorrência que realmente autoriza a demanda. O DTO também mantém cada
    # estado por formação para não os misturar.
    academic_status = row.get("academic_status") if curriculum_id else None
    if active_shared_subjects:
        academic_status = next(
            (subject.get("academic_status") for subject in active_shared_subjects if subject.get("academic_status") == "in_progress"),
            active_shared_subjects[0].get("academic_status"),
        )
    topic_values = item.get("contents", [])
    formations = [
        {"id": subject.get("formation_id"), "name": subject.get("formation_name"), "academic_status": subject.get("academic_status")}
        for subject in shared_subjects
    ]
    if not formations and item.get("formation_id"):
        formations = [{"id": item.get("formation_id"), "name": item.get("formation_name"), "academic_status": academic_status}]
    item.update({
        "subject_id": canonical_id,
        "current_study_id": item["study_subject_id"],
        "canonical_subject_id": canonical_id,
        "canonical_subject_key": f"curriculum:{canonical_id}" if curriculum_id else f"study:{canonical_id}",
        "origin": item.get("kind"),
        "formations": formations,
        "academic_states_by_formation": formations,
        "academic_status": academic_status,
        "study_status": row.get("status"),
        "curricular_workload_minutes": row.get("curriculum_workload_minutes") if curriculum_id else None,
        "estimated_effort_minutes": item.get("required_study_minutes"),
        "personal_effort_minutes": item.get("required_study_minutes"),
        "time_real_minutes": item.get("real_minutes"),
        "time_future_planned_minutes": item.get("future_planned_minutes"),
        "time_remaining_minutes": item.get("remaining_minutes"),
        "time_unallocated_minutes": item.get("unallocated_minutes"),
        "start_date": item.get("effective_start_date"),
        "deadline_date": item.get("deadline"),
        "priority_base": item.get("priority_base"),
        "priority_effective": item.get("priority_effective"),
        "preferred_block_minutes": item.get("preferred_block_minutes"),
        "effective_block_minutes": item.get("effective_block_minutes"),
        "block_duration_source": item.get("block_duration_source"),
        "demand_mode": item.get("demand_mode"),
        "scheduled_in_preview_minutes": item.get("scheduled_in_preview_minutes", 0),
        "deferred_beyond_preview_minutes": item.get("deferred_beyond_preview_minutes", 0),
        "unallocated_due_to_capacity_minutes": item.get("unallocated_due_to_capacity_minutes", 0),
        "allowed_weekdays": item.get("allowed_weekdays") or [],
        "topics": topic_values,
        "evaluations": evaluations,
        "eligible_for_planning": bool(item.get("is_schedulable")),
        "planning_blockers": _planning_blockers(item),
        "effort_is_provisional": bool(row.get("effort_is_provisional")) if curriculum_id else False,
        "deadline_is_provisional": bool(row.get("deadline_is_provisional")) if curriculum_id else False,
        "planning_profile_configured_at": row.get("planning_profile_configured_at") if curriculum_id else None,
    })
    return item


def _item_capacity(windows, start, end, allowed_weekdays=None):
    total, available_days = 0, 0
    for current in _range_dates(start, end):
        if allowed_weekdays and current.weekday() not in allowed_weekdays: continue
        amount = smart_planning.interval_minutes(windows.get(current.isoformat(), []))
        if amount:
            total += amount; available_days += 1
    return total, available_days


def _item_net_capacity(capacity_rows, start, end, allowed_weekdays=None):
    total, available_days = 0, 0
    for row in capacity_rows:
        current = _date(row["date"])
        if current < _date(start) or current > _date(end):
            continue
        if allowed_weekdays and current.weekday() not in allowed_weekdays:
            continue
        amount = int(row.get("net_free_minutes") or 0)
        if amount:
            total += amount
            available_days += 1
    return total, available_days


def _eligible_calendar_days(start, end, allowed_weekdays=None):
    """Dias permitidos para ritmo quando ainda não há janela cadastrada."""
    if _date(end) < _date(start):
        return 0
    return sum(
        1 for current in _range_dates(start, end)
        if not allowed_weekdays or current.weekday() in allowed_weekdays
    )


def _collective_planning_risk(items, capacity_rows, start_day, end_day):
    """Avalia demandas concorrentes contra a mesma capacidade livre.

    O cálculo por item continua útil para explicar uma disciplina, mas não pode
    assumir que cada uma possui todas as tardes livres sozinha. Aqui cada minuto
    de capacidade é contado uma vez no calendário cumulativo.
    """
    ready = [item for item in items if item.get("is_schedulable") and int(item.get("demand_in_period_minutes") or 0) > 0]
    # ``capacity_rows`` pode ter sido calculada para um horizonte maior, pois
    # cada prazo individual precisa dessa projeção. O risco coletivo, porém,
    # responde estritamente ao intervalo solicitado pela prévia.
    capacity_by_day = {
        row["date"]: int(row.get("net_free_minutes") or 0)
        for row in capacity_rows
        if start_day <= _date(row["date"]) <= end_day
    }
    due_by_day = defaultdict(int)
    contributors = defaultdict(list)
    for item in ready:
        deadline, invalid = _optional_date(item.get("deadline_date"))
        due_day = min(deadline, end_day) if deadline and not invalid else end_day
        due_day = max(due_day, start_day)
        demand = int(item.get("demand_in_period_minutes") or 0)
        due_by_day[due_day.isoformat()] += demand
        contributors[due_day.isoformat()].append(item["id"])
    accumulated_capacity = accumulated_demand = 0
    first_deficit = None
    at_risk_ids = set()
    timeline = []
    for current in _range_dates(start_day.isoformat(), end_day.isoformat()):
        key = current.isoformat()
        accumulated_capacity += capacity_by_day.get(key, 0)
        accumulated_demand += due_by_day.get(key, 0)
        deficit = max(0, accumulated_demand - accumulated_capacity)
        timeline.append({"date": key, "capacity_minutes": accumulated_capacity, "demand_minutes": accumulated_demand, "deficit_minutes": deficit})
        if deficit and first_deficit is None:
            first_deficit = key
        if deficit:
            for due_key, ids in contributors.items():
                if due_key <= key:
                    at_risk_ids.update(ids)
    total_capacity = sum(capacity_by_day.values())
    total_demand = sum(int(item.get("demand_in_period_minutes") or 0) for item in ready)
    deficit = max(0, total_demand - total_capacity)
    status = "impossible" if deficit else ("at_risk" if first_deficit else "on_track")
    if deficit:
        message = f"As demandas compartilham a mesma agenda e faltam {deficit} min no período."
    elif first_deficit:
        message = "Há disputa de horários antes de um prazo; reveja disponibilidade ou a distribuição."
    else:
        message = "A capacidade compartilhada comporta as demandas deste período."
    return {
        "status": status, "message": message, "demand_minutes": total_demand,
        "capacity_minutes": total_capacity, "deficit_minutes": deficit,
        "surplus_minutes": total_capacity - total_demand, "first_deficit_date": first_deficit,
        "at_risk_item_ids": sorted(at_risk_ids), "timeline": timeline,
        "suggestions": ([
            {"action": "add_availability", "minutes": deficit, "label": f"Adicionar ao menos {deficit} min de disponibilidade."},
            {"action": "extend_deadlines", "label": "Revisar os prazos que concorrem pela mesma semana."},
        ] if deficit else []),
    }


def _first_feasible_from_windows(item, start, remaining, windows, end):
    """Calcula a primeira conclusão usando uma projeção já carregada.

    Evita recalcular disponibilidade e exceções uma vez por disciplina em
    risco, que seria uma consulta N+1 para grades grandes.
    """
    if remaining <= 0:
        return start.isoformat()
    accumulated = 0
    for current in _range_dates(start.isoformat(), end.isoformat()):
        if item.get("allowed_weekdays") and current.weekday() not in item["allowed_weekdays"]:
            continue
        accumulated += smart_planning.interval_minutes(windows.get(current.isoformat(), []))
        if accumulated >= remaining:
            return current.isoformat()
    return None


def planning_items(conn, start=None, end=None, formation_id=None, item_id=None, kind=None):
    start_day = _date(start or _today())
    end_day = _date(end or (start_day + timedelta(days=6)).isoformat())
    if end_day < start_day: raise DomainError("A data final não pode ser anterior à inicial.")
    rows = _planning_candidate_rows(conn, formation_id, item_id, kind)
    study_ids = [row["id"] for row in rows]
    curriculum_ids = [row["curriculum_subject_id"] for row in rows if row.get("curriculum_subject_id")]
    shared_contexts = _canonical(lambda: canonical_links.planning_contexts(conn, study_ids))
    real_study = _minutes_by_study(conn, study_ids)
    real_curriculum = _minutes_by_curriculum(conn, curriculum_ids)
    week_start, week_end = _week_bounds(_today())
    week_real_study = _minutes_by_study(conn, study_ids, week_start.isoformat(), week_end.isoformat())
    # Cada prazo recebe sua capacidade real até a data; reutiliza janelas em vez
    # de consultar a disponibilidade uma vez por item. Datas antigas inválidas
    # não podem interromper a prévia inteira: serão explicadas no diagnóstico.
    farthest_dates = [end_day]
    for row in rows:
        shared = shared_contexts.get(row["id"], {})
        for value in (row.get("deadline_date"), row.get("curriculum_end_date"), row.get("target_date"), shared.get("closest_active_deadline")):
            parsed, _invalid = _optional_date(value)
            if parsed:
                farthest_dates.append(parsed)
    farthest_day = max(farthest_dates)
    contents_by_study, contents_by_curriculum = _contents_by_owner(
        conn, study_ids, curriculum_ids, future_start=start_day.isoformat(), future_end=farthest_day.isoformat(),
    )
    evaluation_studies, evaluation_curricula = _evaluation_due_sets(conn, study_ids, curriculum_ids)
    evaluations_by_study, evaluations_by_curriculum = _planning_evaluations_by_owner(conn, study_ids, curriculum_ids)
    horizon = _planning_windows(conn, start_day.isoformat(), farthest_day.isoformat())
    preferences = planning_preferences(conn)
    plan_index = _planned_minutes_index(conn, study_ids, min(start_day, week_start).isoformat(), farthest_day.isoformat())
    items = []
    today_day = _local_now().date()
    current_monday = (today_day - timedelta(days=today_day.weekday())).isoformat()
    for row in rows:
        curriculum_id = row.get("curriculum_subject_id")
        shared = shared_contexts.get(row["id"], {})
        kind = "curriculum" if curriculum_id else "personal"
        required = row.get("curriculum_required_study_minutes") if curriculum_id else row.get("required_study_minutes")
        required = int(required) if required else 0
        weekly_goal = int(row.get("weekly_goal_minutes") or 0)
        minimum_weekly = int(row.get("minimum_weekly_minutes") or 0) if kind == "personal" else 0
        real = real_curriculum.get(curriculum_id, 0) if curriculum_id else real_study.get(row["id"], 0)
        week_real = week_real_study.get(row["id"], 0)
        ordinary_deadline = (row.get("deadline_date") or row.get("curriculum_end_date") or row.get("target_date")) if curriculum_id else row.get("target_date")
        deadline_options = []
        for value in (ordinary_deadline, shared.get("closest_active_deadline")):
            parsed, invalid = _optional_date(value)
            if parsed:
                deadline_options.append(parsed)
            elif invalid and value == ordinary_deadline:
                deadline_options = []
                break
        deadline = min(deadline_options).isoformat() if deadline_options else ordinary_deadline
        deadline_day, invalid_deadline = _optional_date(deadline)
        study_start_day, invalid_study_start = _optional_date(row.get("start_date"))
        curriculum_start_day, invalid_curriculum_start = _optional_date(row.get("curriculum_start_date"))
        date_invalid = invalid_deadline or invalid_study_start or invalid_curriculum_start
        effective_start = max([start_day, today_day, *[value for value in (study_start_day, curriculum_start_day) if value]])
        allocation_end = min(deadline_day, end_day) if deadline_day else end_day
        # A prévia pode cobrir apenas esta semana, mas a viabilidade/riscos da
        # disciplina precisam olhar até o prazo completo — não só sete dias.
        capacity_end = deadline_day if deadline_day else end_day
        allowed = _stored_weekdays(row.get("curriculum_allowed_weekdays") if curriculum_id else row.get("allowed_weekdays"))
        effective_block_minutes, block_duration_source = _effective_block_preference(
            row, curriculum_id, preferences["default_session_minutes"],
        )
        planned_by_week = defaultdict(int)
        for planned_row in plan_index.get(row["id"], []):
            planned_day = _date(planned_row["scheduled_date"])
            monday = (planned_day - timedelta(days=planned_day.weekday())).isoformat()
            planned_by_week[monday] += int(planned_row["planned_duration_minutes"] or 0)
        if capacity_end >= effective_start:
            planned_future = _indexed_planned_minutes(plan_index, row["id"], effective_start.isoformat(), capacity_end.isoformat())
        else:
            planned_future = 0
        review_mode = bool(curriculum_id and row.get("review_status") in {"queued", "in_progress"})
        if curriculum_id:
            # Tópicos mantêm a referência curricular de origem para a grade,
            # porém, após um vínculo canônico, podem pertencer ao mesmo estudo.
            # A união por ID torna todos elegíveis uma única vez sem somar a
            # demanda da disciplina duas vezes.
            visible_topics = [
                *contents_by_curriculum.get(curriculum_id, []),
                *contents_by_study.get(row["id"], []),
            ]
            raw_contents = list({topic["id"]: topic for topic in visible_topics}.values())
        else:
            raw_contents = contents_by_study.get(row["id"], [])
        topic_contents = _planning_topic_contents(raw_contents, required, review_mode)
        # Ao concluir um tópico antes do estimado, sua parcela não utilizada
        # deixa de ser demanda. É crédito de planejamento, não tempo real.
        completion_credit = 0 if review_mode else sum(
            max(0, int(topic.get("effective_estimated_minutes") or 0) - int(topic.get("real_minutes") or 0))
            for topic in topic_contents if topic.get("status") == "completed"
        )
        effective_completed = real + completion_credit
        weekly_goal_by_week, minimum_by_week, weekly_demand_by_week = {}, {}, {}
        if allocation_end >= effective_start:
            for week_first, _week_last in smart_planning.weekly_buckets(effective_start, allocation_end):
                monday = (week_first - timedelta(days=week_first.weekday())).isoformat()
                actual_this_week = week_real if monday == current_monday else 0
                planned_this_week = int(planned_by_week.get(monday, 0))
                if not required and weekly_goal:
                    weekly_goal_by_week[monday] = max(0, weekly_goal - actual_this_week - planned_this_week)
                if minimum_weekly:
                    minimum_by_week[monday] = max(0, minimum_weekly - actual_this_week - planned_this_week)
                weekly_demand_by_week[monday] = max(
                    weekly_goal_by_week.get(monday, 0), minimum_by_week.get(monday, 0),
                )
        if required:
            remaining = max(0, required - effective_completed)
            unallocated = max(0, remaining - planned_future)
        else:
            remaining = sum(weekly_demand_by_week.values())
            unallocated = remaining
        if date_invalid or capacity_end < effective_start:
            capacity, available_days = 0, 0
        else:
            capacity, available_days = _item_net_capacity(horizon["capacity_rows"], effective_start.isoformat(), capacity_end.isoformat(), allowed)
        if date_invalid or allocation_end < effective_start:
            period_capacity, period_available_days = 0, 0
        else:
            period_capacity, period_available_days = _item_net_capacity(horizon["capacity_rows"], effective_start.isoformat(), allocation_end.isoformat(), allowed)
        days_remaining = (deadline_day - _local_now().date()).days if deadline_day else None
        raw = {
            "id": row["id"], "study_subject_id": row["id"], "curriculum_subject_id": curriculum_id,
            "kind": kind, "name": row.get("curriculum_name") or row.get("personal_name"),
            "formation_id": row.get("formation_id") or row.get("related_formation_id"),
            "formation_name": row.get("formation_name"),
            "related_formations": shared.get("formation_names", []),
            "shared_curriculum_subjects": shared.get("linked_subjects", []),
            "is_shared_study": len(shared.get("linked_subjects", [])) > 1,
            "deadline": deadline, "deadline_date": deadline, "days_remaining": days_remaining,
            "required_study_minutes": required or None,
            "real_minutes": real, "planning_completed_credit_minutes": completion_credit,
            "planning_effective_completed_minutes": effective_completed,
            "remaining_minutes": remaining, "future_planned_minutes": planned_future,
            "unallocated_minutes": unallocated, "capacity_until_deadline_minutes": capacity,
            "available_days_until_deadline": available_days, "priority_base": int(row.get("priority_base") or row.get("priority") or 3),
            "preferred_block_minutes": effective_block_minutes,
            "effective_block_minutes": effective_block_minutes,
            "block_duration_source": block_duration_source,
            "allowed_weekdays": allowed, "minimum_weekly_minutes": minimum_weekly,
            "weekly_goal_minutes": int(weekly_goal), "week_real_minutes": week_real,
            "week_planned_minutes": int(planned_by_week.get(current_monday, 0)),
            "planned_by_week": dict(planned_by_week), "weekly_goal_by_week": weekly_goal_by_week,
            "minimum_by_week": minimum_by_week, "weekly_demand_by_week": weekly_demand_by_week,
            "study_start_date": row.get("start_date"), "curriculum_start_date": row.get("curriculum_start_date"),
            "effective_start_date": effective_start.isoformat(), "date_invalid": date_invalid,
            "contents": topic_contents,
            "review_mode": review_mode,
            "has_upcoming_evaluation": (curriculum_id in evaluation_curricula if curriculum_id else row["id"] in evaluation_studies) or bool(shared.get("has_upcoming_evaluation")),
        }
        has_configured_demand = bool(required or weekly_goal or minimum_weekly)
        # Uma disciplina atual é elegível por padrão. ``planning_opt_out``
        # representa a desativação explícita e não confunde o valor legado 0
        # de ``planning_enabled`` com a vontade do usuário.
        if curriculum_id and bool(row.get("planning_opt_out")):
            planning_state = "planning_disabled"
        elif date_invalid:
            planning_state = "invalid_date"
        elif deadline_day and deadline_day < start_day:
            planning_state = "deadline_expired"
        elif deadline_day and deadline_day < effective_start:
            planning_state = "deadline_before_start"
        elif effective_start > end_day:
            planning_state = "starts_after_period"
        elif not has_configured_demand:
            planning_state = "missing_effort_or_goal"
        elif required and remaining <= 0:
            planning_state = "remaining_effort_zero"
        elif required and unallocated <= 0:
            planning_state = "already_covered_by_future_blocks"
        elif not required and remaining <= 0:
            planning_state = "already_covered_by_future_blocks"
        else:
            planning_state = "ready"
        if required:
            # A demanda da prévia é a parcela do esforço que pertence ao
            # período visível. Ela não é um "erro de capacidade" só porque o
            # prazo continua depois da prévia. Usamos dias disponíveis para
            # preservar ritmo estável e caímos para dias permitidos quando a
            # disponibilidade ainda não foi configurada.
            pace_days_total = available_days or _eligible_calendar_days(effective_start.isoformat(), capacity_end.isoformat(), allowed)
            pace_days_period = period_available_days or _eligible_calendar_days(effective_start.isoformat(), allocation_end.isoformat(), allowed)
            if deadline_day and deadline_day > end_day and pace_days_total > 0:
                demand_in_period = min(unallocated, max(0, round(unallocated * pace_days_period / pace_days_total)))
            else:
                demand_in_period = unallocated
            deferred_beyond_preview = max(0, unallocated - demand_in_period)
            demand_mode = "review" if review_mode else "deadline_total"
        else:
            demand_in_period = remaining
            deferred_beyond_preview = 0
            demand_mode = "recurring_weekly" if weekly_goal else ("weekly_minimum" if minimum_weekly else "none")
        raw["planning_state"] = planning_state
        raw["is_schedulable"] = planning_state == "ready"
        raw["demand_in_period_minutes"] = int(demand_in_period)
        raw["capacity_in_period_minutes"] = int(period_capacity)
        raw["available_days_in_period"] = int(period_available_days)
        raw["demand_mode"] = demand_mode
        raw["scheduled_in_preview_minutes"] = 0
        raw["deferred_beyond_preview_minutes"] = int(deferred_beyond_preview)
        raw["unallocated_due_to_capacity_minutes"] = max(0, int(demand_in_period) - int(period_capacity))
        # A ausência de esforço pessoal não vira silenciosamente carga da grade.
        # Sem esforço total, a meta semanal ainda mantém o item planejável.
        ideal_day = (unallocated / available_days) if available_days else None
        raw["ideal_minutes_per_available_day"] = round(ideal_day, 1) if ideal_day is not None else None
        raw["ideal_minutes_per_week"] = round((remaining * 7 / max((days_remaining or 7) + 1, 1)), 1) if deadline_day else (max(weekly_goal, minimum_weekly) or None)
        raw["behind_ideal_pace"] = bool(deadline_day and unallocated > 0 and (capacity <= unallocated or (unallocated > 0 and available_days <= 2)))
        urgency, reasons = smart_planning.urgency(raw)
        raw["automatic_urgency"] = urgency; raw["urgency_reasons"] = reasons
        raw["priority_effective"] = smart_planning.effective_priority(raw)
        raw["risk"], raw["risk_label"] = smart_planning.risk(raw)
        raw["deficit_minutes"] = max(0, unallocated - capacity)
        raw["first_feasible_date"] = None
        owner_evaluations = evaluations_by_curriculum.get(curriculum_id, []) if curriculum_id else evaluations_by_study.get(row["id"], [])
        items.append(_normalise_planning_item(raw, row, owner_evaluations))
    feasibility = [item for item in items if item.get("is_schedulable") and item.get("deadline") and item["remaining_minutes"] and item["remaining_minutes"] > item["capacity_until_deadline_minutes"]]
    if feasibility:
        projection_end = start_day + timedelta(days=548)
        projection = _planning_windows(conn, start_day.isoformat(), projection_end.isoformat())["windows"]
        for item in feasibility:
            item["first_feasible_date"] = _first_feasible_from_windows(item, _date(item["effective_start_date"]), item["remaining_minutes"], projection, projection_end)
    joint_risk = _collective_planning_risk(items, horizon["capacity_rows"], start_day, end_day)
    joint_at_risk = set(joint_risk["at_risk_item_ids"])
    for item in items:
        item["joint_risk"] = {
            "status": joint_risk["status"] if item["id"] in joint_at_risk else "on_track",
            "first_deficit_date": joint_risk["first_deficit_date"],
            "shared_deficit_minutes": joint_risk["deficit_minutes"] if item["id"] in joint_at_risk else 0,
            "message": joint_risk["message"],
        }
        if item["id"] in joint_at_risk and joint_risk["status"] != "on_track":
            item.setdefault("urgency_reasons", []).append("capacidade disputada por outras disciplinas")
    return {
        "start": start_day.isoformat(), "end": end_day.isoformat(), "items": items,
        "window_data": horizon, "joint_risk": joint_risk,
    }


def planning_capacity(conn, start, end, formation_id=None, item_id=None, kind=None):
    calculated = planning_items(conn, start, end, formation_id, item_id, kind)
    window_data = _planning_windows(conn, calculated["start"], calculated["end"])
    total_demand = sum(int(item.get("demand_in_period_minutes") or 0) for item in calculated["items"] if item.get("is_schedulable", True))
    return {
        "start": calculated["start"], "end": calculated["end"],
        "capacity_minutes": window_data["capacity_minutes"], "planned_minutes": window_data["planned_minutes"],
        "free_minutes": window_data["free_minutes"], "demand_minutes": total_demand,
        "surplus_minutes": window_data["net_free_minutes"] - total_demand,
        "surplus_before_breaks_minutes": window_data["free_minutes"] - total_demand,
        "gross_capacity_minutes": window_data["gross_capacity_minutes"],
        "reserved_rest_minutes": window_data["reserved_rest_minutes"],
        "net_capacity_minutes": window_data["net_capacity_minutes"],
        "net_free_minutes": window_data["net_free_minutes"],
        "past_unrealized_minutes": window_data["past_unrealized_minutes"],
        "past_unrealized_blocks": window_data["past_unrealized_blocks"],
        "capacity_by_day": window_data["capacity_rows"],
        "joint_risk": calculated["joint_risk"], "items": calculated["items"],
    }


def planning_ideal(conn, start, end, formation_id=None, item_id=None, kind=None):
    values = planning_capacity(conn, start, end, formation_id, item_id, kind)
    future_clauses, future_params = ["d.archived_at IS NULL", "f.archived_at IS NULL", "d.item_type='subject'", "d.academic_status='not_available'"], []
    if formation_id not in (None, ""):
        future_clauses.append("d.formation_id=?")
        future_params.append(int(formation_id))
    if kind == "personal" or item_id not in (None, ""):
        future_clauses.append("1=0")
    futures = repo.many(conn, """
        SELECT d.id,d.name,d.period,d.start_date,d.end_date,d.deadline_date,f.name formation_name
        FROM disciplinas_grade d JOIN formacoes f ON f.id=d.formation_id
        WHERE """ + " AND ".join(future_clauses) + " ORDER BY COALESCE(d.start_date,d.end_date),d.sort_order,d.name LIMIT 30", future_params)
    values["future_subjects"] = futures
    return values


def _planning_diagnostic_action(key, formation_id=None, study_id=None):
    """Ação navegável para uma causa que impede ou limita a prévia."""
    formation_query = f"?selected={int(formation_id)}" if formation_id else ""
    studies_query = f"?study_filter=active&formation_id={int(formation_id)}" if formation_id else "?study_filter=active"
    study_query = f"?study_filter=paused&selected={int(study_id)}" if study_id else "?study_filter=paused"
    actions = {
        "add_current_study": ("Adicionar aos Estudos atuais", f"/studies{studies_query}"),
        "configure_effort": ("Configurar esforço ou meta", f"/formations{formation_query}" if formation_id else "/studies"),
        "enable_planning": ("Reativar planejamento automático", f"/formations{formation_query}" if formation_id else "/studies"),
        "adjust_dates": ("Revisar datas da disciplina", f"/formations{formation_query}" if formation_id else "/studies"),
        "resume_formation": ("Reativar formação", f"/formations{formation_query}"),
        "resume_study": ("Retomar estudo", f"/studies{study_query}"),
        "configure_availability": ("Ajustar disponibilidade", "/planning"),
        "review_curriculum_state": ("Revisar estado da disciplina", f"/formations{formation_query}"),
        "wait_availability": ("Ver disciplina futura", f"/formations{formation_query}"),
    }
    label, href = actions.get(key, ("Abrir planejamento", "/planning"))
    return {"key": key, "label": label, "href": href}


def _planning_diagnostic_item(*, state, code, message, name, formation_id=None, formation_name=None,
                              study_subject_id=None, curriculum_subject_id=None, action_key="configure_availability"):
    return {
        "entity": "curriculum" if curriculum_subject_id else "study",
        "study_subject_id": study_subject_id,
        "curriculum_subject_id": curriculum_subject_id,
        "formation_id": formation_id,
        "formation_name": formation_name,
        "name": name,
        "state": state,
        "reason_codes": [code],
        "reasons": [{"code": code, "message": message, "action": _planning_diagnostic_action(action_key, formation_id, study_subject_id)}],
    }


def _planning_diagnostics(conn, start, end, calculated, capacity, allocation):
    """Explica o que entrou, o que ficou fora e qual ação resolve cada caso.

    A consulta é deliberadamente mais ampla que o filtro do gerador: um estudo
    pausado ou uma disciplina em andamento sem vínculo não podem virar demanda,
    mas precisam aparecer de maneira acionável quando a prévia ficar vazia.
    """
    candidates_by_study = {item["study_subject_id"]: item for item in calculated["items"]}
    candidates_by_curriculum = {item["curriculum_subject_id"]: item for item in calculated["items"] if item.get("curriculum_subject_id")}
    diagnostics, seen = [], set()

    def add(state, code, message, name, *, formation_id=None, formation_name=None,
            study_subject_id=None, curriculum_subject_id=None, action_key="configure_availability"):
        identity = (state, code, study_subject_id, curriculum_subject_id)
        if identity in seen:
            return
        seen.add(identity)
        diagnostics.append(_planning_diagnostic_item(
            state=state, code=code, message=message, name=name,
            formation_id=formation_id, formation_name=formation_name,
            study_subject_id=study_subject_id, curriculum_subject_id=curriculum_subject_id,
            action_key=action_key,
        ))

    calculated_messages = {
        "planning_disabled": ("planning_disabled", "Esta disciplina está em andamento, mas foi removida do planejamento automático.", "enable_planning"),
        "invalid_date": ("invalid_date", "Há uma data inválida neste estudo; revise início e prazo.", "adjust_dates"),
        "deadline_expired": ("deadline_expired", "O prazo já passou para o período escolhido.", "adjust_dates"),
        "deadline_before_start": ("deadline_before_start", "O prazo ocorre antes da data em que o estudo pode começar.", "adjust_dates"),
        "starts_after_period": ("starts_after_period", "O estudo começa depois do fim desta prévia.", "adjust_dates"),
        "missing_effort_or_goal": ("missing_effort_or_goal", "Defina esforço total, meta semanal ou mínimo semanal para gerar blocos.", "configure_effort"),
        "remaining_effort_zero": ("remaining_effort_zero", "O esforço desta matéria já foi concluído em sessões reais.", "review_curriculum_state"),
        "already_covered_by_future_blocks": ("effort_already_covered_by_planned_blocks", "Os blocos já salvos cobrem a demanda deste período.", "configure_effort"),
    }
    for item in calculated["items"]:
        planning_state = item.get("planning_state", "ready")
        if planning_state == "ready":
            continue
        code, message, action_key = calculated_messages.get(planning_state, ("planning_not_ready", "Este estudo ainda não está pronto para ser distribuído.", "configure_effort"))
        add(
            "ignored", code, message, item["name"], formation_id=item.get("formation_id"),
            formation_name=item.get("formation_name"), study_subject_id=item["study_subject_id"],
            curriculum_subject_id=item.get("curriculum_subject_id"), action_key=action_key,
        )

    curriculum_rows = repo.many(conn, """
        SELECT d.id curriculum_subject_id,d.name,d.academic_status,d.review_status,d.archived_at curriculum_archived_at,
          f.id formation_id,f.name formation_name,f.status formation_status,f.archived_at formation_archived_at,
          s.id study_subject_id,s.status study_status,s.archived_at study_archived_at
        FROM disciplinas_grade d
        JOIN formacoes f ON f.id=d.formation_id
        LEFT JOIN materias_estudo s ON s.curriculum_subject_id=d.id
          AND s.status IN ('active','paused') AND s.archived_at IS NULL
        WHERE d.item_type='subject'
          AND (d.academic_status IN ('available','in_progress','not_available','locked')
            OR d.review_status IN ('queued','in_progress') OR s.id IS NOT NULL)
        ORDER BY d.id
    """)
    for row in curriculum_rows:
        curriculum_id = row["curriculum_subject_id"]
        if curriculum_id in candidates_by_curriculum:
            continue
        formation_id = row["formation_id"]
        common = {
            "formation_id": formation_id, "formation_name": row.get("formation_name"),
            "study_subject_id": row.get("study_subject_id"), "curriculum_subject_id": curriculum_id,
        }
        if row.get("academic_status") == "not_available":
            add("future", "not_available_future", "Esta disciplina é futura e não cria demanda no planejamento.", row["name"], action_key="wait_availability", **common)
        elif row.get("curriculum_archived_at"):
            add("ignored", "curriculum_archived", "A disciplina está arquivada e não pode receber novos blocos.", row["name"], action_key="review_curriculum_state", **common)
        elif row.get("formation_archived_at") or row.get("formation_status") != "active":
            add("ignored", "formation_not_active", "A formação não está ativa; reative-a antes de planejar a disciplina.", row["name"], action_key="resume_formation", **common)
        elif row.get("study_status") == "paused":
            add("ignored", "study_paused", "O estudo atual está pausado; retome-o para incluí-lo na prévia.", row["name"], action_key="resume_study", **common)
        elif row.get("study_subject_id") and row.get("academic_status") not in {"in_progress", "completed"}:
            add("ignored", "curriculum_not_in_progress", "A disciplina precisa estar em andamento para entrar no planejamento.", row["name"], action_key="review_curriculum_state", **common)
        elif not row.get("study_subject_id") and row.get("academic_status") in {"in_progress", "completed"}:
            add("ignored", "current_study_missing", "A disciplina está em andamento, mas ainda não foi adicionada aos Estudos atuais.", row["name"], action_key="add_current_study", **common)
        elif row.get("academic_status") == "available":
            add("ignored", "curriculum_not_in_progress", "A disciplina está disponível, mas precisa ser adicionada aos Estudos atuais antes de planejar.", row["name"], action_key="add_current_study", **common)
        elif row.get("academic_status") == "locked":
            add("ignored", "curriculum_locked", "A disciplina está bloqueada e não cria demanda no planejamento.", row["name"], action_key="review_curriculum_state", **common)

    personal_rows = repo.many(conn, """
        SELECT s.id study_subject_id,s.personal_name name,s.status study_status,s.archived_at study_archived_at,
          f.id formation_id,f.name formation_name,f.status formation_status,f.archived_at formation_archived_at
        FROM materias_estudo s
        LEFT JOIN formacoes f ON f.id=s.related_formation_id
        WHERE s.origin='personal' AND s.archived_at IS NULL AND s.status IN ('active','paused')
        ORDER BY s.id
    """)
    for row in personal_rows:
        if row["study_subject_id"] in candidates_by_study:
            continue
        common = {
            "formation_id": row.get("formation_id"), "formation_name": row.get("formation_name"),
            "study_subject_id": row["study_subject_id"],
        }
        if row.get("formation_archived_at") or (row.get("formation_id") and row.get("formation_status") != "active"):
            add("ignored", "formation_not_active", "A formação vinculada não está ativa; reative-a antes de planejar este estudo.", row["name"], action_key="resume_formation", **common)
        elif row.get("study_status") == "paused":
            add("ignored", "study_paused", "Este estudo paralelo está pausado; retome-o para incluí-lo na prévia.", row["name"], action_key="resume_study", **common)

    by_study = {item["id"]: item for item in calculated["items"]}
    for unscheduled in allocation["unscheduled"]:
        item = by_study.get(unscheduled["id"], {})
        if int(capacity.get("capacity_minutes") or 0) <= 0:
            code, message = "no_availability", "Não há faixa de disponibilidade no período escolhido."
        elif int(capacity.get("free_minutes") or 0) <= 0:
            code, message = "windows_fully_occupied", "As faixas disponíveis já estão ocupadas por blocos existentes."
        elif unscheduled.get("code") == "minimum_weekly_unmet":
            code, message = "minimum_weekly_unmet", "A capacidade não foi suficiente para cumprir o mínimo semanal configurado."
        else:
            code, message = "capacity_insufficient", "A capacidade livre não foi suficiente para toda a demanda deste período."
        add(
            "attention", code, message, unscheduled["name"], formation_id=item.get("formation_id"),
            formation_name=item.get("formation_name"), study_subject_id=unscheduled["id"],
            curriculum_subject_id=item.get("curriculum_subject_id"), action_key="configure_availability",
        )

    ignored = sum(item["state"] == "ignored" for item in diagnostics)
    future = sum(item["state"] == "future" for item in diagnostics)
    eligible = sum(item.get("is_schedulable", True) for item in calculated["items"])
    found = len(curriculum_rows) + len(personal_rows)
    unallocated = sum(int(item.get("minutes") or 0) for item in allocation["unscheduled"])
    summary = {
        "found": found, "eligible": eligible, "ignored": ignored, "future": future,
        "capacity_minutes": int(capacity.get("capacity_minutes") or 0),
        "free_minutes": int(capacity.get("free_minutes") or 0),
        "demand_minutes": int(capacity.get("demand_minutes") or 0),
        "unallocated_minutes": unallocated, "proposed_blocks": len(allocation["sessions"]),
    }
    return {
        "summary": summary, "items": diagnostics,
        # Aliases explícitos para integrações que consomem a resposta sem usar a UI.
        "studies_found": summary["found"], "eligible_count": summary["eligible"],
        "ignored_count": summary["ignored"], "future_count": summary["future"],
        "proposed_blocks": summary["proposed_blocks"], "unallocated_minutes": summary["unallocated_minutes"],
    }


def generate_plan(conn, start, days=7):
    if days < 1 or days > 93: raise DomainError("O planejamento automático aceita de 1 a 93 dias.")
    first = _date(start)
    if first < _local_now().date():
        raise DomainError("O início da prévia não pode ser anterior a hoje.", 400, "planning_start_in_past")
    end = first + timedelta(days=days - 1)
    calculated = planning_items(conn, first.isoformat(), end.isoformat())
    preferences = planning_preferences(conn)
    allocation = smart_planning.distribute(
        calculated["items"], calculated["window_data"]["windows"], first, end,
        pause_minutes=preferences["planning_break_minutes"], default_duration=preferences["default_session_minutes"],
        minimum_duration=preferences["minimum_session_minutes"], maximum_duration=preferences["maximum_session_minutes"],
    )
    allocation_by_id = {item["id"]: item for item in allocation["items"]}
    preview_items = [{**item, **allocation_by_id.get(item["id"], {})} for item in calculated["items"]]
    skipped = [item["name"] for item in calculated["items"] if item.get("planning_state") == "missing_effort_or_goal"]
    capacity = planning_capacity(conn, first.isoformat(), end.isoformat())
    scheduled_minutes = sum(int(item.get("planned_duration_minutes") or 0) for item in allocation["sessions"])
    deferred_minutes = sum(int(item.get("deferred_beyond_preview_minutes") or 0) for item in preview_items if item.get("is_schedulable"))
    shortage_minutes = sum(int(item.get("unallocated_due_to_capacity_minutes") or 0) for item in preview_items if item.get("is_schedulable"))
    capacity.update({
        "scheduled_in_preview_minutes": scheduled_minutes,
        "deferred_beyond_preview_minutes": deferred_minutes,
        "unallocated_due_to_capacity_minutes": shortage_minutes,
    })
    return {
        "start": first.isoformat(), "end": end.isoformat(), "sessions": allocation["sessions"],
        "items": preview_items, "unscheduled": allocation["unscheduled"],
        "preferences": preferences, "skipped_without_goal": skipped,
        "capacity": capacity,
        "allocation": {
            "scheduled_in_preview_minutes": scheduled_minutes,
            "deferred_beyond_preview_minutes": deferred_minutes,
            "unallocated_due_to_capacity_minutes": shortage_minutes,
        },
        "diagnostics": _planning_diagnostics(conn, first.isoformat(), end.isoformat(), {**calculated, "items": preview_items}, capacity, allocation),
    }


def apply_smart_plan(conn, values):
    sessions = values.get("sessions", [])
    if not isinstance(sessions, list): raise DomainError("A prévia do planejamento deve ser uma lista de blocos.")
    # Aplicar duas vezes a mesma prévia é inofensivo: procura o bloco automático
    # equivalente antes de inserir. Nenhum bloco manual é tocado nesta operação.
    created, existing = [], []
    for item in sessions:
        if not isinstance(item, dict): raise DomainError("Um bloco da prévia é inválido.")
        found = repo.one(conn, "SELECT * FROM sessoes_planejadas WHERE source='automatic' AND status='planned' AND study_subject_id=? AND scheduled_date=? AND start_time=? AND planned_duration_minutes=?", (item.get("study_subject_id"), item.get("scheduled_date"), item.get("start_time"), item.get("planned_duration_minutes")))
        if found:
            existing.append(found); continue
        planned_values = {
            **item,
            "selection_reason": item.get("selection_reason") or item.get("reason"),
            "selection_context": item.get("selection_context") or json.dumps({
                "topic_progress_percent": item.get("topic_progress_percent"),
                "topic_remaining_minutes": item.get("topic_remaining_minutes"),
                "priority_effective": item.get("priority_effective"),
                "deadline_date": item.get("deadline_date"),
            }, ensure_ascii=False),
        }
        created.append(create_planned(conn, planned_values, "automatic"))
    return {"created": created, "existing": existing, "preserved_manual_blocks": True}


def recommendation(conn):
    today = _today()
    today_plan = _planned_rows_for_window(conn, today, today)
    calculated = planning_items(conn, today, today)
    occupied_studies = {row["study_subject_id"] for row in today_plan}
    candidates = [item for item in calculated["items"] if item.get("is_schedulable", True) and item["study_subject_id"] not in occupied_studies and (item["unallocated_minutes"] > 0 or item["minimum_weekly_minutes"] > 0)]
    if not candidates: return None
    selected = max(candidates, key=lambda item: (item["priority_effective"], item["unallocated_minutes"]))
    topic, topic_reason = smart_planning._topic_choice(selected, _date(today))
    alternatives = []
    for item in sorted(candidates, key=lambda item: item["priority_effective"], reverse=True):
        if item["id"] == selected["id"]:
            continue
        alternatives.append({
            "name": item["name"],
            "kind": item["kind"],
            "impact": (
                f"reduz em {min(int(item.get('unallocated_minutes') or 0), int(item.get('preferred_block_minutes') or 50))} min "
                "o esforço ainda não alocado"
                if int(item.get("unallocated_minutes") or 0) else "mantém a meta semanal em dia"
            ),
        })
        if len(alternatives) == 3:
            break
    return {
        "study_subject": {"id": selected["study_subject_id"], "name": selected["name"]}, "topic": topic,
        "recommended_duration": selected.get("preferred_block_minutes") or planning_preferences(conn)["default_session_minutes"],
        "reasons": [f"prioridade efetiva {selected['priority_effective']}/10", *(selected["urgency_reasons"] or [selected["risk_label"]]), *([topic_reason] if topic_reason else [])],
        "alternatives": [item["name"] for item in alternatives],
        "alternative_details": alternatives,
    }


def today_overview(conn):
    today = _today()
    capacity = planning_capacity(conn, today, today)
    agenda = planned(conn, today, today)
    studied = repo.one(conn, "SELECT COALESCE(SUM(duration_seconds),0)/60 minutes FROM sessoes_estudo WHERE date=?", (today,))
    preference_values = settings(conn)
    suggest_during_free_time = _confirmed(preference_values.get("suggest_during_free_time", True))
    free_time_preference = preference_values.get("free_time_preference") or "suggest"
    # A pergunta de hoje não é "todo o esforço restante cabe hoje?". Para
    # saber se existe folga, projetamos cada prazo até sua data e avaliamos a
    # meta semanal na semana corrente. Isso evita declarar atraso apenas
    # porque uma disciplina ainda tem carga para as próximas semanas.
    today_day = _date(today)
    _week_start, week_end = _week_bounds(today)
    candidate_rows = _planning_candidate_rows(conn)
    deadline_days = []
    for row in candidate_rows:
        value = row.get("deadline_date") or row.get("curriculum_end_date") or row.get("target_date")
        parsed, invalid = _optional_date(value)
        if parsed and not invalid:
            deadline_days.append(parsed)
    forecast_end = min(max([week_end, *deadline_days]), today_day + timedelta(days=548))
    forecast = planning_items(conn, today, forecast_end.isoformat())
    current_monday = (today_day - timedelta(days=today_day.weekday())).isoformat()
    week_window = _planning_windows(conn, today, week_end.isoformat())
    current_week_open = sum(
        int(item.get("weekly_demand_by_week", {}).get(current_monday, 0) or 0)
        for item in forecast["items"] if item.get("is_schedulable", True)
    )
    deadline_deficit = sum(
        int(item.get("deficit_minutes") or 0)
        for item in forecast["items"]
        if item.get("is_schedulable", True) and item.get("required_study_minutes")
    )
    weekly_deficit = max(0, current_week_open - int(week_window["net_free_minutes"] or 0))
    mandatory_unallocated = deadline_deficit + weekly_deficit
    on_track = mandatory_unallocated <= 0
    recommendation_value = recommendation(conn) if suggest_during_free_time and free_time_preference != "preserve" else None
    preferences = planning_preferences(conn)
    free_windows = _planning_windows(conn, today, today)["windows"].get(today, [])
    suggestion_slot = None
    if recommendation_value:
        preferred = int(recommendation_value["recommended_duration"] or preferences["default_session_minutes"])
        preferred = max(preferences["minimum_session_minutes"], min(preferred, preferences["maximum_session_minutes"]))
        for start_minute, end_minute in free_windows:
            if end_minute - start_minute >= preferences["minimum_session_minutes"]:
                duration = min(preferred, end_minute - start_minute)
                suggestion_slot = {
                    "scheduled_date": today,
                    "start_time": f"{start_minute // 60:02d}:{start_minute % 60:02d}",
                    "planned_duration_minutes": duration,
                }
                break
        if suggestion_slot:
            recommendation_value["slot"] = suggestion_slot
    required = sum(int(item["planned_duration_minutes"] or 0) for item in agenda)
    return {
        "date": today,
        # Os aliases históricos permanecem brutos para não quebrar a API;
        # interfaces novas devem preferir explicitamente os campos ``net_*``.
        "capacity_minutes": capacity["capacity_minutes"],
        "planned_minutes": capacity["planned_minutes"],
        "studied_minutes": int(studied["minutes"] or 0),
        "free_minutes": capacity["free_minutes"],
        "gross_capacity_minutes": capacity["capacity_minutes"],
        "gross_free_minutes": capacity["free_minutes"],
        "net_capacity_minutes": capacity["net_capacity_minutes"],
        "net_free_minutes": capacity["net_free_minutes"],
        "required_minutes": required, "agenda": agenda,
        "suggestion": recommendation_value if suggestion_slot else None,
        "suggestion_unavailable": bool(recommendation_value and not suggestion_slot),
        "day_is_full": capacity["net_free_minutes"] < preferences["minimum_session_minutes"],
        "mandatory_unallocated_minutes": mandatory_unallocated,
        "current_week_open_minutes": current_week_open,
        "forecast_end": forecast_end.isoformat(),
        "on_track": on_track,
        "free_time_preference": free_time_preference,
        "free_time_message": "Você está em dia. A demanda obrigatória de hoje já foi cumprida." if on_track else None,
        "free_time_options": [
            "Manter o horário livre", "Avançar o próximo tópico", "Adiantar outra disciplina ativa",
            "Estudar uma disciplina disponível futura", "Fazer uma revisão", "Estudar um assunto paralelo",
        ] if on_track else [],
    }


def search(conn, query):
    term = str(query or "").strip()
    if len(term) < 2: return {"formations": [], "curriculum": [], "studies": [], "topics": []}
    like = f"%{term}%"
    return {
        "formations": repo.many(conn, "SELECT id,name,institution FROM formacoes WHERE archived_at IS NULL AND name LIKE ? COLLATE NOCASE ORDER BY name LIMIT 10", (like,)),
        "curriculum": repo.many(conn, "SELECT d.id,d.name,d.formation_id,f.name formation_name FROM disciplinas_grade d JOIN formacoes f ON f.id=d.formation_id WHERE d.archived_at IS NULL AND d.name LIKE ? COLLATE NOCASE ORDER BY d.name LIMIT 10", (like,)),
        "studies": repo.many(conn, "SELECT s.id,COALESCE(d.name,s.personal_name) name FROM materias_estudo s LEFT JOIN disciplinas_grade d ON d.id=s.curriculum_subject_id WHERE s.archived_at IS NULL AND COALESCE(d.name,s.personal_name) LIKE ? COLLATE NOCASE ORDER BY name LIMIT 10", (like,)),
        "topics": repo.many(conn, "SELECT t.id,t.name,t.study_subject_id,t.curriculum_subject_id,COALESCE(cd.name,d.name,s.personal_name) subject_name FROM topicos t LEFT JOIN materias_estudo s ON s.id=t.study_subject_id LEFT JOIN disciplinas_grade d ON d.id=s.curriculum_subject_id LEFT JOIN disciplinas_grade cd ON cd.id=t.curriculum_subject_id WHERE t.archived_at IS NULL AND t.name LIKE ? COLLATE NOCASE ORDER BY t.name LIMIT 10", (like,)),
    }


def reviews(conn):
    return repo.many(conn,"""
        SELECT r.*,t.name topic_name,COALESCE(cd.name,d.name,s.personal_name) subject_name
        FROM revisoes r
        JOIN topicos t ON t.id=r.topic_id
        LEFT JOIN sessoes_estudo x ON x.id=COALESCE(r.study_session_id,r.root_session_id)
        LEFT JOIN materias_estudo s ON s.id=COALESCE(t.study_subject_id,x.study_subject_id)
        LEFT JOIN disciplinas_grade d ON d.id=s.curriculum_subject_id
        LEFT JOIN disciplinas_grade cd ON cd.id=t.curriculum_subject_id
        WHERE r.status='pending' ORDER BY r.due_date
    """)
def _start_review_chain(conn, topic_id, session_id, studied_on):
    existing = repo.one(conn,"SELECT id FROM revisoes WHERE topic_id=? AND status='pending' LIMIT 1",(topic_id,))
    if existing: return None
    ident = repo.insert(conn,"revisoes",{"topic_id":topic_id,"study_session_id":session_id,"root_session_id":session_id,"due_date":(studied_on+timedelta(days=1)).isoformat(),"review_stage":"d1"})
    return _get(conn,"revisoes",ident)


def complete_review(conn,ident,rating, duration_seconds=None, notes=None):
    if rating not in ("wrong","hard","good","easy"): raise DomainError("Avaliação de revisão inválida.")
    review=_get(conn,"revisoes",ident)
    if review["status"] != "pending": raise DomainError("Esta revisão já foi concluída ou cancelada.",409)
    repo.update(conn,"revisoes",ident,{"status":"completed","rating":rating,"completed_at":_now()})
    next_stage = {"d1":"d7","d7":"d30","d30":None}[review["review_stage"]]
    shifts = {"d1":{"wrong":1,"hard":3,"good":7,"easy":14},"d7":{"wrong":3,"hard":7,"good":30,"easy":45}} 
    if next_stage:
        due_date = (_local_now().date()+timedelta(days=shifts[review["review_stage"]][rating])).isoformat()
        repo.insert(conn,"revisoes",{"topic_id":review["topic_id"],"study_session_id":review["study_session_id"],"root_session_id":review["root_session_id"],"due_date":due_date,"review_stage":next_stage})
    if duration_seconds:
        topic = _get(conn,"topicos",review["topic_id"])
        study_id = topic.get("study_subject_id") or repo.one(conn, "SELECT study_subject_id FROM sessoes_estudo WHERE id=?", (review.get("root_session_id") or review.get("study_session_id"),))
        if not study_id and topic.get("curriculum_subject_id"):
            study_id = repo.one(conn, "SELECT id FROM materias_estudo WHERE curriculum_subject_id=? AND status IN ('active','paused') AND archived_at IS NULL ORDER BY id DESC LIMIT 1", (topic["curriculum_subject_id"],))
        effective_id = study_id.get("study_subject_id") if isinstance(study_id, dict) and "study_subject_id" in study_id else study_id.get("id") if isinstance(study_id, dict) else study_id
        if not effective_id: raise DomainError("Ative a disciplina antes de registrar a revisão.", 409, "study_not_current")
        create_session(conn,{"study_subject_id":effective_id,"topic_id":topic["id"],"date":_today(),"duration_seconds":int(duration_seconds),"entry_method":"review","notes":notes})
    return _get(conn,"revisoes",ident)


def history(conn,start=None,end=None,limit=100):
    clauses=[]; params=[]
    if start: clauses.append("x.date>=?"); params.append(start)
    if end: clauses.append("x.date<=?"); params.append(end)
    where=("WHERE "+" AND ".join(clauses)) if clauses else ""
    sql="SELECT x.*,COALESCE(s.personal_name,d.name) subject_name,t.name topic_name FROM sessoes_estudo x JOIN materias_estudo s ON s.id=x.study_subject_id LEFT JOIN disciplinas_grade d ON d.id=s.curriculum_subject_id LEFT JOIN topicos t ON t.id=x.topic_id "+where+" ORDER BY x.date DESC,x.id DESC LIMIT ?"
    return repo.many(conn,sql,(*params,limit))


def _analytics_dates(start=None, end=None):
    today = _local_now().date()
    first = _date(start) if start else today - timedelta(days=29)
    last = _date(end) if end else today
    if last < first: raise DomainError("A data final não pode ser anterior à inicial.")
    return first, last


def analytics_workload(conn, start=None, end=None, formation_id=None, item_id=None, kind=None):
    first, last = _analytics_dates(start, end)
    if kind not in (None, "", "curriculum", "personal"):
        raise DomainError("Tipo de item do filtro é inválido.")
    clauses, params = ["x.date BETWEEN ? AND ?"], [first.isoformat(), last.isoformat()]
    if formation_id not in (None, ""):
        clauses.append("COALESCE(s.related_formation_id,d.formation_id)=?"); params.append(int(formation_id))
    if item_id not in (None, ""):
        clauses.append("s.id=?"); params.append(int(item_id))
    if kind: clauses.append("s.origin=?"); params.append(kind)
    where = " AND ".join(clauses)
    total = repo.one(conn, "SELECT COALESCE(SUM(x.duration_seconds),0) seconds,COUNT(*) sessions,COUNT(DISTINCT x.date) days FROM sessoes_estudo x JOIN materias_estudo s ON s.id=x.study_subject_id LEFT JOIN disciplinas_grade d ON d.id=s.curriculum_subject_id WHERE " + where, params)
    by_item = repo.many(conn, """
        SELECT s.id,COALESCE(d.name,s.personal_name) name,s.origin,COALESCE(SUM(x.duration_seconds),0) seconds,COUNT(x.id) sessions
        FROM sessoes_estudo x JOIN materias_estudo s ON s.id=x.study_subject_id
        LEFT JOIN disciplinas_grade d ON d.id=s.curriculum_subject_id
        WHERE """ + where + " GROUP BY s.id ORDER BY seconds DESC,name", params)
    real_by_day = repo.many(conn, """
        SELECT x.date,COALESCE(SUM(x.duration_seconds),0) real_seconds,COUNT(x.id) sessions
        FROM sessoes_estudo x JOIN materias_estudo s ON s.id=x.study_subject_id
        LEFT JOIN disciplinas_grade d ON d.id=s.curriculum_subject_id
        WHERE """ + where + " GROUP BY x.date ORDER BY x.date", params)
    planned = repo.one(conn, """
        SELECT COUNT(*) total,
          COUNT(*) FILTER(WHERE p.status='completed') completed,
          COUNT(*) FILTER(WHERE p.status='cancelled') cancelled,
          COALESCE(SUM(p.planned_duration_minutes) FILTER(WHERE p.status='planned'),0) future_minutes
        FROM sessoes_planejadas p JOIN materias_estudo s ON s.id=p.study_subject_id
        LEFT JOIN disciplinas_grade d ON d.id=s.curriculum_subject_id
        WHERE p.scheduled_date BETWEEN ? AND ?
        """ + (" AND COALESCE(s.related_formation_id,d.formation_id)=" + "?" if formation_id not in (None, "") else "") + (" AND s.id=?" if item_id not in (None, "") else "") + (" AND s.origin=?" if kind else ""), (first.isoformat(), last.isoformat(), *((int(formation_id),) if formation_id not in (None, "") else ()), *((int(item_id),) if item_id not in (None, "") else ()), *((kind,) if kind else ())))
    planned_clauses = ["p.scheduled_date BETWEEN ? AND ?", "p.status IN ('planned','completed','skipped')"]
    planned_params = [first.isoformat(), last.isoformat()]
    if formation_id not in (None, ""):
        planned_clauses.append("COALESCE(s.related_formation_id,d.formation_id)=?"); planned_params.append(int(formation_id))
    if item_id not in (None, ""):
        planned_clauses.append("s.id=?"); planned_params.append(int(item_id))
    if kind:
        planned_clauses.append("s.origin=?"); planned_params.append(kind)
    planned_by_day = repo.many(conn, """
        SELECT p.scheduled_date date,COALESCE(SUM(p.planned_duration_minutes),0) planned_minutes
        FROM sessoes_planejadas p JOIN materias_estudo s ON s.id=p.study_subject_id
        LEFT JOIN disciplinas_grade d ON d.id=s.curriculum_subject_id
        WHERE """ + " AND ".join(planned_clauses) + " GROUP BY p.scheduled_date ORDER BY p.scheduled_date", planned_params)
    real_by_date = {row["date"]: row for row in real_by_day}
    planned_by_date = {row["date"]: row for row in planned_by_day}
    by_day = [
        {
            "date": current.isoformat(),
            "real_seconds": int(real_by_date.get(current.isoformat(), {}).get("real_seconds", 0) or 0),
            "planned_minutes": int(planned_by_date.get(current.isoformat(), {}).get("planned_minutes", 0) or 0),
            "sessions": int(real_by_date.get(current.isoformat(), {}).get("sessions", 0) or 0),
        }
        for current in _range_dates(first.isoformat(), last.isoformat())
    ]
    orphan_completed = repo.one(conn, """
        SELECT COUNT(*) count FROM sessoes_planejadas p
        WHERE p.status='completed' AND p.scheduled_date BETWEEN ? AND ?
          AND NOT EXISTS (SELECT 1 FROM sessoes_estudo x WHERE x.planned_session_id=p.id)
    """, (first.isoformat(), last.isoformat()))
    ideal = planning_ideal(conn, _today(), (_local_now().date() + timedelta(days=30)).isoformat(), formation_id, item_id, kind)
    evaluation_clauses, evaluation_params = ["e.status NOT IN ('cancelled','corrected')", "e.date>=?"], [_today()]
    if formation_id not in (None, ""):
        evaluation_clauses.append("COALESCE(s.related_formation_id,cd.formation_id,d.formation_id)=?")
        evaluation_params.append(int(formation_id))
    if item_id not in (None, ""):
        evaluation_clauses.append("e.study_subject_id=?")
        evaluation_params.append(int(item_id))
    if kind == "curriculum":
        evaluation_clauses.append("COALESCE(e.curriculum_subject_id,s.curriculum_subject_id) IS NOT NULL")
    elif kind == "personal":
        evaluation_clauses.append("COALESCE(e.curriculum_subject_id,s.curriculum_subject_id) IS NULL")
    upcoming_evaluations = repo.many(conn, """
        SELECT e.*,COALESCE(cd.name,d.name,s.personal_name) subject_name
        FROM avaliacoes e LEFT JOIN materias_estudo s ON s.id=e.study_subject_id
        LEFT JOIN disciplinas_grade d ON d.id=s.curriculum_subject_id
        LEFT JOIN disciplinas_grade cd ON cd.id=e.curriculum_subject_id
        WHERE """ + " AND ".join(evaluation_clauses) + " ORDER BY e.date LIMIT 12", evaluation_params)
    grade_clauses, grade_params = ["e.status<>'cancelled'", "e.score IS NOT NULL", "e.max_score IS NOT NULL", "e.max_score>0"], []
    if formation_id not in (None, ""):
        grade_clauses.append("COALESCE(s.related_formation_id,cd.formation_id,d.formation_id)=?")
        grade_params.append(int(formation_id))
    if item_id not in (None, ""):
        grade_clauses.append("e.study_subject_id=?")
        grade_params.append(int(item_id))
    if kind == "curriculum":
        grade_clauses.append("COALESCE(e.curriculum_subject_id,s.curriculum_subject_id) IS NOT NULL")
    elif kind == "personal":
        grade_clauses.append("COALESCE(e.curriculum_subject_id,s.curriculum_subject_id) IS NULL")
    grade_by_subject = repo.many(conn, """
        SELECT COALESCE(cd.id,d.id) curriculum_subject_id,COALESCE(cd.name,d.name,s.personal_name) subject_name,
          COUNT(*) evaluations,ROUND(AVG(e.score*100.0/e.max_score),1) simple_average_percent,
          ROUND(SUM(CASE WHEN e.weight IS NOT NULL THEN (e.score*100.0/e.max_score)*e.weight END) /
                NULLIF(SUM(CASE WHEN e.weight IS NOT NULL THEN e.weight END),0),1) weighted_average_percent
        FROM avaliacoes e LEFT JOIN materias_estudo s ON s.id=e.study_subject_id
        LEFT JOIN disciplinas_grade d ON d.id=s.curriculum_subject_id
        LEFT JOIN disciplinas_grade cd ON cd.id=e.curriculum_subject_id
        WHERE """ + " AND ".join(grade_clauses) + " GROUP BY COALESCE(cd.id,d.id,s.id),COALESCE(cd.name,d.name,s.personal_name) ORDER BY simple_average_percent DESC,subject_name", grade_params)
    most_studied_contents = repo.many(conn, """
        SELECT t.id,t.name,t.unit,COALESCE(cd.name,d.name,s.personal_name) subject_name,
          COALESCE(SUM(x.duration_seconds),0) seconds,MAX(x.date) last_activity
        FROM topicos t LEFT JOIN sessoes_estudo x ON x.topic_id=t.id
        LEFT JOIN materias_estudo s ON s.id=t.study_subject_id
        LEFT JOIN disciplinas_grade d ON d.id=s.curriculum_subject_id
        LEFT JOIN disciplinas_grade cd ON cd.id=t.curriculum_subject_id
        WHERE t.archived_at IS NULL GROUP BY t.id ORDER BY seconds DESC,last_activity DESC LIMIT 12
    """)
    inactive_contents = repo.many(conn, """
        SELECT t.id,t.name,t.unit,COALESCE(cd.name,d.name,s.personal_name) subject_name,t.last_session_date
        FROM topicos t LEFT JOIN materias_estudo s ON s.id=t.study_subject_id
        LEFT JOIN disciplinas_grade d ON d.id=s.curriculum_subject_id
        LEFT JOIN disciplinas_grade cd ON cd.id=t.curriculum_subject_id
        WHERE t.archived_at IS NULL AND t.status<>'completed'
          AND (t.last_session_date IS NULL OR t.last_session_date<?)
        ORDER BY t.last_session_date,t.name LIMIT 12
    """, ((_local_now().date() - timedelta(days=14)).isoformat(),))
    return {
        "start": first.isoformat(), "end": last.isoformat(), "total_seconds": int(total["seconds"] or 0),
        "sessions": int(total["sessions"] or 0), "days_studied": int(total["days"] or 0),
        "by_item": by_item, "by_day": by_day, "planned": {key: int(value or 0) for key, value in planned.items()},
        "completion_rate_percent": round(int(planned["completed"] or 0) * 100 / int(planned["total"] or 1), 1) if planned["total"] else None,
        "completed_planned_without_real_session": int(orphan_completed["count"] or 0),
        "capacity": {key: planning_capacity(conn, _today(), (_local_now().date() + timedelta(days=offset)).isoformat(), formation_id, item_id, kind) for key, offset in (("7", 6), ("14", 13), ("30", 29))},
        "ideal": ideal, "at_risk": [item for item in ideal["items"] if item["risk"] in {"at_risk", "impossible"}],
        "upcoming_deadlines": sorted(({
            "name": item["name"], "kind": item["kind"], "deadline": item["deadline"],
            "remaining_minutes": item["remaining_minutes"], "risk_label": item["risk_label"],
        } for item in ideal["items"] if item.get("deadline")), key=lambda item: item["deadline"])[:12],
        "upcoming_evaluations": upcoming_evaluations, "grade_by_subject": grade_by_subject,
        "most_studied_contents": most_studied_contents,
        "inactive_contents": inactive_contents,
    }


def analytics_summary(conn, reference_date=None):
    """Totais leves usados pelos cartões globais da tela de análises.

    Eles não dependem de capacidade, risco ou planejamento. Mantê-los fora de
    ``analytics_workload`` evita repetir todo o cálculo de planejamento para
    cada horizonte de tempo exibido na interface.
    """
    reference = _date(reference_date, "Data de referência") if reference_date else _local_now().date()
    week_start, _ = _week_bounds(reference.isoformat())
    month_start = reference.replace(day=1)
    totals = repo.one(conn, """
        SELECT
          COALESCE(SUM(CASE WHEN date=? THEN duration_seconds ELSE 0 END),0) today_seconds,
          COALESCE(SUM(CASE WHEN date BETWEEN ? AND ? THEN duration_seconds ELSE 0 END),0) week_seconds,
          COALESCE(SUM(duration_seconds),0) month_seconds
        FROM sessoes_estudo
        WHERE date BETWEEN ? AND ?
    """, (
        reference.isoformat(), week_start.isoformat(), reference.isoformat(),
        month_start.isoformat(), reference.isoformat(),
    ))
    return {
        "date": reference.isoformat(),
        "week_start": week_start.isoformat(),
        "month_start": month_start.isoformat(),
        "today_seconds": int(totals["today_seconds"] or 0),
        "week_seconds": int(totals["week_seconds"] or 0),
        "month_seconds": int(totals["month_seconds"] or 0),
    }


def analytics(conn):
    today = _local_now().date()
    week_start, week_end = _week_bounds(today.isoformat())
    month_start = today.replace(day=1)
    month_end = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    total = repo.one(conn, "SELECT COALESCE(SUM(duration_seconds),0) seconds,COUNT(*) sessions,COUNT(DISTINCT date) days FROM sessoes_estudo")
    today_total = repo.one(conn, "SELECT COALESCE(SUM(duration_seconds),0) seconds FROM sessoes_estudo WHERE date=?", (today.isoformat(),))
    week = repo.one(conn, "SELECT COALESCE(SUM(duration_seconds),0) seconds FROM sessoes_estudo WHERE date BETWEEN ? AND ?", (week_start.isoformat(), week_end.isoformat()))
    month = repo.one(conn, "SELECT COALESCE(SUM(duration_seconds),0) seconds FROM sessoes_estudo WHERE date BETWEEN ? AND ?", (month_start.isoformat(), month_end.isoformat()))
    completed_blocks = repo.one(conn, "SELECT COUNT(*) count FROM sessoes_planejadas WHERE status='completed'")
    workload = analytics_workload(conn, month_start.isoformat(), month_end.isoformat())
    next_pending = repo.many(conn, """
        SELECT d.id,d.name,d.formation_id,f.name formation_name,d.period,d.academic_status,d.review_status,d.deadline_date
        FROM disciplinas_grade d JOIN formacoes f ON f.id=d.formation_id
        WHERE d.archived_at IS NULL AND d.item_type='subject' AND f.archived_at IS NULL
          AND d.academic_status IN ('in_progress','available')
        ORDER BY CASE d.academic_status WHEN 'in_progress' THEN 0 ELSE 1 END,COALESCE(d.deadline_date,d.end_date),d.sort_order,d.name
        LIMIT 12
    """)
    future_subjects = repo.many(conn, """
        SELECT d.id,d.name,d.period,d.start_date,d.end_date,f.name formation_name
        FROM disciplinas_grade d JOIN formacoes f ON f.id=d.formation_id
        WHERE d.archived_at IS NULL AND f.archived_at IS NULL AND d.item_type='subject' AND d.academic_status='not_available'
        ORDER BY COALESCE(d.start_date,d.end_date),d.sort_order,d.name LIMIT 12
    """)
    return {
        "total_seconds": int(total["seconds"] or 0), "sessions": int(total["sessions"] or 0), "real_sessions": int(total["sessions"] or 0),
        "days_studied": int(total["days"] or 0), "today_seconds": int(today_total["seconds"] or 0), "week_seconds": int(week["seconds"] or 0),
        "month_seconds": int(month["seconds"] or 0), "by_subject": workload["by_item"],
        "completed_planned_blocks": int(completed_blocks["count"] or 0),
        "completed_planned_without_real_session": workload["completed_planned_without_real_session"],
        "next_pending_subjects": next_pending, "future_subjects": future_subjects, "workload": workload,
    }


def projects(conn, include_archived=False):
    where = "" if include_archived else "WHERE p.archived_at IS NULL"
    return repo.many(conn, "SELECT p.*,COUNT(t.id) task_count,COUNT(t.id) FILTER(WHERE t.status='completed') completed_tasks FROM projetos p LEFT JOIN projeto_tarefas t ON t.project_id=p.id " + where + " GROUP BY p.id ORDER BY p.created_at DESC")


def create_project(conn, values):
    data = _fields(values, {"name","description","objective","start_date","target_date","status","estimated_minutes","notes"})
    data["name"] = _need(data.get("name"), "Nome do projeto"); data.setdefault("status", "active")
    return _get(conn, "projetos", repo.insert(conn, "projetos", data))


def update_project(conn, ident, values):
    return change_record(conn, "projetos", ident, values, {"name", "description", "objective", "start_date", "target_date", "status", "estimated_minutes", "notes"})


def archive_project(conn, ident, restore=False):
    _get(conn, "projetos", ident)
    repo.update(conn, "projetos", ident, {"status": "active" if restore else "archived", "archived_at": None if restore else _now()})
    return _get(conn, "projetos", ident)


def project_detail(conn, ident):
    project = _get(conn, "projetos", ident)
    project["tasks"] = repo.many(conn, "SELECT * FROM projeto_tarefas WHERE project_id=? ORDER BY sort_order,id", (ident,))
    return project


def add_project_task(conn, project_id, values):
    _get(conn,"projetos",project_id)
    return _get(conn,"projeto_tarefas",repo.insert(conn,"projeto_tarefas",{"project_id":project_id,"name":_need(values.get("name"),"Nome da tarefa"),"sort_order":values.get("sort_order",0)}))


def update_project_task(conn, ident, values):
    data = _fields(values, {"name", "status", "sort_order"})
    if "name" in data: data["name"] = _need(data["name"], "Nome da tarefa")
    if data.get("status") == "completed": data["completed_at"] = _now()
    elif "status" in data: data["completed_at"] = None
    return change_record(conn, "projeto_tarefas", ident, data, {"name", "status", "sort_order", "completed_at"})


def settings(conn):
    return {row["key"]:row["value"] for row in repo.many(conn,"SELECT key,value FROM configuracoes")}


def save_settings(conn, values):
    allowed = {
        "daily_goal_minutes", "weekly_goal_minutes", "default_session_minutes", "planning_break_minutes",
        "minimum_session_minutes", "maximum_session_minutes", "review_strategy", "theme",
        "focus_recovery_minutes", "daily_max_study_minutes", "minimum_rest_minutes",
        "suggest_during_free_time", "free_time_preference",
    }
    normalized = dict(values)
    for key in {"daily_goal_minutes", "weekly_goal_minutes", "default_session_minutes", "planning_break_minutes", "minimum_session_minutes", "maximum_session_minutes", "focus_recovery_minutes", "daily_max_study_minutes", "minimum_rest_minutes"}:
        if key not in normalized or normalized[key] in (None, ""):
            continue
        try:
            amount = int(normalized[key])
        except (TypeError, ValueError) as error:
            raise DomainError(f"{key} deve ser informado em minutos como número inteiro.") from error
        if amount < 0:
            raise DomainError(f"{key} não pode ser negativo.")
        normalized[key] = amount
    if "suggest_during_free_time" in normalized:
        normalized["suggest_during_free_time"] = 1 if _confirmed(normalized["suggest_during_free_time"]) else 0
    if "free_time_preference" in normalized and normalized["free_time_preference"] not in {"suggest", "preserve"}:
        raise DomainError("Preferência de folga inválida.")
    for key, value in normalized.items():
        if key in allowed: conn.execute("INSERT INTO configuracoes(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')",(key,str(value) if value is not None else None))
    return settings(conn)


def change_record(conn, table, ident, values, allowed):
    _get(conn, table, ident)
    data = _fields(values, allowed)
    if "name" in data: data["name"] = _need(data["name"], "Nome")
    if "title" in data: data["title"] = _need(data["title"], "Título")
    repo.update(conn, table, ident, data)
    return _get(conn, table, ident)
