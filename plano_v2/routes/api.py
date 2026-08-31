from datetime import timedelta
import sqlite3

from flask import Blueprint, jsonify, request

from database.connection import connect
from services import core
from services.grade_import import preview


api = Blueprint("api", __name__, url_prefix="/api")


def body(): return request.get_json(silent=True) or request.form.to_dict()
def respond(value, status=200): return jsonify(value), status
def run(operation):
    try:
        with connect() as conn: return respond(operation(conn))
    except core.DomainError as error: return respond({"error":str(error)},error.status)
    except ValueError as error: return respond({"error":str(error)},400)
    except sqlite3.IntegrityError as error: return respond({"error":str(error)},409)


@api.get("/bootstrap")
def bootstrap():
    def operation(conn):
        today=core._local_now().date(); end=today+timedelta(days=6)
        return {"formations":core.formations(conn),"studies":core.studies(conn),"recommendation":core.recommendation(conn),"reviews":core.reviews(conn),"analytics":core.analytics(conn),"planned":core.planned(conn,today.isoformat(),end.isoformat())}
    return run(operation)


@api.route("/formations",methods=["GET","POST"])
def formation_collection():
    return run(lambda conn: core.formations(conn,request.args.get("archived")=="1") if request.method=="GET" else core.create_formation(conn,body()))
@api.route("/formations/<int:ident>",methods=["PATCH","DELETE"])
def formation_item(ident):
    return run(lambda conn: core.change_formation(conn,ident,body()) if request.method=="PATCH" else core.remove(conn,"formacoes",ident) or {"deleted":True})
@api.post("/formations/<int:ident>/<action>")
def formation_action(ident,action):
    if action not in ("archive","restore"): return respond({"error":"Ação de formação inválida."},400)
    return run(lambda conn: core.archive(conn,"formacoes",ident,action=="restore"))


@api.get("/formations/<int:formation_id>/curriculum")
def curriculum(formation_id): return run(lambda conn: core.curriculum(conn,formation_id,request.args.get("archived")=="1"))
@api.post("/formations/<int:formation_id>/curriculum")
def curriculum_create(formation_id): return run(lambda conn: core.create_curriculum(conn,formation_id,body()))
@api.post("/formations/<int:formation_id>/curriculum/preview")
def curriculum_preview(formation_id):
    def operation(conn):
        core._get(conn,"formacoes",formation_id)
        upload=request.files.get("file")
        if not upload or not upload.filename: raise core.DomainError("Selecione um arquivo.")
        return {"items":preview(upload,upload.filename)}
    return run(operation)
@api.post("/formations/<int:formation_id>/curriculum/import")
def curriculum_import(formation_id): return run(lambda conn: core.import_curriculum(conn,formation_id,body().get("items",[])))
@api.route("/curriculum/<int:ident>",methods=["PATCH","DELETE"])
def curriculum_item(ident): return run(lambda conn: core.update_curriculum(conn,ident,body()) if request.method=="PATCH" else core.remove(conn,"disciplinas_grade",ident) or {"deleted":True})
@api.post("/curriculum/<int:ident>/<action>")
def curriculum_action(ident,action):
    if action not in ("archive","restore"): return respond({"error":"Ação de disciplina inválida."},400)
    return run(lambda conn: core.archive(conn,"disciplinas_grade",ident,action=="restore"))
@api.post("/curriculum/<int:ident>/add-study")
def curriculum_add_study(ident): return run(lambda conn: core.add_curriculum_study(conn,ident,body()))


@api.route("/studies",methods=["GET","POST"])
def study_collection(): return run(lambda conn: core.studies(conn,request.args.get("archived")=="1") if request.method=="GET" else core.create_personal_study(conn,body()))
@api.get("/studies/<int:ident>")
def study_detail(ident): return run(lambda conn: core.subject_detail(conn,ident))
@api.route("/studies/<int:ident>",methods=["PATCH","DELETE"])
def study_item(ident): return run(lambda conn: core.update_study(conn,ident,body()) if request.method=="PATCH" else core.remove(conn,"materias_estudo",ident) or {"deleted":True})
@api.post("/studies/<int:ident>/<action>")
def study_action(ident,action):
    if action not in ("finish","archive","restore"): return respond({"error":"Ação de estudo inválida."},400)
    return run(lambda conn: core.finish_study(conn,ident,body().get("result"),body().get("final_score")) if action=="finish" else core.archive(conn,"materias_estudo",ident,action=="restore"))
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
