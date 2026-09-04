"""Regras de negócio da V2. Nenhuma rota contém SQL ou decisões do produto."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
import json
from pathlib import Path
import re
import sqlite3
import unicodedata
from zoneinfo import ZoneInfo

from config import TIMEZONE
from database.repositories import core as repo
from services import grade_import


class DomainError(ValueError):
    def __init__(self, message, status=400, code="domain_error", blockers=None, details=None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.blockers = blockers
        self.details = details


def _local_now(): return datetime.now(ZoneInfo(TIMEZONE))
def _today(): return _local_now().date().isoformat()
def _now(): return _local_now().isoformat(timespec="seconds")
def _date(value, label="Data"):
    try: return date.fromisoformat(str(value))
    except ValueError as error: raise DomainError(f"{label} deve usar AAAA-MM-DD.") from error
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
def _fields(values, allowed): return {key: value for key, value in values.items() if key in allowed and value is not None}


def _active_formation(conn, ident):
    formation = _get(conn, "formacoes", ident)
    if formation["archived_at"]:
        raise DomainError("Restaure a formação antes de fazer alterações.", 409, "formation_archived")
    return formation


FORMATION = {"name", "institution", "modality", "start_date", "expected_end_date", "status", "focus_priority"}
CURRICULUM = {
    "name", "code", "period", "workload_minutes", "academic_status", "sort_order",
    "start_date", "end_date", "notes", "review_status", "review_priority", "review_notes",
    "item_type",
}
STUDY = {"favorite", "priority", "difficulty", "weekly_goal_minutes", "start_date", "target_date", "status", "academic_period", "result", "final_score"}

ACADEMIC_STATUSES = tuple(grade_import.ACADEMIC_STATUSES)
REVIEW_STATUSES = ("none", "queued", "in_progress", "reviewed")
ITEM_TYPES = ("subject", "section")
STUDY_ARCHIVE_REASONS = ("manual", "formation", "curriculum", "removed_current")


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
    cancelled = {"count": 0, "ids": []}
    if study_policy == "archive_studies":
        for study_id in active_ids:
            _archive_study_row(conn, study_id, "formation", ident)
            archived_ids.append(study_id)
        cancelled = _cancel_future_planned(conn, active_ids)
    repo.update(conn, "formacoes", ident, {"status": "archived", "archived_at": _now()})
    saved = _get(conn, "formacoes", ident)
    return {
        **saved, "formation": saved, "study_policy": study_policy,
        "archived_studies": {"count": len(archived_ids), "ids": archived_ids},
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
    return _restore_study_row(conn, ident) if restore else _archive_study_row(conn, ident, "manual")


def archive_curriculum(conn, ident, restore=False):
    current = _get(conn, "disciplinas_grade", ident)
    if restore:
        _active_formation(conn, current["formation_id"])
        repo.update(conn, "disciplinas_grade", ident, {"archived_at": None})
    else:
        _active_formation(conn, current["formation_id"])
        repo.update(conn, "disciplinas_grade", ident, {"archived_at": _now()})
    return _get(conn, "disciplinas_grade", ident)


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
        )
        SELECT
            (SELECT COUNT(*) FROM disciplinas_grade WHERE formation_id=?) AS curriculum_subjects,
            (SELECT COUNT(*) FROM formation_studies) AS study_subjects,
            (SELECT COUNT(*) FROM formation_topics) AS topics,
            (SELECT COUNT(*) FROM sessoes_planejadas WHERE study_subject_id IN (SELECT id FROM formation_studies)) AS planned_sessions,
            (SELECT COUNT(*) FROM sessoes_estudo WHERE study_subject_id IN (SELECT id FROM formation_studies)) AS study_sessions,
            (SELECT COUNT(*) FROM anotacoes_estudo WHERE study_subject_id IN (SELECT id FROM formation_studies)) AS notes,
            (SELECT COUNT(*) FROM revisoes WHERE topic_id IN (SELECT id FROM formation_topics)) AS reviews,
            (SELECT COUNT(*) FROM avaliacoes WHERE study_subject_id IN (SELECT id FROM formation_studies)) AS evaluations
    """, (ident, ident, ident))
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
    topic_ids = _selected_ids(conn, f"SELECT id FROM topicos WHERE study_subject_id IN {marks}", params)
    planned_rows = repo.many(conn, f"SELECT id,status FROM sessoes_planejadas WHERE study_subject_id IN {marks}", params)
    session_ids = _selected_ids(conn, f"SELECT id FROM sessoes_estudo WHERE study_subject_id IN {marks}", params)
    note_ids = _selected_ids(conn, f"SELECT id FROM anotacoes_estudo WHERE study_subject_id IN {marks}", params)
    review_marks, review_params = _sql_ids(topic_ids)
    review_ids = _selected_ids(conn, f"SELECT id FROM revisoes WHERE topic_id IN {review_marks}", review_params)
    evaluation_ids = _selected_ids(conn, f"SELECT id FROM avaliacoes WHERE study_subject_id IN {marks}", params)
    evaluation_marks, evaluation_params = _sql_ids(evaluation_ids)
    link_ids = _selected_ids(conn, f"SELECT rowid id FROM avaliacao_topicos WHERE evaluation_id IN {evaluation_marks}", evaluation_params)
    history_marks, history_params = _sql_ids(curriculum_ids)
    history_ids = _selected_ids(conn, f"SELECT id FROM curriculum_status_history WHERE curriculum_subject_id IN {history_marks}", history_params)
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
        "evaluation_topic_links": _count_ids(link_ids), "status_history": _count_ids(history_ids),
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
    topic_marks, topic_params = _sql_ids(topic_ids)
    evaluation_ids = _selected_ids(conn, f"SELECT id FROM avaliacoes WHERE study_subject_id IN {marks}", params)
    evaluation_marks, evaluation_params = _sql_ids(evaluation_ids)
    # A ordem é deliberada: remove referências opcionais antes das entidades
    # referenciadas e nunca depende de uma cascata ampla para ocultar a lógica.
    conn.execute(f"DELETE FROM anotacoes_estudo WHERE study_subject_id IN {marks}", params)
    conn.execute(f"DELETE FROM avaliacao_topicos WHERE evaluation_id IN {evaluation_marks} OR topic_id IN {topic_marks}", (*evaluation_params, *topic_params))
    conn.execute(f"DELETE FROM revisoes WHERE topic_id IN {topic_marks}", topic_params)
    conn.execute(f"DELETE FROM sessoes_estudo WHERE study_subject_id IN {marks}", params)
    conn.execute(f"DELETE FROM sessoes_planejadas WHERE study_subject_id IN {marks}", params)
    conn.execute(f"DELETE FROM avaliacoes WHERE id IN {evaluation_marks}", evaluation_params)
    conn.execute(f"DELETE FROM topicos WHERE study_subject_id IN {marks}", params)
    conn.execute(f"DELETE FROM grupos_topicos WHERE study_subject_id IN {marks}", params)
    conn.execute(f"DELETE FROM materias_estudo WHERE id IN {marks}", params)


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
        _delete_study_graph(conn, dependencies["study_subjects"]["ids"])
        marks, params = _sql_ids(dependencies["curriculum_subjects"]["ids"])
        conn.execute(f"DELETE FROM curriculum_status_history WHERE curriculum_subject_id IN {marks}", params)
        conn.execute(f"DELETE FROM disciplinas_grade WHERE id IN {marks}", params)
    elif kind == "formation":
        _delete_study_graph(conn, dependencies["study_subjects"]["ids"])
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
    for key in ("code", "period", "start_date", "end_date", "notes", "review_notes"):
        if data.get(key) == "":
            data[key] = None
    candidate = {**(current or {}), **data}
    if current is None:
        data["name"] = _need(data.get("name"), "Nome da disciplina")
    elif "name" in data:
        data["name"] = _need(data["name"], "Nome da disciplina")
    if "workload_minutes" in data and data["workload_minutes"] is not None:
        try:
            minutes = int(data["workload_minutes"])
        except (TypeError, ValueError) as error:
            raise DomainError("Carga horária deve ser informada em minutos como um número inteiro.") from error
        if minutes <= 0:
            raise DomainError("Carga horária deve ser maior que zero.")
        data["workload_minutes"] = minutes
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
    start, end = candidate.get("start_date"), candidate.get("end_date")
    if start:
        _date(start, "Data de início")
    if end:
        _date(end, "Data de término")
    if start and end and start > end:
        raise DomainError("A data de término não pode ser anterior à data de início.")
    return data


def create_curriculum(conn, formation_id, values):
    _active_formation(conn, formation_id)
    data = _curriculum_data(values)
    data.update({"formation_id": formation_id})
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
    ordinary = {key: value for key, value in data.items() if key not in {"academic_status", "review_status", "review_priority", "review_notes"}}
    if ordinary: repo.update(conn, "disciplinas_grade", ident, ordinary)
    if any(key in data for key in {"academic_status", "review_status", "review_priority", "review_notes"}):
        return change_curriculum_status(conn, ident, data, "manual", values.get("status_notes"))
    return _get(conn, "disciplinas_grade", ident)


def curriculum_status_history(conn, ident):
    _get(conn, "disciplinas_grade", ident)
    return repo.many(conn, "SELECT * FROM curriculum_status_history WHERE curriculum_subject_id=? ORDER BY created_at DESC,id DESC", (ident,))


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
        _delete_study_graph(conn, preview["dependencies"]["study_subjects"]["ids"])
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


def _assert_study_accessible(conn, ident, require_current=False):
    study = _get(conn, "materias_estudo", ident)
    if study["archived_at"] or study["status"] == "archived":
        raise DomainError("Este estudo está arquivado. Restaure-o antes de iniciar o foco.", 409, "study_archived")
    curriculum_item = _get(conn, "disciplinas_grade", study["curriculum_subject_id"]) if study["curriculum_subject_id"] else None
    if curriculum_item and curriculum_item["archived_at"]:
        raise DomainError("A disciplina deste estudo está arquivada. Restaure-a antes de iniciar o foco.", 409, "archived_parent")
    formation_id = _study_formation_id(study, curriculum_item)
    if formation_id and _get(conn, "formacoes", formation_id)["archived_at"]:
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
    parent_active = "s.archived_at IS NULL AND s.status<>'archived' AND (d.id IS NULL OR d.archived_at IS NULL) AND (f.id IS NULL OR f.archived_at IS NULL)"
    clauses, params = [], []
    if visibility == "active": clauses.append(parent_active + " AND s.status='active'")
    elif visibility == "paused": clauses.append(parent_active + " AND s.status='paused'")
    elif visibility == "review": clauses.append(parent_active + " AND d.review_status IN ('queued','in_progress')")
    elif visibility == "completed": clauses.append(parent_active + " AND s.status='completed'")
    elif visibility == "archived": clauses.append("s.archived_at IS NOT NULL OR s.status='archived' OR d.archived_at IS NOT NULL OR f.archived_at IS NOT NULL")
    if formation_id not in (None, ""):
        try: selected_formation = int(formation_id)
        except (TypeError, ValueError) as error: raise DomainError("Formação do filtro é inválida.") from error
        clauses.append("COALESCE(s.related_formation_id,d.formation_id)=?"); params.append(selected_formation)
    if q and str(q).strip():
        clauses.append("COALESCE(d.name,s.personal_name) LIKE ? COLLATE NOCASE"); params.append(f"%{str(q).strip()}%")
    if review:
        if review not in REVIEW_STATUSES: raise DomainError("Filtro de revisão inválido.")
        clauses.append("COALESCE(d.review_status,'none')=?"); params.append(review)
    where = (" WHERE " + " AND ".join(f"({clause})" for clause in clauses)) if clauses else ""
    sql = """
        SELECT s.*, COALESCE(d.name,s.personal_name) name, f.name formation_name,
          d.academic_status, d.review_status, d.item_type, d.archived_at curriculum_archived_at,
          f.archived_at formation_archived_at,
          CASE WHEN s.archived_at IS NOT NULL OR s.status='archived' THEN 'study_archived'
               WHEN d.archived_at IS NOT NULL THEN 'curriculum_archived'
               WHEN f.archived_at IS NOT NULL THEN 'formation_archived'
               ELSE NULL END visibility_reason,
          COALESCE((SELECT ROUND(AVG(t.mastery),1) FROM topicos t WHERE t.study_subject_id=s.id AND t.archived_at IS NULL),0) mastery_average,
          (SELECT COUNT(*) FROM topicos t WHERE t.study_subject_id=s.id AND t.archived_at IS NULL AND t.status<>'completed') pending_topics,
          (SELECT COUNT(*) FROM topicos t WHERE t.study_subject_id=s.id AND t.archived_at IS NULL) topic_count,
          (SELECT COUNT(*) FROM topicos t WHERE t.study_subject_id=s.id AND t.archived_at IS NULL AND t.status='completed') completed_topics,
          COALESCE((SELECT SUM(x.duration_seconds) FROM sessoes_estudo x WHERE x.study_subject_id=s.id AND x.date BETWEEN ? AND ?),0) week_seconds,
          COALESCE((SELECT SUM(p.planned_duration_minutes) FROM sessoes_planejadas p WHERE p.study_subject_id=s.id AND p.status='planned' AND p.scheduled_date BETWEEN ? AND ?),0) planned_week_minutes
        FROM materias_estudo s
        LEFT JOIN disciplinas_grade d ON d.id=s.curriculum_subject_id
        LEFT JOIN formacoes f ON f.id=COALESCE(s.related_formation_id,d.formation_id)
    """ + where + " ORDER BY s.favorite DESC,s.priority DESC,s.created_at DESC"
    values = repo.many(conn, sql, (week_start.isoformat(), week_end.isoformat(), week_start.isoformat(), week_end.isoformat(), *params))
    for value in values:
        value["progress_percent"] = round(value["completed_topics"] * 100 / value["topic_count"]) if value["topic_count"] else 0
        value["visibility_reason_label"] = {
            "study_archived": "Estudo arquivado", "curriculum_archived": "Disciplina arquivada",
            "formation_archived": "Formação arquivada",
        }.get(value["visibility_reason"])
    return values


def add_curriculum_study(conn, curriculum_id, values):
    curriculum_item = _get(conn, "disciplinas_grade", curriculum_id)
    _active_formation(conn, curriculum_item["formation_id"])
    if curriculum_item["archived_at"]:
        raise DomainError("Restaure a disciplina antes de adicioná-la aos estudos atuais.", 409, "curriculum_archived")
    if curriculum_item["item_type"] != "subject":
        raise DomainError("Uma linha estrutural não pode ser adicionada aos estudos atuais.", 409, "curriculum_section")
    if curriculum_item["academic_status"] not in ("available", "in_progress"): raise DomainError("A disciplina precisa estar disponível para entrar nos estudos atuais.")
    data = _fields(values, STUDY); data.update({"origin":"curriculum", "curriculum_subject_id":curriculum_id, "priority":data.get("priority",3), "difficulty":data.get("difficulty",3), "status":"active"})
    try: ident = repo.insert(conn, "materias_estudo", data)
    except sqlite3.IntegrityError as error: raise DomainError("Esta disciplina já está nos estudos atuais.", 409) from error
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


def create_personal_study(conn, values):
    data = _fields(values, STUDY | {"related_formation_id", "personal_name"})
    if data.get("related_formation_id"):
        _active_formation(conn, int(data["related_formation_id"]))
    data.update({"origin":"personal", "personal_name":_need(data.get("personal_name"), "Nome do estudo"), "priority":data.get("priority",3), "difficulty":data.get("difficulty",3), "status":"active"})
    return _get(conn, "materias_estudo", repo.insert(conn, "materias_estudo", data))


def update_study(conn, ident, values):
    study = _get(conn, "materias_estudo", ident); data = _fields(values, STUDY | {"personal_name", "related_formation_id"})
    if study["archived_at"] or study["status"] == "archived":
        raise DomainError("Restaure o estudo antes de editá-lo.", 409, "study_archived")
    if data.get("status") == "archived":
        raise DomainError("Use a ação Arquivar para arquivar um estudo.", 400, "use_archive_action")
    if study["origin"] == "curriculum" and data.get("status") == "completed":
        raise DomainError("Use a ação Finalizar para encerrar um estudo curricular.", 400, "use_finish_action")
    if study["origin"] == "curriculum": data.pop("personal_name", None); data.pop("related_formation_id", None)
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


def subject_detail(conn, ident):
    study = _get(conn, "materias_estudo", ident)
    groups = repo.many(conn, "SELECT * FROM grupos_topicos WHERE study_subject_id=? AND archived_at IS NULL ORDER BY sort_order,name", (ident,))
    topics = repo.many(conn, "SELECT * FROM topicos WHERE study_subject_id=? AND archived_at IS NULL ORDER BY sort_order,name", (ident,))
    nested = defaultdict(list)
    for topic in topics: nested[topic["group_id"]].append(topic)
    study["groups"] = [{**group, "topics":nested.pop(group["id"], [])} for group in groups]
    study["ungrouped_topics"] = nested.get(None, [])
    return study


def create_group(conn, study_id, values):
    _get(conn, "materias_estudo", study_id)
    return _get(conn, "grupos_topicos", repo.insert(conn, "grupos_topicos", {"study_subject_id":study_id,"name":_need(values.get("name"),"Nome da unidade"),"sort_order":values.get("sort_order",0)}))


def create_topic(conn, study_id, values):
    _get(conn, "materias_estudo", study_id); group_id = values.get("group_id")
    if group_id and _get(conn, "grupos_topicos", group_id)["study_subject_id"] != study_id: raise DomainError("A unidade precisa pertencer ao mesmo estudo.")
    data = _fields(values, {"name","description","group_id","difficulty","sort_order","mastery","status"})
    data.update({"study_subject_id":study_id,"name":_need(data.get("name"),"Nome do tópico")}); data.setdefault("status","not_started"); data.setdefault("mastery",0); data.setdefault("sort_order",0)
    data["manual_mastery"] = data["mastery"]
    return _get(conn, "topicos", repo.insert(conn,"topicos",data))


def update_topic(conn, ident, values):
    topic = _get(conn,"topicos",ident); data = _fields(values,{"name","description","group_id","difficulty","sort_order","mastery","status"})
    if data.get("group_id") and _get(conn,"grupos_topicos",data["group_id"])["study_subject_id"] != topic["study_subject_id"]: raise DomainError("A unidade precisa pertencer ao mesmo estudo.")
    if "mastery" in data: data["manual_mastery"] = data["mastery"]
    if data.get("status") == "completed": data["completed_at"] = _today()
    if "status" in data and data["status"] != "completed": data["completed_at"] = None
    repo.update(conn,"topicos",ident,data); return _get(conn,"topicos",ident)


def _recalculate_mastery(conn, topic_id):
    if not topic_id: return
    last = repo.one(conn,"SELECT mastery_after FROM sessoes_estudo WHERE topic_id=? AND mastery_after IS NOT NULL ORDER BY date DESC,id DESC LIMIT 1",(topic_id,))
    repo.update(conn,"topicos",topic_id,{"mastery":last["mastery_after"] if last else _get(conn,"topicos",topic_id)["manual_mastery"]})


def create_session(conn, values):
    study_id = _need(values.get("study_subject_id"),"Matéria"); _assert_study_accessible(conn, study_id); topic_id=values.get("topic_id")
    if topic_id and _get(conn,"topicos",topic_id)["study_subject_id"] != study_id: raise DomainError("O tópico precisa pertencer à matéria selecionada.")
    seconds=int(_need(values.get("duration_seconds"),"Duração"))
    if seconds<=0: raise DomainError("A duração deve ser maior que zero.")
    data=_fields(values,{"study_subject_id","topic_id","planned_session_id","date","started_at","ended_at","duration_seconds","entry_method","mastery_before","mastery_after","progress_level","notes"})
    data.update({"study_subject_id":study_id,"duration_seconds":seconds,"date":data.get("date",_today()),"entry_method":data.get("entry_method","manual")})
    _date(data["date"])
    if data.get("mastery_after") is not None and not 0 <= int(data["mastery_after"]) <= 5: raise DomainError("Domínio deve estar entre 0 e 5.")
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
    if topic_id and data.get("mastery_before") is None: data["mastery_before"]=_get(conn,"topicos",topic_id)["mastery"]
    if data.get("started_at") and data.get("ended_at"):
        data["duration_seconds"] = max(1, int((datetime.fromisoformat(str(data["ended_at"]).replace("Z","+00:00")) - datetime.fromisoformat(str(data["started_at"]).replace("Z","+00:00"))).total_seconds()))
    ident=repo.insert(conn,"sessoes_estudo",data); _recalculate_mastery(conn,topic_id)
    completed = values.get("topic_completed") in (True,1,"1","true","True","sim")
    if completed:
        if not topic_id: raise DomainError("Concluir tópico exige selecionar um tópico.")
        repo.update(conn,"topicos",topic_id,{"status":"completed","completed_at":data["date"]})
    if topic_id and data["entry_method"] != "review":
        if _get(conn,"topicos",topic_id)["status"] == "not_started": repo.update(conn,"topicos",topic_id,{"status":"in_progress"})
        _start_review_chain(conn, topic_id, ident, _date(data["date"]))
    session = _get(conn,"sessoes_estudo",ident)
    if completed: session["topic_completed"] = True
    return session


def update_session(conn, ident, values):
    old=_get(conn,"sessoes_estudo",ident); data=_fields(values,{"study_subject_id","date","started_at","ended_at","duration_seconds","entry_method","mastery_before","mastery_after","progress_level","notes","topic_id"})
    topic_id=data.get("topic_id",old["topic_id"]); study_id=data.get("study_subject_id",old["study_subject_id"])
    if topic_id and _get(conn,"topicos",topic_id)["study_subject_id"] != study_id: raise DomainError("O tópico precisa pertencer à matéria selecionada.")
    if data.get("started_at") and data.get("ended_at"): data["duration_seconds"] = max(1,int((datetime.fromisoformat(str(data["ended_at"]).replace("Z","+00:00"))-datetime.fromisoformat(str(data["started_at"]).replace("Z","+00:00"))).total_seconds()))
    if "duration_seconds" in data and int(data["duration_seconds"])<=0: raise DomainError("A duração deve ser maior que zero.")
    if "date" in data: _date(data["date"])
    if data.get("mastery_after") is not None and not 0 <= int(data["mastery_after"]) <= 5: raise DomainError("Domínio deve estar entre 0 e 5.")
    changed_source = any(key in data for key in ("topic_id","date","entry_method"))
    if changed_source: conn.execute("UPDATE revisoes SET status='cancelled' WHERE root_session_id=? AND status='pending'",(ident,))
    repo.update(conn,"sessoes_estudo",ident,data); _recalculate_mastery(conn,old["topic_id"]); _recalculate_mastery(conn,topic_id)
    if changed_source and topic_id and data.get("entry_method",old["entry_method"]) != "review": _start_review_chain(conn,topic_id,ident,_date(data.get("date",old["date"])))
    if values.get("topic_completed") in (True,1,"1","true","True","sim"):
        if not topic_id: raise DomainError("Concluir tópico exige selecionar um tópico.")
        repo.update(conn,"topicos",topic_id,{"status":"completed","completed_at":data.get("date",old["date"])})
    return _get(conn,"sessoes_estudo",ident)


def delete_session(conn, ident):
    old=_get(conn,"sessoes_estudo",ident); conn.execute("UPDATE revisoes SET status='cancelled' WHERE root_session_id=? AND status='pending'",(ident,)); remove(conn,"sessoes_estudo",ident); _recalculate_mastery(conn,old["topic_id"])


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
        if topic["study_subject_id"] != study_subject_id:
            raise DomainError("O tópico precisa pertencer à matéria selecionada.")
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


def evaluations(conn, study_id=None):
    sql="SELECT e.*,COALESCE(s.personal_name,d.name) subject_name FROM avaliacoes e JOIN materias_estudo s ON s.id=e.study_subject_id LEFT JOIN disciplinas_grade d ON d.id=s.curriculum_subject_id"; params=()
    if study_id: sql += " WHERE e.study_subject_id=?"; params=(study_id,)
    return repo.many(conn, sql + " ORDER BY e.date", params)


def create_evaluation(conn, values):
    study=_need(values.get("study_subject_id"),"Matéria"); _get(conn,"materias_estudo",study)
    data=_fields(values,{"study_subject_id","title","type","date","weight","max_score","score","status","notes"}); data.update({"study_subject_id":study,"title":_need(data.get("title"),"Título"),"type":data.get("type","exam"),"date":_need(data.get("date"),"Data")})
    ident = repo.insert(conn,"avaliacoes",data)
    for topic_id in values.get("topic_ids", []):
        if _get(conn,"topicos",topic_id)["study_subject_id"] != study: raise DomainError("Todos os tópicos precisam pertencer à matéria da avaliação.")
        conn.execute("INSERT INTO avaliacao_topicos(evaluation_id,topic_id) VALUES (?,?)",(ident,topic_id))
    return _get(conn,"avaliacoes",ident)


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


def availability_windows(conn, current):
    recurring=[(_clock_minutes(item["start_time"]),_clock_minutes(item["end_time"])) for item in availability(conn) if item["enabled"] and item["weekday"]==current.weekday()]
    exceptions=availability_exceptions(conn,current.isoformat(),current.isoformat())
    windows=_merge(recurring+[(_clock_minutes(item["start_time"]),_clock_minutes(item["end_time"])) for item in exceptions if item["kind"]=="available"])
    return _subtract(windows,[(_clock_minutes(item["start_time"]),_clock_minutes(item["end_time"])) for item in exceptions if item["kind"]=="unavailable"])


def planned(conn,start,end):
    sql="SELECT p.*,COALESCE(s.personal_name,d.name) subject_name,t.name topic_name FROM sessoes_planejadas p JOIN materias_estudo s ON s.id=p.study_subject_id LEFT JOIN disciplinas_grade d ON d.id=s.curriculum_subject_id LEFT JOIN formacoes f ON f.id=COALESCE(s.related_formation_id,d.formation_id) LEFT JOIN topicos t ON t.id=p.topic_id WHERE p.scheduled_date BETWEEN ? AND ? AND p.status='planned' AND s.archived_at IS NULL AND s.status<>'archived' AND (d.id IS NULL OR d.archived_at IS NULL) AND (f.id IS NULL OR f.archived_at IS NULL) ORDER BY p.scheduled_date,p.start_time"
    return repo.many(conn,sql,(start,end))


def planned_detail(conn, ident):
    row = repo.one(conn,"SELECT p.*,COALESCE(s.personal_name,d.name) subject_name,t.name topic_name FROM sessoes_planejadas p JOIN materias_estudo s ON s.id=p.study_subject_id LEFT JOIN disciplinas_grade d ON d.id=s.curriculum_subject_id LEFT JOIN topicos t ON t.id=p.topic_id WHERE p.id=?",(ident,))
    if not row: raise DomainError("Sessão planejada não encontrada.",404)
    return row


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


def create_planned(conn,values,source="manual"):
    study=int(_need(values.get("study_subject_id"),"Matéria")); _assert_study_accessible(conn, study)
    data=_fields(values,{"study_subject_id","topic_id","scheduled_date","start_time","planned_duration_minutes"}); data.update({"study_subject_id":study,"scheduled_date":_need(data.get("scheduled_date"),"Data"),"planned_duration_minutes":int(_need(data.get("planned_duration_minutes"),"Duração")),"source":source})
    if data["planned_duration_minutes"] <= 0: raise DomainError("A duração deve ser maior que zero.")
    if data.get("start_time") is not None: _clock_minutes(data["start_time"])
    if data.get("topic_id") and _get(conn,"topicos",data["topic_id"])["study_subject_id"] != study: raise DomainError("O tópico precisa pertencer à matéria selecionada.")
    return _get(conn,"sessoes_planejadas",repo.insert(conn,"sessoes_planejadas",data))


def update_planned(conn, ident, values):
    current = planned_detail(conn,ident)
    data = _fields(values,{"study_subject_id","topic_id","scheduled_date","start_time","planned_duration_minutes","status"})
    candidate = {**current, **data}
    if candidate["status"] not in ("planned","completed","skipped","rescheduled","cancelled"): raise DomainError("Status de planejamento inválido.")
    if int(candidate["planned_duration_minutes"]) <= 0: raise DomainError("A duração deve ser maior que zero.")
    if candidate.get("start_time") is not None: _clock_minutes(candidate["start_time"])
    _assert_study_accessible(conn, candidate["study_subject_id"])
    if candidate.get("topic_id") and _get(conn,"topicos",candidate["topic_id"])["study_subject_id"] != candidate["study_subject_id"]: raise DomainError("O tópico precisa pertencer à matéria selecionada.")
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
    if duration <= 0 or pause < 0: raise DomainError("As preferências do planejamento são inválidas.")
    return {"default_session_minutes": duration, "planning_break_minutes": pause}


def generate_plan(conn,start,days=7):
    first=_date(start); end=(first+timedelta(days=days-1)).isoformat(); proposal=[]; candidates=studies(conn, week_reference=first.isoformat())
    preferences = planning_preferences(conn)
    duration, pause = preferences["default_session_minutes"], preferences["planning_break_minutes"]
    skipped_without_goal = []
    for subject in candidates:
        goal = subject["weekly_goal_minutes"]
        if not goal:
            subject["remaining_minutes"] = 0
            skipped_without_goal.append(subject["name"])
        else:
            subject["remaining_minutes"] = max(0, int(goal) - int(subject["week_seconds"] or 0) // 60 - int(subject["planned_week_minutes"] or 0))
    existing=planned(conn,start,end)
    for offset in range(days):
        current=first+timedelta(days=offset); reserved=[(_clock_minutes(item["start_time"]),_clock_minutes(item["start_time"])+int(item["planned_duration_minutes"])) for item in existing if item["scheduled_date"]==current.isoformat() and item["start_time"]]
        for window_start,window_end in _subtract(availability_windows(conn,current),reserved):
            cursor=window_start
            while cursor + duration <= window_end:
                eligible=[item for item in candidates if item["remaining_minutes"] > 0]
                if not eligible: break
                subject=max(eligible,key=lambda item:item["priority"]*3+item["difficulty"]*2+item["pending_topics"]+(2 if item["week_seconds"]<item["weekly_goal_minutes"]*60 else 0))
                topic=repo.one(conn,"SELECT * FROM topicos WHERE study_subject_id=? AND archived_at IS NULL AND status<>'completed' ORDER BY CASE status WHEN 'in_progress' THEN 0 ELSE 1 END,mastery,sort_order LIMIT 1",(subject["id"],))
                proposal.append({"study_subject_id":subject["id"],"topic_id":topic["id"] if topic else None,"scheduled_date":current.isoformat(),"start_time":f"{cursor//60:02d}:{cursor%60:02d}","planned_duration_minutes":duration,"subject_name":subject["name"],"topic_name":topic["name"] if topic else None,"reason":f"Meta restante de {subject['remaining_minutes']} min; prioridade {subject['priority']}/5; dificuldade {subject['difficulty']}/5."})
                subject["remaining_minutes"] -= duration; cursor += duration + pause
    return {"start":start,"end":end,"sessions":proposal,"preferences":preferences,"skipped_without_goal":skipped_without_goal}


def recommendation(conn):
    candidates=studies(conn)
    if not candidates: return None
    subject=max(candidates,key=lambda item:item["priority"]*4+item["difficulty"]*2+item["pending_topics"])
    topic=repo.one(conn,"SELECT * FROM topicos WHERE study_subject_id=? AND archived_at IS NULL AND status<>'completed' ORDER BY mastery,sort_order LIMIT 1",(subject["id"],))
    reasons=[f"prioridade {subject['priority']}/5",f"{subject['pending_topics']} tópicos pendentes"]
    if topic: reasons.append(f"domínio {topic['mastery']}/5 em {topic['name']}")
    return {"study_subject":subject,"topic":topic,"recommended_duration":50,"reasons":reasons,"alternatives":[item["name"] for item in candidates if item["id"]!=subject["id"]][:3]}


def search(conn, query):
    term = str(query or "").strip()
    if len(term) < 2: return {"formations": [], "curriculum": [], "studies": [], "topics": []}
    like = f"%{term}%"
    return {
        "formations": repo.many(conn, "SELECT id,name,institution FROM formacoes WHERE archived_at IS NULL AND name LIKE ? COLLATE NOCASE ORDER BY name LIMIT 10", (like,)),
        "curriculum": repo.many(conn, "SELECT d.id,d.name,d.formation_id,f.name formation_name FROM disciplinas_grade d JOIN formacoes f ON f.id=d.formation_id WHERE d.archived_at IS NULL AND d.name LIKE ? COLLATE NOCASE ORDER BY d.name LIMIT 10", (like,)),
        "studies": repo.many(conn, "SELECT s.id,COALESCE(d.name,s.personal_name) name FROM materias_estudo s LEFT JOIN disciplinas_grade d ON d.id=s.curriculum_subject_id WHERE s.archived_at IS NULL AND COALESCE(d.name,s.personal_name) LIKE ? COLLATE NOCASE ORDER BY name LIMIT 10", (like,)),
        "topics": repo.many(conn, "SELECT t.id,t.name,t.study_subject_id,COALESCE(d.name,s.personal_name) subject_name FROM topicos t JOIN materias_estudo s ON s.id=t.study_subject_id LEFT JOIN disciplinas_grade d ON d.id=s.curriculum_subject_id WHERE t.archived_at IS NULL AND t.name LIKE ? COLLATE NOCASE ORDER BY t.name LIMIT 10", (like,)),
    }


def reviews(conn):
    return repo.many(conn,"SELECT r.*,t.name topic_name,COALESCE(s.personal_name,d.name) subject_name FROM revisoes r JOIN topicos t ON t.id=r.topic_id JOIN materias_estudo s ON s.id=t.study_subject_id LEFT JOIN disciplinas_grade d ON d.id=s.curriculum_subject_id WHERE r.status='pending' ORDER BY r.due_date")
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
        create_session(conn,{"study_subject_id":topic["study_subject_id"],"topic_id":topic["id"],"date":_today(),"duration_seconds":int(duration_seconds),"entry_method":"review","notes":notes})
    return _get(conn,"revisoes",ident)


def history(conn,start=None,end=None,limit=100):
    clauses=[]; params=[]
    if start: clauses.append("x.date>=?"); params.append(start)
    if end: clauses.append("x.date<=?"); params.append(end)
    where=("WHERE "+" AND ".join(clauses)) if clauses else ""
    sql="SELECT x.*,COALESCE(s.personal_name,d.name) subject_name,t.name topic_name FROM sessoes_estudo x JOIN materias_estudo s ON s.id=x.study_subject_id LEFT JOIN disciplinas_grade d ON d.id=s.curriculum_subject_id LEFT JOIN topicos t ON t.id=x.topic_id "+where+" ORDER BY x.date DESC,x.id DESC LIMIT ?"
    return repo.many(conn,sql,(*params,limit))


def analytics(conn):
    total=repo.one(conn,"SELECT COALESCE(SUM(duration_seconds),0) seconds,COUNT(*) sessions,COUNT(DISTINCT date) days FROM sessoes_estudo")
    today = _local_now().date()
    week_start, week_end = _week_bounds(today.isoformat())
    month_start = today.replace(day=1)
    month_end = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    today_total = repo.one(conn,"SELECT COALESCE(SUM(duration_seconds),0) seconds FROM sessoes_estudo WHERE date=?",(today.isoformat(),))
    week=repo.one(conn,"SELECT COALESCE(SUM(duration_seconds),0) seconds FROM sessoes_estudo WHERE date BETWEEN ? AND ?",(week_start.isoformat(),week_end.isoformat()))
    month=repo.one(conn,"SELECT COALESCE(SUM(duration_seconds),0) seconds FROM sessoes_estudo WHERE date BETWEEN ? AND ?",(month_start.isoformat(),month_end.isoformat()))
    subjects=repo.many(conn,"SELECT COALESCE(s.personal_name,d.name) name,SUM(x.duration_seconds) seconds FROM sessoes_estudo x JOIN materias_estudo s ON s.id=x.study_subject_id LEFT JOIN disciplinas_grade d ON d.id=s.curriculum_subject_id GROUP BY s.id ORDER BY seconds DESC")
    completed_blocks = repo.one(conn, "SELECT COUNT(*) count FROM sessoes_planejadas WHERE status='completed'")
    orphan_completed_blocks = repo.one(conn, """
        SELECT COUNT(*) count FROM sessoes_planejadas p
        WHERE p.status='completed' AND NOT EXISTS (
          SELECT 1 FROM sessoes_estudo s WHERE s.planned_session_id=p.id
        )
    """)
    academic_distribution = repo.many(conn, """
        SELECT academic_status status, COUNT(*) count FROM disciplinas_grade
        WHERE archived_at IS NULL AND item_type='subject' GROUP BY academic_status
    """)
    next_pending = repo.many(conn, """
        SELECT d.id,d.name,d.formation_id,f.name formation_name,d.period,d.academic_status,d.review_status
        FROM disciplinas_grade d JOIN formacoes f ON f.id=d.formation_id
        WHERE d.archived_at IS NULL AND d.item_type='subject' AND f.archived_at IS NULL
          AND d.academic_status NOT IN ('completed','exempted')
        ORDER BY CASE d.academic_status WHEN 'in_progress' THEN 0 WHEN 'available' THEN 1 ELSE 2 END,d.sort_order,d.name
        LIMIT 12
    """)
    return {
        "total_seconds":total["seconds"], "sessions":total["sessions"], "real_sessions":total["sessions"],
        "days_studied":total["days"], "today_seconds":today_total["seconds"], "week_seconds":week["seconds"],
        "month_seconds":month["seconds"], "by_subject":subjects,
        "completed_planned_blocks": int(completed_blocks["count"] or 0),
        "completed_planned_without_real_session": int(orphan_completed_blocks["count"] or 0),
        "academic_progress": formations(conn, "all"), "academic_distribution": academic_distribution,
        "next_pending_subjects": next_pending,
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
    allowed = {"daily_goal_minutes", "weekly_goal_minutes", "default_session_minutes", "planning_break_minutes", "review_strategy", "theme"}
    for key, value in values.items():
        if key in allowed: conn.execute("INSERT INTO configuracoes(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')",(key,str(value) if value is not None else None))
    return settings(conn)


def change_record(conn, table, ident, values, allowed):
    _get(conn, table, ident)
    data = _fields(values, allowed)
    if "name" in data: data["name"] = _need(data["name"], "Nome")
    if "title" in data: data["title"] = _need(data["title"], "Título")
    repo.update(conn, table, ident, data)
    return _get(conn, table, ident)
