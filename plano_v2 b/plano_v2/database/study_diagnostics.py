"""Diagnóstico e reconciliação explícita de estudos legados.

O objetivo deste módulo é tornar estados antigos visíveis sem "consertar" a
base silenciosamente. A leitura nunca altera o banco; a reconciliação só faz
alterações que vierem identificadas e confirmadas pelo usuário, sem apagar
sessões, tópicos, avaliações ou blocos.
"""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime
import sqlite3
from typing import Any
from config import LOCAL_TIMEZONE


CURRENT_STUDY_STATUSES = ("active", "paused")
ARCHIVED_STUDY_STATUS = "archived"


def _today(value: date | datetime | str | None = None) -> date:
    if value is None:
        return datetime.now(LOCAL_TIMEZONE).date()
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _row_dict(row: sqlite3.Row | tuple | None) -> dict[str, Any] | None:
    if row is None:
        return None
    if isinstance(row, sqlite3.Row):
        return dict(row)
    raise TypeError("A conexão de diagnóstico precisa usar sqlite3.Row.")


def _safe_positive_minutes(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        minutes = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError("O esforço deve ser informado em minutos inteiros.") from error
    if minutes <= 0:
        raise ValueError("O esforço deve ser maior que zero.")
    return minutes


def _safe_date(value: Any, label: str) -> str | None:
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value)).isoformat()
    except (TypeError, ValueError) as error:
        raise ValueError(f"{label} deve estar no formato AAAA-MM-DD.") from error


def _confirmed(value: Any) -> bool:
    return value is True or str(value).strip().lower() in {"1", "true", "yes", "sim", "confirm"}


def _issue(
    kind: str,
    message: str,
    *,
    severity: str = "warning",
    curriculum_subject_id: int | None = None,
    study_subject_id: int | None = None,
    formation_id: int | None = None,
    name: str | None = None,
    source: str | None = None,
    suggested_values: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": f"{kind}:{curriculum_subject_id or 'none'}:{study_subject_id or 'none'}",
        "kind": kind,
        "severity": severity,
        "message": message,
        "curriculum_subject_id": curriculum_subject_id,
        "study_subject_id": study_subject_id,
        "formation_id": formation_id,
        "name": name,
        "source": source,
        # A interface pode preencher um formulário com estes valores, mas nada
        # é gravado até chamar reconcile(..., confirm=True).
        "suggested_values": suggested_values or {},
    }


def _current_study_rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    placeholders = ",".join("?" for _ in CURRENT_STUDY_STATUSES)
    rows = conn.execute(
        f"""
        SELECT
            s.id study_subject_id,s.origin,s.curriculum_subject_id,s.related_formation_id,
            s.personal_name,s.status study_status,s.archived_at study_archived_at,
            s.start_date study_start_date,s.target_date study_target_date,
            s.required_study_minutes study_required_study_minutes,
            d.name curriculum_name,d.formation_id,d.academic_status,d.archived_at curriculum_archived_at,
            d.start_date curriculum_start_date,d.end_date curriculum_end_date,
            d.deadline_date,d.workload_minutes,d.required_study_minutes curriculum_required_study_minutes,
            f.name formation_name,f.archived_at formation_archived_at,
            (
              SELECT COUNT(*) FROM topicos t
              WHERE t.archived_at IS NULL
                AND (t.study_subject_id=s.id OR (
                  s.curriculum_subject_id IS NOT NULL AND t.curriculum_subject_id=s.curriculum_subject_id
                ))
            ) topic_count
        FROM materias_estudo s
        LEFT JOIN disciplinas_grade d ON d.id=s.curriculum_subject_id
        LEFT JOIN formacoes f ON f.id=COALESCE(s.related_formation_id,d.formation_id)
        WHERE s.status IN ({placeholders}) AND s.archived_at IS NULL
        ORDER BY COALESCE(d.name,s.personal_name) COLLATE NOCASE,s.id
        """,
        CURRENT_STUDY_STATUSES,
    ).fetchall()
    return [dict(row) for row in rows]


def diagnose_studies(conn: sqlite3.Connection, today: date | datetime | str | None = None) -> dict[str, Any]:
    """Lista inconsistências recuperáveis sem modificar registros.

    A estrutura é estável para a interface: cada item contém identificadores,
    mensagem e valores sugeridos que podem ser editados antes da reconciliação
    em lote.
    """
    current_day = _today(today)
    issues: list[dict[str, Any]] = []

    missing_current = conn.execute(
        """
        SELECT d.id curriculum_subject_id,d.formation_id,d.name,d.start_date,d.end_date,
               d.deadline_date,d.workload_minutes,d.required_study_minutes
        FROM disciplinas_grade d
        JOIN formacoes f ON f.id=d.formation_id
        WHERE d.academic_status='in_progress'
          AND d.archived_at IS NULL
          AND f.archived_at IS NULL
          AND NOT EXISTS (
            SELECT 1 FROM materias_estudo s
            WHERE s.curriculum_subject_id=d.id
              AND s.archived_at IS NULL
              AND s.status IN ('active','paused')
          )
          AND NOT EXISTS (
            SELECT 1 FROM curriculum_study_links l
            JOIN materias_estudo canonical ON canonical.id=l.canonical_study_id
            WHERE l.curriculum_subject_id=d.id
              AND canonical.archived_at IS NULL
              AND canonical.status IN ('active','paused')
          )
        ORDER BY d.name COLLATE NOCASE,d.id
        """
    ).fetchall()
    for row in missing_current:
        item = dict(row)
        proposed_effort = item["required_study_minutes"] or item["workload_minutes"]
        issues.append(_issue(
            "in_progress_without_current_study",
            "A disciplina está em andamento, mas não possui um estudo atual vinculado.",
            curriculum_subject_id=item["curriculum_subject_id"],
            formation_id=item["formation_id"],
            name=item["name"],
            suggested_values={
                "create_current_study": True,
                "start_date": item["start_date"] or current_day.isoformat(),
                "required_study_minutes": proposed_effort,
                "required_study_minutes_source": "curriculum" if item["required_study_minutes"] else (
                    "workload_minutes" if item["workload_minutes"] else "required"
                ),
                "deadline_date": item["deadline_date"] or item["end_date"],
            },
        ))

    for study in _current_study_rows(conn):
        curriculum_id = study["curriculum_subject_id"]
        name = study["curriculum_name"] or study["personal_name"]
        formation_id = study["formation_id"] or study["related_formation_id"]
        required = study["curriculum_required_study_minutes"] if curriculum_id else study["study_required_study_minutes"]
        deadline = (
            study["deadline_date"] or study["curriculum_end_date"] or study["study_target_date"]
            if curriculum_id else study["study_target_date"]
        )
        baseline_effort = study["workload_minutes"] if curriculum_id else None

        if not required or int(required) <= 0:
            issues.append(_issue(
                "missing_effort",
                "O estudo atual não tem esforço pessoal estimado; ele não pode receber uma demanda confiável.",
                curriculum_subject_id=curriculum_id,
                study_subject_id=study["study_subject_id"],
                formation_id=formation_id,
                name=name,
                suggested_values={
                    "required_study_minutes": baseline_effort,
                    "required_study_minutes_source": "workload_minutes" if baseline_effort else "required",
                },
            ))
        if not deadline:
            issues.append(_issue(
                "missing_deadline",
                "O estudo atual não tem prazo. Ele continua visível, mas a urgência não pode ser calculada com precisão.",
                curriculum_subject_id=curriculum_id,
                study_subject_id=study["study_subject_id"],
                formation_id=formation_id,
                name=name,
                suggested_values={
                    "deadline_date": study["curriculum_end_date"] if curriculum_id else None,
                    "deadline_date_source": "curriculum_end_date" if curriculum_id and study["curriculum_end_date"] else "required",
                },
            ))
        if not int(study["topic_count"] or 0):
            issues.append(_issue(
                "missing_topics",
                "O estudo atual ainda não possui tópicos. O planejador pode usar um bloco geral, mas não consegue avançar por conteúdo.",
                curriculum_subject_id=curriculum_id,
                study_subject_id=study["study_subject_id"],
                formation_id=formation_id,
                name=name,
                suggested_values={"open_topic_editor": True},
            ))
        if study["curriculum_archived_at"] or study["formation_archived_at"]:
            issues.append(_issue(
                "current_study_under_archived_parent",
                "O estudo atual está vinculado a uma formação ou disciplina arquivada e deve ser revisado antes de novo planejamento.",
                severity="attention",
                curriculum_subject_id=curriculum_id,
                study_subject_id=study["study_subject_id"],
                formation_id=formation_id,
                name=name,
                suggested_values={"review_parent_archive": True},
            ))
        if curriculum_id and study["academic_status"] not in {"available", "in_progress", "completed"}:
            issues.append(_issue(
                "current_study_with_non_plannable_academic_status",
                "O estudo atual está ligado a uma disciplina cujo estado acadêmico não permite planejamento normal.",
                severity="attention",
                curriculum_subject_id=curriculum_id,
                study_subject_id=study["study_subject_id"],
                formation_id=formation_id,
                name=name,
                suggested_values={"review_academic_status": True},
            ))

    expired_blocks = conn.execute(
        """
        SELECT p.id,p.study_subject_id,p.topic_id,p.scheduled_date,p.source,
               COALESCE(d.name,s.personal_name) name,
               COALESCE(d.formation_id,s.related_formation_id) formation_id,
               s.curriculum_subject_id
        FROM sessoes_planejadas p
        JOIN materias_estudo s ON s.id=p.study_subject_id
        LEFT JOIN disciplinas_grade d ON d.id=s.curriculum_subject_id
        WHERE p.status='planned' AND p.scheduled_date < ?
        ORDER BY p.scheduled_date,p.start_time,p.id
        """,
        (current_day.isoformat(),),
    ).fetchall()
    for row in expired_blocks:
        item = dict(row)
        is_manual = item["source"] == "manual"
        issues.append(_issue(
            "past_planned_block",
            "Há um bloco manual passado que precisa de classificação; ele foi preservado." if is_manual else
            "Há um bloco automático passado ainda marcado como planejado; escolha se deve reagendar ou classificar.",
            severity="attention",
            curriculum_subject_id=item["curriculum_subject_id"],
            study_subject_id=item["study_subject_id"],
            formation_id=item["formation_id"],
            name=item["name"],
            source=item["source"],
            suggested_values={
                "planned_session_id": item["id"],
                "scheduled_date": item["scheduled_date"],
                "requires_explicit_classification": True,
                "manual_block_preserved": is_manual,
            },
        ))

    counts = Counter(issue["kind"] for issue in issues)
    return {
        "generated_for_date": current_day.isoformat(),
        "issues": issues,
        "summary": {
            "total": len(issues),
            "by_kind": dict(sorted(counts.items())),
            "affected_curriculum_subjects": len({issue["curriculum_subject_id"] for issue in issues if issue["curriculum_subject_id"]}),
            "affected_studies": len({issue["study_subject_id"] for issue in issues if issue["study_subject_id"]}),
        },
        "safety": {
            "read_only": True,
            "automatic_deletion": False,
            "manual_blocks_preserved": True,
        },
    }


def _curriculum(conn: sqlite3.Connection, ident: int) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT d.*,f.archived_at formation_archived_at
        FROM disciplinas_grade d JOIN formacoes f ON f.id=d.formation_id
        WHERE d.id=?
        """,
        (ident,),
    ).fetchone()
    if not row:
        raise ValueError("Disciplina curricular não encontrada para reconciliação.")
    return dict(row)


def _study(conn: sqlite3.Connection, ident: int) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM materias_estudo WHERE id=?", (ident,)).fetchone()
    if not row:
        raise ValueError("Estudo não encontrado para reconciliação.")
    return dict(row)


def _active_study_for_curriculum(conn: sqlite3.Connection, curriculum_id: int) -> dict[str, Any] | None:
    placeholders = ",".join("?" for _ in CURRENT_STUDY_STATUSES)
    row = conn.execute(
        f"""
        SELECT * FROM materias_estudo
        WHERE curriculum_subject_id=? AND archived_at IS NULL AND status IN ({placeholders})
        ORDER BY id LIMIT 1
        """,
        (curriculum_id, *CURRENT_STUDY_STATUSES),
    ).fetchone()
    return _row_dict(row)


def _linked_active_canonical_study(conn: sqlite3.Connection, curriculum_id: int) -> dict[str, Any] | None:
    """Evita recriar um estudo próprio quando a disciplina já o compartilha."""
    placeholders = ",".join("?" for _ in CURRENT_STUDY_STATUSES)
    row = conn.execute(
        f"""
        SELECT s.*
        FROM curriculum_study_links l
        JOIN materias_estudo s ON s.id=l.canonical_study_id
        WHERE l.curriculum_subject_id=? AND s.archived_at IS NULL
          AND s.status IN ({placeholders})
        ORDER BY s.id LIMIT 1
        """,
        (curriculum_id, *CURRENT_STUDY_STATUSES),
    ).fetchone()
    return _row_dict(row)


def _timeline_event(conn: sqlite3.Connection, curriculum_id: int, details: str) -> None:
    # A tabela existe desde a migration 0007; o evento torna a intervenção
    # rastreável sem depender de um novo esquema só para auditoria.
    conn.execute(
        """
        INSERT INTO curriculum_timeline_events(curriculum_subject_id,event_type,title,details)
        VALUES (?, 'schedule_settings', 'Reconciliação segura aplicada', ?)
        """,
        (curriculum_id, details),
    )


def reconcile_studies(
    conn: sqlite3.Connection,
    payload: dict[str, Any] | None,
    today: date | datetime | str | None = None,
) -> dict[str, Any]:
    """Aplica uma correção em lote somente quando o usuário confirmar.

    A função aceita uma lista de itens editáveis. Ela nunca classifica blocos
    passados, nunca cria tópicos genéricos e nunca arquiva/exclui nada. Assim,
    a primeira execução pode ser mostrada como prévia e a segunda, com
    ``confirm=true``, é repetível sem criar estudos curriculares duplicados.
    """
    payload = payload or {}
    entries = payload.get("items", payload.get("repairs", []))
    if not isinstance(entries, list):
        raise ValueError("A reconciliação deve receber uma lista de itens.")
    confirmed = _confirmed(payload.get("confirm"))
    current_day = _today(today)
    preview: list[dict[str, Any]] = []
    created_study_ids: list[int] = []
    started_curriculum_ids: list[int] = []
    updated_curriculum_ids: list[int] = []
    updated_study_ids: list[int] = []

    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("Cada item de reconciliação deve ser um objeto.")
        curriculum_id = entry.get("curriculum_subject_id")
        study_id = entry.get("study_subject_id")
        try:
            curriculum_id = int(curriculum_id) if curriculum_id not in (None, "") else None
            study_id = int(study_id) if study_id not in (None, "") else None
        except (TypeError, ValueError) as error:
            raise ValueError("Os identificadores da reconciliação são inválidos.") from error
        if curriculum_id is None and study_id is None:
            raise ValueError("Informe uma disciplina curricular ou um estudo para reconciliar.")

        curriculum = _curriculum(conn, curriculum_id) if curriculum_id else None
        study = _study(conn, study_id) if study_id else None
        if study and curriculum and study.get("curriculum_subject_id") not in (None, curriculum_id):
            raise ValueError("O estudo não pertence à disciplina curricular informada.")
        if study and curriculum is None and study.get("curriculum_subject_id"):
            curriculum = _curriculum(conn, int(study["curriculum_subject_id"]))
            curriculum_id = int(curriculum["id"])

        create_current = _confirmed(entry.get("create_current_study"))
        effort = _safe_positive_minutes(entry.get("required_study_minutes")) if "required_study_minutes" in entry else None
        deadline = _safe_date(entry.get("deadline_date"), "O prazo") if "deadline_date" in entry else None
        start_date = _safe_date(entry.get("start_date"), "A data de início") if "start_date" in entry else None
        changes: list[str] = []

        if create_current:
            if not curriculum:
                raise ValueError("Só disciplinas curriculares podem criar um estudo atual nesta reconciliação.")
            if curriculum["archived_at"] or curriculum["formation_archived_at"]:
                raise ValueError("Restaure a disciplina e a formação antes de criar o estudo atual.")
            if curriculum["academic_status"] != "in_progress":
                raise ValueError("A disciplina precisa estar em andamento antes de criar o estudo atual.")
            existing = _active_study_for_curriculum(conn, int(curriculum["id"]))
            linked_canonical = None if existing else _linked_active_canonical_study(conn, int(curriculum["id"]))
            if existing:
                study = existing
                study_id = int(existing["id"])
                changes.append("estudo atual já existente, preservado")
            elif linked_canonical:
                study = linked_canonical
                study_id = int(linked_canonical["id"])
                changes.append("vínculo com estudo canônico ativo preservado; nenhum estudo duplicado foi criado")
            else:
                planned_start = start_date or curriculum.get("start_date") or current_day.isoformat()
                if confirmed:
                    # A reconciliação não replica o fluxo de negócio: usa a
                    # mesma operação transacional da tela "Iniciar disciplina"
                    # para criar perfil provisório, datas e estudo atual em um
                    # único savepoint.
                    from services import core

                    start_values: dict[str, Any] = {
                        "start_date": planned_start,
                        "effort_mode": "manual" if effort is not None else "automatic",
                    }
                    if effort is not None:
                        start_values["required_study_minutes"] = effort
                    if deadline is not None:
                        start_values["deadline_date"] = deadline
                    started = core.start_curriculum_study(conn, int(curriculum["id"]), start_values)
                    study = dict(started["study"])
                    curriculum = dict(started["curriculum"])
                    study_id = int(study["id"])
                    started_curriculum_ids.append(int(curriculum["id"]))
                    if started["created"]:
                        created_study_ids.append(study_id)
                changes.append("criar estudo atual e perfil de planejamento pela operação oficial")

        if effort is not None:
            if curriculum:
                changes.append(f"definir esforço curricular para {effort} min")
                if confirmed and curriculum.get("required_study_minutes") != effort:
                    conn.execute(
                        """
                        UPDATE disciplinas_grade
                        SET required_study_minutes=?,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')
                        WHERE id=?
                        """,
                        (effort, curriculum["id"]),
                    )
                    updated_curriculum_ids.append(int(curriculum["id"]))
            elif study:
                changes.append(f"definir esforço do estudo para {effort} min")
                if confirmed and study.get("required_study_minutes") != effort:
                    conn.execute(
                        """
                        UPDATE materias_estudo
                        SET required_study_minutes=?,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')
                        WHERE id=?
                        """,
                        (effort, study["id"]),
                    )
                    updated_study_ids.append(int(study["id"]))

        if deadline is not None:
            if curriculum:
                changes.append(f"definir prazo curricular para {deadline}")
                if confirmed and curriculum.get("deadline_date") != deadline:
                    conn.execute(
                        """
                        UPDATE disciplinas_grade
                        SET deadline_date=?,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')
                        WHERE id=?
                        """,
                        (deadline, curriculum["id"]),
                    )
                    updated_curriculum_ids.append(int(curriculum["id"]))
            elif study:
                changes.append(f"definir prazo do estudo para {deadline}")
                if confirmed and study.get("target_date") != deadline:
                    conn.execute(
                        """
                        UPDATE materias_estudo
                        SET target_date=?,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')
                        WHERE id=?
                        """,
                        (deadline, study["id"]),
                    )
                    updated_study_ids.append(int(study["id"]))

        if start_date is not None and study and not create_current:
            changes.append(f"definir início do estudo para {start_date}")
            if confirmed and study.get("start_date") != start_date:
                conn.execute(
                    """
                    UPDATE materias_estudo
                    SET start_date=?,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')
                    WHERE id=?
                    """,
                    (start_date, study["id"]),
                )
                updated_study_ids.append(int(study["id"]))

        if not changes:
            raise ValueError("Informe ao menos uma correção explícita para cada item.")
        preview.append({
            "curriculum_subject_id": curriculum_id,
            "study_subject_id": study_id,
            "changes": changes,
        })

    if confirmed:
        for curriculum_id in sorted(set(updated_curriculum_ids)):
            _timeline_event(conn, curriculum_id, "Esforço e/ou prazo confirmados pela reconciliação de estudos legados.")

    return {
        "applied": confirmed,
        "preview": preview,
        "created_study_ids": created_study_ids,
        "started_curriculum_ids": started_curriculum_ids,
        "updated_curriculum_ids": sorted(set(updated_curriculum_ids)),
        "updated_study_ids": sorted(set(updated_study_ids)),
        "diagnosis": diagnose_studies(conn, current_day),
        "safety": {
            "automatic_deletion": False,
            "manual_blocks_preserved": True,
            "past_blocks_require_explicit_classification": True,
        },
    }
