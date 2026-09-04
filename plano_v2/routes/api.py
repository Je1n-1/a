from datetime import timedelta
from io import BytesIO
import sqlite3
from zipfile import ZIP_DEFLATED, ZipFile

from flask import Blueprint, Response, jsonify, request, send_file

from config import CURRICULUM_TEMPLATE_PATH
from database.connection import connect
from services import core
from services.grade_import import preview, preview_paste


api = Blueprint("api", __name__, url_prefix="/api")


def body(): return request.get_json(silent=True) or request.form.to_dict()
def respond(value, status=200): return jsonify(value), status
def run(operation):
    try:
        with connect() as conn: return respond(operation(conn))
    except core.DomainError as error:
        payload = {"error": str(error), "code": error.code}
        if error.blockers is not None:
            payload["blockers"] = error.blockers
        if error.details is not None:
            payload["details"] = error.details
        return respond(payload, error.status)
    except ValueError as error: return respond({"error":str(error),"code":"validation_error"},400)
    except sqlite3.IntegrityError: return respond({"error":"Não foi possível salvar porque os dados conflitam com um registro existente.","code":"integrity_error"},409)


def download(operation, mimetype, filename):
    try:
        with connect() as conn:
            payload = operation(conn)
        response = Response(payload, mimetype=mimetype)
        response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response
    except core.DomainError as error: return respond({"error":str(error),"code":error.code},error.status)
    except ValueError as error: return respond({"error":str(error),"code":"validation_error"},400)
    except sqlite3.IntegrityError: return respond({"error":"Não foi possível preparar a exportação porque os dados conflitam com um registro existente.","code":"integrity_error"},409)


@api.get("/bootstrap")
def bootstrap():
    def operation(conn):
        today=core._local_now().date(); end=today+timedelta(days=6)
        return {"formations":core.formations(conn),"studies":core.studies(conn),"recommendation":core.recommendation(conn),"reviews":core.reviews(conn),"analytics":core.analytics(conn),"planned":core.planned(conn,today.isoformat(),end.isoformat())}
    return run(operation)


@api.route("/formations",methods=["GET","POST"])
def formation_collection():
    if request.method == "GET":
        state = request.args.get("state")
        if state is None:
            state = "all" if request.args.get("archived") == "1" else "active"
        return run(lambda conn: core.formations(conn, state))
    return run(lambda conn: core.create_formation(conn,body()))
@api.route("/formations/<int:ident>",methods=["PATCH","DELETE"])
def formation_item(ident):
    return run(lambda conn: core.change_formation(conn,ident,body()) if request.method=="PATCH" else core.delete_formation(conn,ident) or {"deleted":True})
@api.post("/formations/<int:ident>/<action>")
def formation_action(ident,action):
    data = body()
    if action == "archive":
        return run(lambda conn: core.archive_formation(conn, ident, data.get("study_policy", "archive_studies")))
    if action == "restore":
        return run(lambda conn: core.restore_formation(conn, ident, data.get("restore_studies")))
    if action == "destroy":
        return run(lambda conn: core.destroy(conn, "formation", ident, data.get("confirmation"), data.get("include_dependencies")))
    return respond({"error":"Ação de formação inválida."},400)
@api.get("/formations/<int:ident>/dependencies")
def formation_dependencies(ident): return run(lambda conn: core.formation_dependencies(conn, ident))


@api.get("/formations/<int:formation_id>/curriculum")
def curriculum(formation_id): return run(lambda conn: core.curriculum(conn,formation_id,request.args.get("archived")=="1"))
@api.get("/formations/<int:formation_id>/curriculum/management")
def curriculum_management(formation_id):
    filters = {key: request.args.get(key) for key in ("q", "period", "academic_status", "review_status", "visibility", "quick", "sort", "item_type") if request.args.get(key) is not None}
    return run(lambda conn: core.curriculum_management(conn, formation_id, filters))
@api.post("/formations/<int:formation_id>/curriculum")
def curriculum_create(formation_id): return run(lambda conn: core.create_curriculum(conn,formation_id,body()))
@api.post("/formations/<int:formation_id>/curriculum/batch/preview")
def curriculum_batch_preview(formation_id): return run(lambda conn: core.curriculum_batch_preview(conn, formation_id, body()))
@api.post("/formations/<int:formation_id>/curriculum/batch")
def curriculum_batch(formation_id): return run(lambda conn: core.curriculum_batch(conn, formation_id, body()))
@api.get("/formations/<int:formation_id>/curriculum/duplicates")
def curriculum_duplicates(formation_id): return run(lambda conn: core.duplicate_candidates(conn, formation_id))
@api.get("/formations/<int:formation_id>/curriculum/structural-candidates")
def curriculum_structural_candidates(formation_id): return run(lambda conn: core.structural_candidates(conn, formation_id))
@api.post("/formations/<int:formation_id>/curriculum/merge")
def curriculum_merge(formation_id):
    data = body()
    return run(lambda conn: core.merge_curriculum(conn, formation_id, data.get("primary_id"), data.get("duplicate_ids"), data.get("preserve"), data.get("confirmation")))
@api.get("/curriculum/template")
def curriculum_template():
    if not CURRICULUM_TEMPLATE_PATH.is_file():
        return respond({"error":"O modelo oficial de grade não está disponível neste momento.","code":"curriculum_template_missing"}, 404)
    return send_file(
        CURRICULUM_TEMPLATE_PATH,
        as_attachment=True,
        download_name="modelo_grade_curricular.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
@api.post("/formations/<int:formation_id>/curriculum/preview")
def curriculum_preview(formation_id):
    def operation(conn):
        core._get(conn,"formacoes",formation_id)
        upload=request.files.get("file")
        if not upload or not upload.filename: raise core.DomainError("Selecione um arquivo.")
        result = preview(upload, upload.filename, request.form.get("sheet") or request.args.get("sheet"))
        return core.curriculum_import_preview(conn, formation_id, result)
    return run(operation)
@api.post("/formations/<int:formation_id>/curriculum/preview/paste")
def curriculum_preview_paste(formation_id):
    data = body()
    return run(lambda conn: core.curriculum_import_preview(conn, formation_id, preview_paste(data.get("text"))))
@api.post("/formations/<int:formation_id>/curriculum/import")
def curriculum_import(formation_id):
    data = body()
    return run(lambda conn: core.import_curriculum(conn, formation_id, data.get("items", []), data.get("confirmed")))
@api.route("/curriculum/<int:ident>",methods=["PATCH","DELETE"])
def curriculum_item(ident): return run(lambda conn: core.update_curriculum(conn,ident,body()) if request.method=="PATCH" else core.delete_curriculum(conn,ident) or {"deleted":True})
@api.get("/curriculum/<int:ident>/dependencies")
def curriculum_dependencies(ident): return run(lambda conn: core.curriculum_dependencies(conn, ident))
@api.get("/curriculum/<int:ident>/history")
def curriculum_history(ident): return run(lambda conn: core.curriculum_status_history(conn, ident))
@api.post("/curriculum/<int:ident>/status")
def curriculum_status(ident): return run(lambda conn: core.change_curriculum_status(conn, ident, body(), "manual", body().get("notes")))
@api.post("/curriculum/<int:ident>/review")
def curriculum_review(ident): return run(lambda conn: core.set_curriculum_review(conn, ident, body()))
@api.post("/curriculum/<int:ident>/<action>")
def curriculum_action(ident,action):
    if action == "archive": return run(lambda conn: core.archive_curriculum(conn,ident))
    if action == "restore": return run(lambda conn: core.archive_curriculum(conn,ident,True))
    if action == "destroy": return run(lambda conn: core.destroy(conn,"curriculum",ident,body().get("confirmation"),body().get("include_dependencies")))
    return respond({"error":"Ação de disciplina inválida."},400)
@api.post("/curriculum/<int:ident>/add-study")
def curriculum_add_study(ident): return run(lambda conn: core.add_curriculum_study(conn,ident,body()))


@api.route("/studies",methods=["GET","POST"])
def study_collection():
    if request.method == "POST": return run(lambda conn: core.create_personal_study(conn,body()))
    visibility = request.args.get("visibility")
    return run(lambda conn: core.studies(
        conn, request.args.get("archived")=="1", request.args.get("week_reference"), visibility,
        request.args.get("formation_id"), request.args.get("q"), request.args.get("review_status"),
    ))
@api.get("/studies/<int:ident>")
def study_detail(ident): return run(lambda conn: core.subject_detail(conn,ident))
@api.route("/studies/<int:ident>",methods=["PATCH","DELETE"])
def study_item(ident): return run(lambda conn: core.update_study(conn,ident,body()) if request.method=="PATCH" else core.delete_study(conn,ident) or {"deleted":True})
@api.get("/studies/<int:ident>/dependencies")
def study_dependencies(ident): return run(lambda conn: core.study_dependencies(conn, ident))
@api.post("/studies/<int:ident>/<action>")
def study_action(ident,action):
    data = body()
    if action == "finish": return run(lambda conn: core.finish_study(conn,ident,data.get("result"),data.get("final_score")))
    if action == "archive": return run(lambda conn: core.archive_study(conn,ident))
    if action == "restore": return run(lambda conn: core.archive_study(conn,ident,True))
    if action == "pause": return run(lambda conn: core.pause_study(conn,ident))
    if action == "resume": return run(lambda conn: core.pause_study(conn,ident,True))
    if action == "remove-current": return run(lambda conn: core.remove_current_study(conn,ident,data.get("resolution", data.get("academic_status", "available")),data.get("cancel_future_blocks", True)))
    if action == "destroy": return run(lambda conn: core.destroy(conn,"study",ident,data.get("confirmation"),data.get("include_dependencies")))
    return respond({"error":"Ação de estudo inválida."},400)
@api.post("/studies/<int:ident>/groups")
def group_create(ident): return run(lambda conn: core.create_group(conn,ident,body()))
@api.post("/studies/<int:ident>/new-attempt")
def study_new_attempt(ident): return run(lambda conn: core.new_academic_attempt(conn,ident,body()))
@api.post("/studies/<int:ident>/topics")
def topic_create(ident): return run(lambda conn: core.create_topic(conn,ident,body()))
@api.patch("/topics/<int:ident>")
def topic_item(ident): return run(lambda conn: core.update_topic(conn,ident,body()))


@api.route("/sessions",methods=["GET","POST"])
def session_collection(): return run(lambda conn: core.history(conn,request.args.get("start"),request.args.get("end")) if request.method=="GET" else core.create_session(conn,body()))
@api.route("/sessions/<int:ident>",methods=["PATCH","DELETE"])
def session_item(ident): return run(lambda conn: core.update_session(conn,ident,body()) if request.method=="PATCH" else core.delete_session(conn,ident) or {"deleted":True})


@api.route("/notes", methods=["GET", "POST"])
def note_collection():
    if request.method == "GET":
        selected_date = request.args.get("date")
        return run(lambda conn: core.notes(
            conn,
            request.args.get("study_subject_id") or request.args.get("subject_id"),
            request.args.get("topic_id"),
            request.args.get("start") or selected_date,
            request.args.get("end") or selected_date,
            request.args.get("status"),
        ))
    return run(lambda conn: core.create_note(conn, body()))


@api.route("/notes/<int:ident>", methods=["GET", "PATCH", "DELETE"])
def note_item(ident):
    if request.method == "GET":
        return run(lambda conn: core.note_detail(conn, ident))
    if request.method == "PATCH":
        return run(lambda conn: core.autosave_note(conn, ident, body()))
    return run(lambda conn: core.delete_note(conn, ident) or {"deleted": True})


@api.post("/notes/<int:ident>/finalize")
def note_finalize(ident):
    return run(lambda conn: core.finalize_note(conn, ident, body()))


@api.get("/notes/<int:ident>/export")
def note_export(ident):
    exported = {}
    # O nome retornado é ASCII seguro; o conteúdo continua UTF-8 e preserva acentos.
    try:
        with connect() as conn:
            exported.update(core.note_markdown(conn, ident))
        response = Response(exported["markdown"], mimetype="text/markdown")
        response.headers["Content-Disposition"] = f'attachment; filename="{exported["filename"]}"'
        return response
    except core.DomainError as error: return respond({"error":str(error),"code":error.code},error.status)
    except ValueError as error: return respond({"error":str(error),"code":"validation_error"},400)


@api.post("/notes/export/obsidian")
def notes_obsidian_export():
    selected = body().get("ids", body().get("note_ids"))
    def operation(conn):
        archive = BytesIO()
        with ZipFile(archive, "w", compression=ZIP_DEFLATED) as bundle:
            for item in core.notes_for_obsidian_export(conn, selected):
                bundle.writestr(item["filename"], item["markdown"].encode("utf-8"))
        return archive.getvalue()
    return download(operation, "application/zip", "anotacoes-obsidian.zip")


@api.route("/evaluations",methods=["GET","POST"])
def evaluation_collection(): return run(lambda conn: core.evaluations(conn,request.args.get("study_id")) if request.method=="GET" else core.create_evaluation(conn,body()))
@api.route("/evaluations/<int:ident>",methods=["PATCH","DELETE"])
def evaluation_item(ident): return run(lambda conn: core.change_record(conn,"avaliacoes",ident,body(),{"title","type","date","weight","max_score","score","status","notes"}) if request.method=="PATCH" else core.remove(conn,"avaliacoes",ident) or {"deleted":True})
@api.get("/reviews")
def review_collection(): return run(core.reviews)
@api.post("/reviews/<int:ident>/complete")
def review_complete(ident):
    data = body()
    return run(lambda conn: core.complete_review(conn,ident,data.get("rating"),data.get("duration_seconds"),data.get("notes")))


@api.route("/availability",methods=["GET","POST"])
def availability_collection(): return run(core.availability if request.method=="GET" else lambda conn:core.set_availability(conn,body()))
@api.post("/availability/batch")
def availability_batch(): return run(lambda conn:core.set_availability_batch(conn,body()))
@api.post("/availability/copy")
def availability_copy(): return run(lambda conn:core.copy_availability(conn,body()))
@api.route("/availability/<int:ident>",methods=["PATCH","DELETE"])
def availability_item(ident): return run(lambda conn: core.update_availability(conn,ident,body()) if request.method=="PATCH" else core.remove(conn,"disponibilidades_semanais",ident) or {"deleted":True})
@api.route("/availability-exceptions",methods=["GET","POST"])
def availability_exceptions(): return run(lambda conn:core.availability_exceptions(conn,request.args.get("start"),request.args.get("end")) if request.method=="GET" else core.set_availability_exception(conn,body()))
@api.route("/availability-exceptions/<int:ident>",methods=["PATCH","DELETE"])
def availability_exception_item(ident): return run(lambda conn:core.update_availability_exception(conn,ident,body()) if request.method=="PATCH" else core.remove(conn,"excecoes_disponibilidade",ident) or {"deleted":True})
@api.route("/planned",methods=["GET","POST"])
def planned_collection():
    today = core._today()
    return run(lambda conn: core.planned(conn,request.args.get("start",today),request.args.get("end",(core._local_now().date()+timedelta(days=6)).isoformat())) if request.method=="GET" else core.create_planned(conn,body()))
@api.delete("/planned/day/<scheduled_date>")
def planned_day_delete(scheduled_date):
    return run(lambda conn: core.delete_planned_day(conn, scheduled_date))
@api.route("/planned/<int:ident>",methods=["GET","PATCH","DELETE"])
def planned_item(ident):
    if request.method=="GET": return run(lambda conn:core.planned_detail(conn,ident))
    return run(lambda conn: core.update_planned(conn,ident,body()) if request.method=="PATCH" else core.remove(conn,"sessoes_planejadas",ident) or {"deleted":True})
@api.post("/planned/<int:ident>/reschedule")
def planned_reschedule(ident): return run(lambda conn:core.reschedule_planned(conn,ident,body()))
@api.post("/planning/generate")
def planning_generate(): return run(lambda conn: core.generate_plan(conn,body().get("start",core._today()),int(body().get("days",7))))
@api.post("/planning/apply")
def planning_apply():
    def operation(conn): return {"created":[core.create_planned(conn,item,"automatic") for item in body().get("sessions",[])]}
    return run(operation)
@api.get("/recommendation")
def recommendation(): return run(core.recommendation)
@api.get("/search")
def search(): return run(lambda conn: core.search(conn, request.args.get("q")))
@api.get("/analytics")
def analytics(): return run(core.analytics)

@api.route("/projects",methods=["GET","POST"])
def project_collection(): return run(lambda conn: core.projects(conn,request.args.get("archived")=="1") if request.method=="GET" else core.create_project(conn,body()))
@api.route("/projects/<int:ident>",methods=["GET","PATCH","DELETE"])
def project_item(ident):
    if request.method == "GET": return run(lambda conn: core.project_detail(conn,ident))
    return run(lambda conn: core.update_project(conn,ident,body()) if request.method=="PATCH" else core.remove(conn,"projetos",ident) or {"deleted":True})
@api.post("/projects/<int:ident>/<action>")
def project_action(ident, action): return run(lambda conn: core.archive_project(conn,ident,action=="restore"))
@api.post("/projects/<int:ident>/tasks")
def project_task(ident): return run(lambda conn: core.add_project_task(conn,ident,body()))
@api.route("/project-tasks/<int:ident>",methods=["PATCH","DELETE"])
def project_task_item(ident): return run(lambda conn: core.update_project_task(conn,ident,body()) if request.method=="PATCH" else core.remove(conn,"projeto_tarefas",ident) or {"deleted":True})
@api.route("/settings",methods=["GET","PUT"])
def settings(): return run(core.settings if request.method=="GET" else lambda conn: core.save_settings(conn,body()))
