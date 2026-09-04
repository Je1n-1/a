"""Regras de negócio da V2. Nenhuma rota contém SQL ou decisões do produto."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
import json
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
CURRICULUM = {"name", "code", "period", "workload_minutes", "academic_status", "sort_order", "start_date", "end_date", "notes"}
STUDY = {"favorite", "priority", "difficulty", "weekly_goal_minutes", "start_date", "target_date", "status", "academic_period", "result", "final_score"}


def formations(conn, visibility="active"):
    if visibility not in {"active", "archived", "all"}:
        raise DomainError("Filtro de formações inválido.")
    where = {"active": "WHERE f.archived_at IS NULL", "archived": "WHERE f.archived_at IS NOT NULL", "all": ""}[visibility]
    sql = "SELECT f.*,COUNT(DISTINCT d.id) curriculum_count,COUNT(DISTINCT s.id) active_studies FROM formacoes f LEFT JOIN disciplinas_grade d ON d.formation_id=f.id AND d.archived_at IS NULL LEFT JOIN materias_estudo s ON (s.related_formation_id=f.id OR s.curriculum_subject_id=d.id) AND s.status IN ('active','paused') " + where + " GROUP BY f.id ORDER BY f.created_at DESC"
    return repo.many(conn, sql)


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


def archive(conn, table, ident, restore=False):
    _get(conn, table, ident)
    values = {"archived_at": None if restore else _now()}
    if table == "formacoes": values["status"] = "active" if restore else "archived"
    if table == "materias_estudo": values["status"] = "active" if restore else "archived"
    repo.update(conn, table, ident, values); return _get(conn, table, ident)


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
    repo.delete(conn, "formacoes", ident)


def curriculum(conn, formation_id, include_archived=False):
    _get(conn, "formacoes", formation_id)
    hidden = "" if include_archived else "AND d.archived_at IS NULL"
    return repo.many(conn, "SELECT d.*,s.id active_study_id FROM disciplinas_grade d LEFT JOIN materias_estudo s ON s.curriculum_subject_id=d.id AND s.status IN ('active','paused') WHERE d.formation_id=? " + hidden + " ORDER BY d.sort_order,d.name", (formation_id,))


def _curriculum_data(values, current=None):
    data = _fields(values, CURRICULUM)
    for key in ("code", "period", "start_date", "end_date", "notes"):
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
    if status not in grade_import.ACADEMIC_STATUSES:
        raise DomainError("Status acadêmico inválido.")
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
    data.setdefault("academic_status", "not_available"); data.setdefault("sort_order", 0)
    try: ident = repo.insert(conn, "disciplinas_grade", data)
    except sqlite3.IntegrityError as error: raise DomainError("Já existe uma disciplina com esse nome nesta formação.", 409) from error
    return _get(conn, "disciplinas_grade", ident)


def update_curriculum(conn, ident, values):
    current = _get(conn, "disciplinas_grade", ident)
    _active_formation(conn, current["formation_id"])
    data = _curriculum_data(values, current)
    repo.update(conn, "disciplinas_grade", ident, data); return _get(conn, "disciplinas_grade", ident)


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
            repo.update(conn, "disciplinas_grade", existing_id, _curriculum_data(values, _get(conn, "disciplinas_grade", existing_id)))
            updated.append(_get(conn, "disciplinas_grade", existing_id))
    return {
        "inserted": inserted,
        "updated": updated,
        "skipped": skipped,
        "summary": {"requested": len(items), "inserted": len(inserted), "updated": len(updated), "skipped": len(skipped)},
    }


def studies(conn, include_archived=False, week_reference=None):
    week_start, week_end = _week_bounds(week_reference)
    visibility = "" if include_archived else "WHERE s.archived_at IS NULL"
    sql = "SELECT s.*,COALESCE(d.name,s.personal_name) name,f.name formation_name,COALESCE((SELECT ROUND(AVG(t.mastery),1) FROM topicos t WHERE t.study_subject_id=s.id AND t.archived_at IS NULL),0) mastery_average,(SELECT COUNT(*) FROM topicos t WHERE t.study_subject_id=s.id AND t.archived_at IS NULL AND t.status<>'completed') pending_topics,(SELECT COUNT(*) FROM topicos t WHERE t.study_subject_id=s.id AND t.archived_at IS NULL) topic_count,(SELECT COUNT(*) FROM topicos t WHERE t.study_subject_id=s.id AND t.archived_at IS NULL AND t.status='completed') completed_topics,COALESCE((SELECT SUM(x.duration_seconds) FROM sessoes_estudo x WHERE x.study_subject_id=s.id AND x.date BETWEEN ? AND ?),0) week_seconds,COALESCE((SELECT SUM(p.planned_duration_minutes) FROM sessoes_planejadas p WHERE p.study_subject_id=s.id AND p.status='planned' AND p.scheduled_date BETWEEN ? AND ?),0) planned_week_minutes FROM materias_estudo s LEFT JOIN disciplinas_grade d ON d.id=s.curriculum_subject_id LEFT JOIN formacoes f ON f.id=COALESCE(s.related_formation_id,d.formation_id) " + visibility + " ORDER BY s.favorite DESC,s.priority DESC,s.created_at DESC"
    values = repo.many(conn, sql, (week_start.isoformat(), week_end.isoformat(), week_start.isoformat(), week_end.isoformat()))
    for value in values:
        value["progress_percent"] = round(value["completed_topics"] * 100 / value["topic_count"]) if value["topic_count"] else 0
    return values


def add_curriculum_study(conn, curriculum_id, values):
    curriculum_item = _get(conn, "disciplinas_grade", curriculum_id)
    _active_formation(conn, curriculum_item["formation_id"])
    if curriculum_item["academic_status"] not in ("available", "in_progress"): raise DomainError("A disciplina precisa estar disponível para entrar nos estudos atuais.")
    data = _fields(values, STUDY); data.update({"origin":"curriculum", "curriculum_subject_id":curriculum_id, "priority":data.get("priority",3), "difficulty":data.get("difficulty",3), "status":"active"})
    try: ident = repo.insert(conn, "materias_estudo", data)
    except sqlite3.IntegrityError as error: raise DomainError("Esta disciplina já está nos estudos atuais.", 409) from error
    repo.update(conn, "disciplinas_grade", curriculum_id, {"academic_status":"in_progress"})
    return _get(conn, "materias_estudo", ident)


def create_personal_study(conn, values):
    data = _fields(values, STUDY | {"related_formation_id", "personal_name"})
    data.update({"origin":"personal", "personal_name":_need(data.get("personal_name"), "Nome do estudo"), "priority":data.get("priority",3), "difficulty":data.get("difficulty",3), "status":"active"})
    return _get(conn, "materias_estudo", repo.insert(conn, "materias_estudo", data))


def update_study(conn, ident, values):
    study = _get(conn, "materias_estudo", ident); data = _fields(values, STUDY | {"personal_name", "related_formation_id"})
    if study["origin"] == "curriculum": data.pop("personal_name", None); data.pop("related_formation_id", None)
    repo.update(conn, "materias_estudo", ident, data); return _get(conn, "materias_estudo", ident)


def finish_study(conn, ident, result, final_score=None):
    study = _get(conn, "materias_estudo", ident)
    statuses = {"approved":"completed", "failed":"failed", "withdrawn":"available", "exempted":"exempted"}
    if study["origin"] != "curriculum" or result not in statuses: raise DomainError("Resultado acadêmico inválido.")
    repo.update(conn, "materias_estudo", ident, {"status":"completed", "completed_at":_today(), "result":result, "final_score":final_score})
    repo.update(conn, "disciplinas_grade", study["curriculum_subject_id"], {"academic_status":statuses[result]})
    return _get(conn, "materias_estudo", ident)


def new_academic_attempt(conn, ident, values=None):
    previous = _get(conn, "materias_estudo", ident)
    if previous["origin"] != "curriculum" or previous["result"] not in ("failed", "withdrawn"):
        raise DomainError("Uma nova tentativa só está disponível após reprovação ou retirada.", 409)
    curriculum_id = previous["curriculum_subject_id"]
    maximum = repo.one(conn, "SELECT MAX(attempt_number) attempt FROM materias_estudo WHERE curriculum_subject_id=?", (curriculum_id,))
    copied = {"origin":"curriculum", "curriculum_subject_id":curriculum_id, "priority":previous["priority"], "difficulty":previous["difficulty"], "weekly_goal_minutes":previous["weekly_goal_minutes"], "start_date":(values or {}).get("start_date") or _today(), "target_date":(values or {}).get("target_date"), "status":"active", "academic_period":(values or {}).get("academic_period") or previous["academic_period"], "attempt_number":int(maximum["attempt"] or 0) + 1}
    created = _get(conn, "materias_estudo", repo.insert(conn, "materias_estudo", copied))
    repo.update(conn, "disciplinas_grade", curriculum_id, {"academic_status":"in_progress"})
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
    study_id = _need(values.get("study_subject_id"),"Matéria"); _get(conn,"materias_estudo",study_id); topic_id=values.get("topic_id")
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
    sql="SELECT p.*,COALESCE(s.personal_name,d.name) subject_name,t.name topic_name FROM sessoes_planejadas p JOIN materias_estudo s ON s.id=p.study_subject_id LEFT JOIN disciplinas_grade d ON d.id=s.curriculum_subject_id LEFT JOIN topicos t ON t.id=p.topic_id WHERE p.scheduled_date BETWEEN ? AND ? AND p.status='planned' ORDER BY p.scheduled_date,p.start_time"
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
    study=int(_need(values.get("study_subject_id"),"Matéria")); _get(conn,"materias_estudo",study)
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
    _get(conn,"materias_estudo",candidate["study_subject_id"])
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
    return {"total_seconds":total["seconds"],"sessions":total["sessions"],"days_studied":total["days"],"today_seconds":today_total["seconds"],"week_seconds":week["seconds"],"month_seconds":month["seconds"],"by_subject":subjects}


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
