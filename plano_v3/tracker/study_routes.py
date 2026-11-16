"""Roteiros por disciplina, sempre vinculados a tópicos canônicos."""

import difflib
import hashlib
import json
import re

from . import catalog, topics
from .domain import DomainError, clean, get, key, now

MAX_JSON_CHARS = 1_000_000
MAX_MODULES = 30
MAX_TOPICS = 300
KEY_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,59}$")
FORBIDDEN_FIELDS = {"status", "completed", "needs_review", "hours", "minutes_studied", "sessions"}


def _expect_object(value, label):
    if not isinstance(value, dict):
        raise DomainError(f"{label}: esperado um objeto JSON.")
    forbidden = FORBIDDEN_FIELDS.intersection(value)
    if forbidden:
        raise DomainError(f"O JSON não pode definir estado ou histórico ({', '.join(sorted(forbidden))}).")


def _validate(conn, subject_id, document):
    if isinstance(document, str):
        if len(document) > MAX_JSON_CHARS:
            raise DomainError("O JSON excede o limite de 1 MB.")
        try:
            document = json.loads(document)
        except (TypeError, json.JSONDecodeError):
            raise DomainError("Não foi possível ler o JSON. Confira se a resposta está completa e válida.")
    _expect_object(document, "Documento")
    if len(json.dumps(document, ensure_ascii=False)) > MAX_JSON_CHARS:
        raise DomainError("O JSON excede o limite de 1 MB.")
    if document.get("schema_version") != 1 or document.get("kind") != "subject_study_route":
        raise DomainError("Use schema_version 1 e kind subject_study_route.")
    route = document.get("route")
    _expect_object(route, "route")
    title = clean(route.get("title"), "Título do roteiro", 200, required=True)
    description = clean(route.get("description"), "Descrição do roteiro", 2000)
    modules = route.get("modules")
    if not isinstance(modules, list) or not 1 <= len(modules) <= MAX_MODULES:
        raise DomainError(f"O roteiro deve conter de 1 a {MAX_MODULES} módulos.")
    module_keys, item_keys, normalized_titles = set(), set(), set()
    cleaned_modules, count = [], 0
    for mi, module in enumerate(modules):
        _expect_object(module, f"Módulo {mi + 1}")
        mkey = module.get("key")
        if not isinstance(mkey, str) or not KEY_RE.fullmatch(mkey) or mkey in module_keys:
            raise DomainError(f"A chave do módulo {mi + 1} é inválida ou repetida.")
        module_keys.add(mkey)
        mtitle = clean(module.get("title"), f"Título do módulo {mi + 1}", 200, required=True)
        mdescription = clean(module.get("description"), f"Descrição do módulo {mi + 1}", 2000)
        items = module.get("topics")
        if not isinstance(items, list) or not items:
            raise DomainError(f"O módulo {mtitle} precisa ter pelo menos um tópico.")
        out_items = []
        for ti, item in enumerate(items):
            count += 1
            if count > MAX_TOPICS:
                raise DomainError(f"O roteiro pode conter no máximo {MAX_TOPICS} tópicos.")
            _expect_object(item, f"Tópico {ti + 1} do módulo {mtitle}")
            ikey = item.get("key")
            if not isinstance(ikey, str) or not KEY_RE.fullmatch(ikey) or ikey in item_keys:
                raise DomainError(f"A chave do tópico {ikey or ti + 1} é inválida ou repetida.")
            item_keys.add(ikey)
            ititle = clean(item.get("title"), "Título do tópico", 200, required=True)
            ititle_key = key(ititle)
            if not ititle_key:
                raise DomainError("O título de cada tópico deve conter letras ou números.")
            duplicate = ititle_key in normalized_titles
            normalized_titles.add(ititle_key)
            id_value = item.get("existing_topic_id")
            if id_value is not None and (isinstance(id_value, bool) or not isinstance(id_value, int) or id_value <= 0):
                raise DomainError(f"ID inválido no tópico {ititle}.")
            minutes = item.get("estimated_minutes")
            if minutes is not None and (isinstance(minutes, bool) or not isinstance(minutes, int) or not 1 <= minutes <= 600000):
                raise DomainError(f"Estimativa inválida no tópico {ititle}; use minutos inteiros de 1 a 600.000.")
            out_items.append({
                "key": ikey,
                "title": ititle,
                "description": clean(item.get("description"), "Descrição do tópico", 2000),
                "estimated_minutes": minutes,
                "source_reference": clean(item.get("source_reference"), "Referência de origem", 500),
                "existing_topic_id": id_value,
                "internal_duplicate": duplicate,
            })
        cleaned_modules.append({"key": mkey, "title": mtitle, "description": mdescription, "topics": out_items})
    get_topics = {row["id"]: row for row in topics.listing(conn, subject_id, archived=True)}
    for module in cleaned_modules:
        for item in module["topics"]:
            ident = item["existing_topic_id"]
            if ident is not None:
                existing = get_topics.get(ident)
                if not existing:
                    raise DomainError(f"O tópico indicado em “{item['title']}” não pertence a esta disciplina.")
                item["resolved_topic_id"] = ident
                item["match"] = "explicit_id"
            else:
                exact = next((t for t in get_topics.values() if t["name_key"] == key(item["title"])), None)
                if exact:
                    item["resolved_topic_id"] = exact["id"]
                    item["match"] = "exact"
                else:
                    close = difflib.get_close_matches(key(item["title"]), [t["name_key"] for t in get_topics.values()], n=3, cutoff=0.78)
                    candidates = [t["id"] for t in get_topics.values() if t["name_key"] in close]
                    item["suggested_topic_ids"] = candidates
                    item["match"] = "choice_required" if candidates else "new"
    return {"schema_version": 1, "kind": "subject_study_route", "route": {"title": title, "description": description, "modules": cleaned_modules}}


def _subject(conn, subject_id):
    row = conn.execute("""SELECT s.*,c.name course_name,c.institution,c.archived_at course_archived_at
        FROM subjects s JOIN courses c ON c.id=s.course_id WHERE s.id=?""", (subject_id,)).fetchone()
    if row is None:
        raise DomainError("Disciplina não encontrada.", 404)
    subject = dict(row)
    catalog.active_course(conn, subject["course_id"])
    if subject["archived_at"]:
        raise DomainError("Restaure a disciplina antes de gerenciar seu roteiro.", 409)
    return subject


def get_for_subject(conn, subject_id):
    subject = _subject(conn, subject_id)
    route_row = conn.execute("SELECT * FROM study_routes WHERE subject_id=?", (subject_id,)).fetchone()
    if not route_row:
        all_topics = topics.listing(conn, subject_id, archived=True)
        return {"subject": subject, "route": None, "topics": all_topics, "outside_topics": all_topics}
    route = dict(route_row)
    route.pop("content_signature", None)
    modules = []
    for module in conn.execute("SELECT * FROM study_route_modules WHERE route_id=? ORDER BY position", (route["id"],)):
        mod = dict(module)
        mod["topics"] = [dict(r) for r in conn.execute("""SELECT i.item_key,i.description route_description,
            i.estimated_minutes,i.source_reference,i.position,t.id,t.name,t.completed,t.needs_review,t.version,
            COALESCE(x.seconds,0) effective_seconds,COALESCE(x.sessions,0) sessions
            FROM study_route_items i JOIN topics t ON t.id=i.topic_id
            LEFT JOIN (SELECT topic_id,SUM(effective_seconds) seconds,COUNT(*) sessions FROM study_sessions GROUP BY topic_id) x ON x.topic_id=t.id
            WHERE i.module_id=? ORDER BY i.position""", (mod["id"],))]
        modules.append(mod)
    in_route = {item["id"] for module in modules for item in module["topics"]}
    all_topics = topics.listing(conn, subject_id, archived=True)
    outside = [t for t in all_topics if t["id"] not in in_route]
    route["modules"] = modules
    route["topic_count"] = sum(len(m["topics"]) for m in modules)
    route["module_count"] = len(modules)
    return {"subject": subject, "route": route, "topics": all_topics, "outside_topics": outside}


def preview(conn, subject_id, document, decisions=None):
    _subject(conn, subject_id)
    data = _validate(conn, subject_id, document)
    decisions = decisions or {}
    if not isinstance(decisions, dict):
        raise DomainError("As escolhas de vínculo são inválidas.")
    existing = {t["id"]: t for t in topics.listing(conn, subject_id, archived=True)}
    seen_topic_ids = set()
    warnings = []
    for module in data["route"]["modules"]:
        for item in module["topics"]:
            action = decisions.get(item["key"])
            if action is not None:
                if not isinstance(action, dict) or action.get("action") not in ("new", "existing"):
                    raise DomainError(f"Escolha se “{item['title']}” será novo ou vinculado a um tópico existente.")
                if action["action"] == "existing":
                    ident = action.get("topic_id")
                    if isinstance(ident, bool) or not isinstance(ident, int) or ident not in existing:
                        raise DomainError(f"O tópico escolhido para “{item['title']}” não pertence a esta disciplina.")
                    item["resolved_topic_id"] = ident
                    item["match"] = "chosen"
                else:
                    item.pop("resolved_topic_id", None)
                    item["match"] = "new"
            if item["internal_duplicate"]:
                warnings.append({"type": "duplicate_in_json", "key": item["key"], "title": item["title"]})
            ident = item.get("resolved_topic_id")
            if ident is not None:
                if ident in seen_topic_ids:
                    warnings.append({"type": "same_topic_twice", "key": item["key"], "topic_id": ident})
                seen_topic_ids.add(ident)
                item["existing_topic"] = existing[ident]
            elif item["match"] == "choice_required":
                warnings.append({"type": "ambiguous_match", "key": item["key"], "candidates": [existing[i] for i in item["suggested_topic_ids"]]})
    return {"document": data, "warnings": warnings, "has_unresolved_choices": any(
        item["match"] == "choice_required" for module in data["route"]["modules"] for item in module["topics"]
    )}


def _signature(document, decisions):
    if isinstance(document, str):
        document = json.loads(document)
    serialized = json.dumps({"document": document, "decisions": decisions}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def confirm(conn, subject_id, values):
    _subject(conn, subject_id)
    document = values.get("document")
    decisions = values.get("decisions", {})
    operation_key = values.get("operation_key")
    if not isinstance(operation_key, str) or not 8 <= len(operation_key) <= 100:
        raise DomainError("Identificador da importação inválido.")
    prepared = preview(conn, subject_id, document, decisions)
    if prepared["has_unresolved_choices"]:
        raise DomainError("Resolva as correspondências aproximadas antes de confirmar.")
    if any(w["type"] in {"duplicate_in_json", "same_topic_twice"} for w in prepared["warnings"]):
        raise DomainError("Remova ou corrija os tópicos duplicados antes de confirmar.")
    data = prepared["document"]
    signature = _signature(document, decisions)
    receipt = conn.execute("SELECT * FROM study_route_imports WHERE operation_key=?", (operation_key,)).fetchone()
    if receipt:
        if receipt["subject_id"] != subject_id or receipt["request_signature"] != signature:
            raise DomainError("Esta confirmação já foi usada para outro conteúdo. Gere uma nova prévia.", 409)
        result = get_for_subject(conn, subject_id)
        result["idempotent_replay"] = True
        return result
    route_data = data["route"]
    old = conn.execute("SELECT * FROM study_routes WHERE subject_id=?", (subject_id,)).fetchone()
    expected = values.get("expected_version", 0)
    actual = old["version"] if old else 0
    if isinstance(expected, bool) or not isinstance(expected, int) or expected != actual:
        raise DomainError("O roteiro mudou em outra aba. Atualize antes de importar.", 409)
    timestamp = now()
    if old and old["content_signature"] == signature:
        conn.execute("INSERT INTO study_route_imports(operation_key,subject_id,request_signature,route_id,created_at) VALUES (?,?,?,?,?)", (operation_key, subject_id, signature, old["id"], timestamp))
        result = get_for_subject(conn, subject_id)
        result["idempotent_replay"] = False
        result["unchanged"] = True
        return result
    if old:
        conn.execute("UPDATE study_routes SET title=?,description=?,content_signature=?,version=version+1,updated_at=? WHERE id=?", (route_data["title"], route_data["description"], signature, timestamp, old["id"]))
        route_id = old["id"]
        conn.execute("DELETE FROM study_route_modules WHERE route_id=?", (route_id,))
    else:
        route_id = conn.execute("INSERT INTO study_routes(subject_id,title,description,content_signature,created_at,updated_at) VALUES (?,?,?,?,?,?)", (subject_id, route_data["title"], route_data["description"], signature, timestamp, timestamp)).lastrowid
    for mi, module in enumerate(route_data["modules"]):
        module_id = conn.execute("INSERT INTO study_route_modules(route_id,module_key,title,description,position) VALUES (?,?,?,?,?)", (route_id, module["key"], module["title"], module["description"], mi)).lastrowid
        for ti, item in enumerate(module["topics"]):
            topic_id = item.get("resolved_topic_id")
            if topic_id is None:
                topic_id = topics.create(conn, subject_id, item["title"])["id"]
            else:
                canonical = get(conn, "topics", topic_id)
                if canonical["subject_id"] != subject_id:
                    raise DomainError("Um tópico escolhido pertence a outra disciplina.")
            conn.execute("INSERT INTO study_route_items(module_id,topic_id,item_key,description,estimated_minutes,source_reference,position) VALUES (?,?,?,?,?,?,?)", (module_id, topic_id, item["key"], item["description"], item["estimated_minutes"], item["source_reference"], ti))
    conn.execute("INSERT INTO study_route_imports(operation_key,subject_id,request_signature,route_id,created_at) VALUES (?,?,?,?,?)", (operation_key, subject_id, signature, route_id, timestamp))
    result = get_for_subject(conn, subject_id)
    result["idempotent_replay"] = False
    result["unchanged"] = False
    return result
