"""Vínculos opt-in para o mesmo estudo em formações diferentes.

O módulo deliberadamente não tenta "adivinhar" equivalências: a semelhança
serve apenas para listar candidatas. A decisão e qualquer fusão de histórico
dependem de confirmação explícita da pessoa usuária.
"""
from __future__ import annotations

import json
import re
import unicodedata


class CanonicalLinkError(ValueError):
    def __init__(self, message: str, *, code: str = "canonical_link_error", status: int = 400, details=None):
        super().__init__(message)
        self.code = code
        self.status = status
        self.details = details


def _now_sql():
    return "strftime('%Y-%m-%dT%H:%M:%fZ','now')"


def _confirmed(value) -> bool:
    return value is True or str(value).strip().casefold() in {"1", "true", "yes", "sim", "confirm", "confirmed"}


def _normal(value) -> str:
    plain = unicodedata.normalize("NFKD", str(value or ""))
    plain = "".join(char for char in plain if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", "", plain.casefold())


def _subject(conn, ident: int):
    row = conn.execute(
        """
        SELECT d.*,f.name formation_name,f.institution formation_institution,f.archived_at formation_archived_at
        FROM disciplinas_grade d JOIN formacoes f ON f.id=d.formation_id
        WHERE d.id=?
        """,
        (ident,),
    ).fetchone()
    if not row:
        raise CanonicalLinkError("Disciplina curricular não encontrada.", code="curriculum_not_found", status=404)
    return dict(row)


def _study(conn, ident: int):
    row = conn.execute("SELECT * FROM materias_estudo WHERE id=?", (ident,)).fetchone()
    if not row:
        raise CanonicalLinkError("Estudo canônico não encontrado.", code="canonical_study_not_found", status=404)
    return dict(row)


def _study_counts(conn, study_id: int) -> dict:
    return {
        "topics": int(conn.execute("SELECT COUNT(*) FROM topicos WHERE study_subject_id=? AND archived_at IS NULL", (study_id,)).fetchone()[0]),
        "sessions": int(conn.execute("SELECT COUNT(*) FROM sessoes_estudo WHERE study_subject_id=?", (study_id,)).fetchone()[0]),
        "planned_blocks": int(conn.execute("SELECT COUNT(*) FROM sessoes_planejadas WHERE study_subject_id=? AND status='planned'", (study_id,)).fetchone()[0]),
        "notes": int(conn.execute("SELECT COUNT(*) FROM anotacoes_estudo WHERE study_subject_id=?", (study_id,)).fetchone()[0]),
        "evaluations": int(conn.execute("SELECT COUNT(*) FROM avaliacoes WHERE study_subject_id=?", (study_id,)).fetchone()[0]),
    }


def _active_studies_for_subject(conn, curriculum_id: int):
    return [dict(row) for row in conn.execute(
        """
        SELECT * FROM materias_estudo
        WHERE curriculum_subject_id=? AND archived_at IS NULL AND status IN ('active','paused')
        ORDER BY id
        """,
        (curriculum_id,),
    ).fetchall()]


def linked_curriculum_subjects(conn, study_id: int) -> list[dict]:
    """Retorna a disciplina primária e todas as ocorrências vinculadas."""
    study = _study(conn, study_id)
    params = [study_id]
    primary_id = study.get("curriculum_subject_id")
    condition = "l.canonical_study_id=?"
    if primary_id:
        condition = "(" + condition + " OR d.id=?)"
        params.append(primary_id)
    rows = conn.execute(
        """
        SELECT d.id,d.formation_id,d.name,d.code,d.academic_status,d.start_date,d.end_date,d.deadline_date,
               d.workload_minutes,d.required_study_minutes,d.archived_at,
               f.name formation_name,f.archived_at formation_archived_at,
               l.canonical_study_id,l.link_note,l.linked_at,
               CASE WHEN d.id=? THEN 1 ELSE 0 END is_primary
        FROM disciplinas_grade d
        JOIN formacoes f ON f.id=d.formation_id
        LEFT JOIN curriculum_study_links l ON l.curriculum_subject_id=d.id
        WHERE """ + condition + " ORDER BY is_primary DESC,d.deadline_date,d.name COLLATE NOCASE",
        [primary_id, *params],
    ).fetchall()
    return [dict(row) for row in rows]


def planning_contexts(conn, study_ids) -> dict[int, dict]:
    """Dados compartilhados que influenciam uma única demanda canônica.

    O esforço não é somado entre ocorrências. O prazo aplicável, porém, é o
    mais próximo dentre as formações que ainda permitem aquele estudo, e uma
    avaliação de uma ocorrência vinculada também é relevante para a prioridade
    do estudo compartilhado.
    """
    identifiers = [int(value) for value in study_ids if value not in (None, "")]
    if not identifiers:
        return {}
    marks = ",".join("?" for _ in identifiers)
    rows = conn.execute(
        f"""
        WITH subjects AS (
            SELECT s.id study_subject_id,d.id curriculum_subject_id,d.formation_id,d.name,
                   d.academic_status,d.deadline_date,d.end_date,d.archived_at,
                   f.archived_at formation_archived_at,f.name formation_name
            FROM materias_estudo s
            JOIN disciplinas_grade d ON d.id=s.curriculum_subject_id
            JOIN formacoes f ON f.id=d.formation_id
            WHERE s.id IN ({marks})
            UNION ALL
            SELECT l.canonical_study_id,d.id,d.formation_id,d.name,
                   d.academic_status,d.deadline_date,d.end_date,d.archived_at,
                   f.archived_at,f.name
            FROM curriculum_study_links l
            JOIN disciplinas_grade d ON d.id=l.curriculum_subject_id
            JOIN formacoes f ON f.id=d.formation_id
            WHERE l.canonical_study_id IN ({marks})
        )
        SELECT * FROM subjects
        ORDER BY study_subject_id,curriculum_subject_id
        """,
        [*identifiers, *identifiers],
    ).fetchall()
    result: dict[int, dict] = {
        study_id: {"linked_subjects": [], "active_deadlines": [], "formation_names": [], "has_upcoming_evaluation": False}
        for study_id in identifiers
    }
    for raw in rows:
        row = dict(raw)
        state = row["academic_status"]
        active = not row["archived_at"] and not row["formation_archived_at"] and state in {"available", "in_progress"}
        entry = {**row, "planning_active": active}
        context = result.setdefault(int(row["study_subject_id"]), {"linked_subjects": [], "active_deadlines": [], "formation_names": [], "has_upcoming_evaluation": False})
        context["linked_subjects"].append(entry)
        if row["formation_name"] not in context["formation_names"]:
            context["formation_names"].append(row["formation_name"])
        if active:
            deadline = row.get("deadline_date") or row.get("end_date")
            if deadline:
                context["active_deadlines"].append(deadline)
    for study_id, context in result.items():
        context["closest_active_deadline"] = min(context["active_deadlines"]) if context["active_deadlines"] else None
        curriculum_ids = [item["curriculum_subject_id"] for item in context["linked_subjects"]]
        if curriculum_ids:
            marks = ",".join("?" for _ in curriculum_ids)
            context["has_upcoming_evaluation"] = bool(conn.execute(
                f"""
                SELECT 1 FROM avaliacoes
                WHERE curriculum_subject_id IN ({marks})
                  AND status NOT IN ('cancelled','corrected')
                LIMIT 1
                """,
                curriculum_ids,
            ).fetchone())
    return result


def has_active_shared_subject_elsewhere(conn, study_id: int, excluded_formation_id: int) -> bool:
    """Indica se arquivar uma formação não deve arquivar o estudo canônico."""
    row = conn.execute(
        """
        SELECT 1
        FROM curriculum_study_links l
        JOIN disciplinas_grade d ON d.id=l.curriculum_subject_id
        JOIN formacoes f ON f.id=d.formation_id
        WHERE l.canonical_study_id=? AND d.formation_id<>?
          AND d.archived_at IS NULL AND f.archived_at IS NULL
          AND d.academic_status IN ('available','in_progress')
        LIMIT 1
        """,
        (study_id, excluded_formation_id),
    ).fetchone()
    return bool(row)


def canonical_study_for_subject(conn, curriculum_id: int) -> dict | None:
    """Resolve o estudo compartilhado sem criar registros implícitos."""
    link = conn.execute(
        "SELECT canonical_study_id,link_note,linked_at FROM curriculum_study_links WHERE curriculum_subject_id=?",
        (curriculum_id,),
    ).fetchone()
    if link:
        study = _study(conn, int(link["canonical_study_id"]))
        return {"study": study, "kind": "linked", "link_note": link["link_note"], "linked_at": link["linked_at"]}
    current = conn.execute(
        """
        SELECT * FROM materias_estudo
        WHERE curriculum_subject_id=? AND archived_at IS NULL AND status IN ('active','paused')
        ORDER BY id LIMIT 1
        """,
        (curriculum_id,),
    ).fetchone()
    if current:
        return {"study": dict(current), "kind": "own"}
    return None


def _candidate_score(source: dict, candidate: dict) -> tuple[int, list[str]]:
    score, evidence = 0, []
    if source.get("code") and candidate.get("code") and _normal(source["code"]) == _normal(candidate["code"]):
        score += 100; evidence.append("mesmo código")
    if _normal(source.get("name")) == _normal(candidate.get("name")):
        score += 70; evidence.append("mesmo nome normalizado")
    if source.get("workload_minutes") and candidate.get("workload_minutes") and int(source["workload_minutes"]) == int(candidate["workload_minutes"]):
        score += 12; evidence.append("mesma carga curricular")
    if source.get("formation_institution") and candidate.get("formation_institution") and _normal(source["formation_institution"]) == _normal(candidate["formation_institution"]):
        score += 5; evidence.append("mesma instituição")
    if source.get("notes") and candidate.get("notes") and _normal(source["notes"]) == _normal(candidate["notes"]):
        score += 8; evidence.append("mesmas observações/ementa")
    return score, evidence


def equivalence_candidates(conn, curriculum_id: int) -> dict:
    source = _subject(conn, curriculum_id)
    rows = conn.execute(
        """
        SELECT d.*,f.name formation_name,f.institution formation_institution,f.archived_at formation_archived_at,
               l.canonical_study_id
        FROM disciplinas_grade d
        JOIN formacoes f ON f.id=d.formation_id
        LEFT JOIN curriculum_study_links l ON l.curriculum_subject_id=d.id
        WHERE d.id<>? AND d.item_type='subject' AND d.archived_at IS NULL AND f.archived_at IS NULL
        ORDER BY d.name COLLATE NOCASE,d.id
        """,
        (curriculum_id,),
    ).fetchall()
    values = []
    for row in rows:
        candidate = dict(row)
        score, evidence = _candidate_score(source, candidate)
        if score < 70:
            continue
        current = canonical_study_for_subject(conn, candidate["id"])
        canonical_id = current["study"]["id"] if current else candidate.get("canonical_study_id")
        values.append({
            "curriculum_subject_id": candidate["id"], "name": candidate["name"], "code": candidate.get("code"),
            "formation_id": candidate["formation_id"], "formation_name": candidate["formation_name"],
            "academic_status": candidate["academic_status"], "deadline_date": candidate.get("deadline_date"),
            "workload_minutes": candidate.get("workload_minutes"), "score": score, "evidence": evidence,
            "canonical_study_id": canonical_id,
            "study": ({"id": current["study"]["id"], "status": current["study"]["status"], "counts": _study_counts(conn, current["study"]["id"])} if current else None),
            "actions": ["compare", "link", "keep_separate"],
        })
    values.sort(key=lambda item: (-item["score"], item["name"].casefold(), item["curriculum_subject_id"]))
    return {"source": source, "candidates": values, "automatic_linking": False}


def link_preview(conn, curriculum_id: int, canonical_study_id: int) -> dict:
    source = _subject(conn, curriculum_id)
    canonical = _study(conn, canonical_study_id)
    if source["archived_at"] or source["formation_archived_at"]:
        raise CanonicalLinkError("Restaure a disciplina e a formação antes de vinculá-las.", code="archived_source", status=409)
    if canonical["origin"] != "curriculum" or not canonical.get("curriculum_subject_id"):
        raise CanonicalLinkError("O estudo canônico precisa ser um estudo curricular existente.", code="canonical_must_be_curriculum", status=409)
    if canonical["status"] not in {"active", "paused"}:
        # Um vínculo aponta para o objeto operacional que será reutilizado por
        # Planejamento e Foco. Ligar uma disciplina nova a um estudo concluído
        # ou arquivado faria o botão "Iniciar" parecer funcionar, mas sem uma
        # demanda utilizável. A pessoa pode reabrir o estudo primeiro, ou optar
        # explicitamente por manter as duas ocorrências separadas.
        raise CanonicalLinkError(
            "O estudo canônico precisa estar ativo ou pausado para ser compartilhado.",
            code="canonical_study_not_current",
            status=409,
            details={"study_status": canonical["status"]},
        )
    if int(canonical["curriculum_subject_id"]) == int(curriculum_id):
        raise CanonicalLinkError("A disciplina já é a origem deste estudo canônico.", code="canonical_is_same_subject", status=409)
    canonical_subject = _subject(conn, int(canonical["curriculum_subject_id"]))
    if canonical["archived_at"] or canonical_subject["archived_at"] or canonical_subject["formation_archived_at"]:
        raise CanonicalLinkError("Restaure o estudo canônico e sua formação antes do vínculo.", code="archived_canonical", status=409)
    # A prévia é uma decisão de usuário, não apenas um identificador técnico:
    # ela precisa revelar o que será reaproveitado antes da confirmação.
    canonical_counts = _study_counts(conn, canonical_study_id)
    canonical = {
        **canonical,
        "name": canonical_subject["name"],
        "formation_name": canonical_subject["formation_name"],
        "topic_count": canonical_counts["topics"],
        "session_count": canonical_counts["sessions"],
        "planned_block_count": canonical_counts["planned_blocks"],
        "note_count": canonical_counts["notes"],
        "evaluation_count": canonical_counts["evaluations"],
    }
    current_links = _active_studies_for_subject(conn, curriculum_id)
    active_focus = []
    if current_links:
        marks = ",".join("?" for _ in current_links)
        active_focus = [dict(row) for row in conn.execute(
            f"SELECT id,study_subject_id,status FROM sessoes_foco WHERE study_subject_id IN ({marks}) AND status IN ('running','paused','recovery_required')",
            [row["id"] for row in current_links],
        ).fetchall()]
    existing = conn.execute("SELECT * FROM curriculum_study_links WHERE curriculum_subject_id=?", (curriculum_id,)).fetchone()
    return {
        "source": source,
        "canonical_study": canonical,
        "canonical_subject": canonical_subject,
        "existing_link": dict(existing) if existing else None,
        "source_current_studies": [{**row, "counts": _study_counts(conn, row["id"])} for row in current_links],
        "active_focus": active_focus,
        "requires_merge": bool(current_links and any(row["id"] != canonical_study_id for row in current_links)),
        "manual_blocks_preserved": True,
        "academic_states_remain_independent": True,
    }


def _merge_study(conn, source_study_id: int, canonical_study_id: int) -> dict:
    """Move o histórico de um estudo duplicado sem excluir sua linha original."""
    if source_study_id == canonical_study_id:
        return {"moved": {}, "cancelled_automatic_duplicates": []}
    running = conn.execute(
        "SELECT id FROM sessoes_foco WHERE study_subject_id=? AND status IN ('running','paused','recovery_required')",
        (source_study_id,),
    ).fetchone()
    if running:
        raise CanonicalLinkError(
            "Encerre ou recupere a sessão de foco ativa antes de unir os estudos.",
            code="canonical_merge_focus_active", status=409, details={"focus_session_id": running[0]},
        )

    duplicate_rows = conn.execute(
        """
        SELECT p.id FROM sessoes_planejadas p
        WHERE p.study_subject_id=? AND p.status='planned' AND p.source='automatic'
          AND EXISTS (
            SELECT 1 FROM sessoes_planejadas q
            WHERE q.study_subject_id=? AND q.status='planned'
              AND q.scheduled_date=p.scheduled_date
              AND COALESCE(q.start_time,'')=COALESCE(p.start_time,'')
              AND q.planned_duration_minutes=p.planned_duration_minutes
          )
        """,
        (source_study_id, canonical_study_id),
    ).fetchall()
    duplicate_ids = [int(row[0]) for row in duplicate_rows]
    if duplicate_ids:
        marks = ",".join("?" for _ in duplicate_ids)
        conn.execute(
            f"UPDATE sessoes_planejadas SET status='cancelled',selection_reason='cancelado: duplicidade após vínculo canônico',updated_at={_now_sql()} WHERE id IN ({marks})",
            duplicate_ids,
        )

    tables = ("grupos_topicos", "topicos", "sessoes_estudo", "avaliacoes", "anotacoes_estudo", "sessoes_foco")
    moved = {}
    for table in tables:
        cursor = conn.execute(
            f"UPDATE {table} SET study_subject_id=?,updated_at={_now_sql()} WHERE study_subject_id=?",
            (canonical_study_id, source_study_id),
        )
        moved[table] = int(cursor.rowcount)
    cursor = conn.execute(
        "UPDATE sessoes_planejadas SET study_subject_id=?,updated_at=" + _now_sql() + " WHERE study_subject_id=? AND status='planned'",
        (canonical_study_id, source_study_id),
    )
    moved["planned_active"] = int(cursor.rowcount)
    # Os blocos já concluídos/cancelados continuam apontando para o estudo
    # histórico, para tornar a trilha anterior auditável sem dupla demanda.
    conn.execute(
        """
        UPDATE materias_estudo
        SET status='archived',archived_at=COALESCE(archived_at, date('now')),
            -- A constraint legada mantém os motivos de arquivamento fechados.
            -- A auditoria de vínculo abaixo registra o motivo específico sem
            -- reescrever uma migration já aplicada.
            archive_reason='removed_current',status_before_archive=status,updated_at=""" + _now_sql() + " WHERE id=?",
        (source_study_id,),
    )
    return {"moved": moved, "cancelled_automatic_duplicates": duplicate_ids}


def link_curriculum_subject(conn, curriculum_id: int, canonical_study_id: int, values=None) -> dict:
    values = values or {}
    preview = link_preview(conn, curriculum_id, canonical_study_id)
    if not _confirmed(values.get("confirm")):
        return {"applied": False, "preview": preview, "requires_confirmation": True}
    if preview["active_focus"]:
        raise CanonicalLinkError("Há uma sessão de foco ativa no estudo que seria unido.", code="canonical_merge_focus_active", status=409, details=preview)
    existing = preview["existing_link"]
    if existing and int(existing["canonical_study_id"]) != int(canonical_study_id) and not _confirmed(values.get("replace_existing_link")):
        raise CanonicalLinkError("Esta disciplina já aponta para outro estudo canônico. Confirme a substituição para trocar o vínculo.", code="canonical_link_exists", status=409, details=preview)
    sources = [row for row in preview["source_current_studies"] if int(row["id"]) != int(canonical_study_id)]
    if sources and not _confirmed(values.get("merge_existing_study")):
        raise CanonicalLinkError("A disciplina já possui estudo atual. Revise a prévia e confirme a união para preservar e centralizar o histórico.", code="canonical_merge_required", status=409, details=preview)

    merged = []
    for source in sources:
        merged.append({"study_subject_id": source["id"], **_merge_study(conn, int(source["id"]), int(canonical_study_id))})
    # Conteúdos e avaliações criados diretamente na grade ainda não possuem
    # um estudo atual. Ao vincular, eles passam a pertencer ao canônico sem
    # perder a referência curricular da formação de origem.
    attached_direct_content = conn.execute(
        "UPDATE topicos SET study_subject_id=?,updated_at=" + _now_sql() + " WHERE curriculum_subject_id=? AND study_subject_id IS NULL",
        (canonical_study_id, curriculum_id),
    ).rowcount
    attached_direct_evaluations = conn.execute(
        "UPDATE avaliacoes SET study_subject_id=?,updated_at=" + _now_sql() + " WHERE curriculum_subject_id=? AND study_subject_id IS NULL",
        (canonical_study_id, curriculum_id),
    ).rowcount
    conn.execute(
        """
        INSERT INTO curriculum_study_links(curriculum_subject_id,canonical_study_id,link_note)
        VALUES (?,?,?)
        ON CONFLICT(curriculum_subject_id) DO UPDATE SET
          canonical_study_id=excluded.canonical_study_id,link_note=excluded.link_note,updated_at=""" + _now_sql(),
        (curriculum_id, canonical_study_id, values.get("link_note")),
    )
    action = "merged_existing_study" if merged else "linked"
    conn.execute(
        """
        INSERT INTO curriculum_study_link_audit(action,curriculum_subject_id,canonical_study_id,previous_study_id,details)
        VALUES (?,?,?,?,?)
        """,
        (action, curriculum_id, canonical_study_id, sources[0]["id"] if sources else None, json.dumps({"merged": merged, "attached_direct_content": attached_direct_content, "attached_direct_evaluations": attached_direct_evaluations, "note": values.get("link_note")}, ensure_ascii=False)),
    )
    return {
        "applied": True, "curriculum_subject_id": curriculum_id, "canonical_study_id": canonical_study_id,
        "merged": merged, "attached_direct_content": int(attached_direct_content),
        "attached_direct_evaluations": int(attached_direct_evaluations),
        "linked_curricula": linked_curriculum_subjects(conn, canonical_study_id),
        "academic_states_remain_independent": True,
    }


def unlink_curriculum_subject(conn, curriculum_id: int, values=None) -> dict:
    values = values or {}
    row = conn.execute("SELECT * FROM curriculum_study_links WHERE curriculum_subject_id=?", (curriculum_id,)).fetchone()
    if not row:
        raise CanonicalLinkError("Esta disciplina não possui vínculo canônico para desfazer.", code="canonical_link_not_found", status=404)
    link = dict(row)
    if not _confirmed(values.get("confirm")):
        return {"applied": False, "link": link, "requires_confirmation": True, "preserved_shared_data": True}
    conn.execute("DELETE FROM curriculum_study_links WHERE curriculum_subject_id=?", (curriculum_id,))
    conn.execute(
        """
        INSERT INTO curriculum_study_link_audit(action,curriculum_subject_id,canonical_study_id,details)
        VALUES ('unlinked',?,?,?)
        """,
        (curriculum_id, link["canonical_study_id"], json.dumps({"note": values.get("note"), "shared_data_preserved": True}, ensure_ascii=False)),
    )
    return {"applied": True, "unlinked": link, "preserved_shared_data": True}


def link_audit(conn, curriculum_id: int) -> list[dict]:
    return [dict(row) for row in conn.execute(
        "SELECT * FROM curriculum_study_link_audit WHERE curriculum_subject_id=? ORDER BY id DESC",
        (curriculum_id,),
    ).fetchall()]
