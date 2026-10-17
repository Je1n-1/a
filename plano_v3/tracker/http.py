from functools import wraps
import sqlite3
from flask import Blueprint, Response, current_app, jsonify, request
from . import catalog, db, imports, timer, sessions, analytics, corrections, today, storage, topics, projects
from .domain import DomainError

api = Blueprint("api", __name__, url_prefix="/api")


def body():
    value = request.get_json(silent=True)
    if not isinstance(value, dict):
        raise DomainError("Envie um objeto JSON válido.")
    return value


def endpoint(write=False):
    def decorate(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            path = current_app.config["DATABASE_PATH"]
            context = db.transaction(path) if write else db.read_transaction(path)
            try:
                with context as conn:
                    result = function(conn, *args, **kwargs)
                    return result if isinstance(result, Response) else jsonify(result)
            except DomainError as error:
                return jsonify(error=str(error), details=error.details), error.status
            except ValueError as error:
                return jsonify(error=str(error)), 400
            except sqlite3.IntegrityError:
                return jsonify(
                    error="Os dados conflitam com um registro existente. Atualize a página e tente novamente."
                ), 409
            except sqlite3.OperationalError:
                current_app.logger.exception("Falha ao acessar o banco V3")
                return jsonify(
                    error="Não foi possível acessar o banco. Os dados da operação não foram confirmados."
                ), 503

        return wrapped

    return decorate


@api.get("/courses")
@endpoint()
def courses(conn):
    return catalog.courses(conn, request.args.get("archived") == "1")


@api.post("/courses")
@endpoint(True)
def create_course(conn):
    return catalog.save_course(conn, body())


@api.patch("/courses/<int:ident>")
@endpoint(True)
def edit_course(conn, ident):
    return catalog.save_course(conn, body(), ident)


@api.get("/subjects")
@endpoint()
def subjects(conn):
    return catalog.subjects(
        conn, request.args.get("course_id"), request.args.get("archived") == "1"
    )


@api.post("/subjects")
@endpoint(True)
def create_subject(conn):
    return catalog.save_subject(conn, body())


@api.patch("/subjects/<int:ident>")
@endpoint(True)
def edit_subject(conn, ident):
    return catalog.save_subject(conn, body(), ident)


@api.post("/<kind>/<int:ident>/archive")
@endpoint(True)
def archive(conn, kind, ident):
    if kind not in ("course", "subject"):
        raise DomainError("Registro não encontrado.", 404)
    value = body().get("archived")
    if type(value) is not bool:
        raise DomainError("Informe arquivar ou restaurar.")
    return catalog.archive(conn, kind, ident, value)


@api.post("/courses/<int:ident>/import/preview")
@endpoint()
def import_preview(conn, ident):
    if request.is_json:
        return imports.preview(conn, ident, text=body().get("text"))
    upload = request.files.get("file")
    if not upload or not upload.filename:
        raise DomainError("Escolha o arquivo da grade.")
    return imports.preview(conn, ident, upload=upload, sheet=request.form.get("sheet"))


@api.post("/courses/<int:ident>/import/confirm")
@endpoint(True)
def import_confirm(conn, ident):
    return imports.confirm(conn, ident, body())


@api.get("/today")
@endpoint()
def today_overview(conn):
    return today.overview(conn, include_catalog=request.args.get("catalog") != "0")


@api.get("/timer")
@endpoint()
def active_timer(conn):
    return timer.active(conn)


@api.post("/timer")
@endpoint(True)
def start_timer(conn):
    return timer.start(conn, body())


@api.get("/timer/<int:ident>")
@endpoint()
def timer_detail(conn, ident):
    return timer.snapshot(conn, ident)


@api.post("/timer/<int:ident>/<action>")
@endpoint(True)
def timer_action(conn, ident, action):
    return timer.transition(conn, ident, action, body())


@api.get("/sessions/recent")
@endpoint()
def recent(conn):
    return timer.recent(conn)


@api.get("/sessions/summary")
@endpoint()
def study_totals(conn):
    return analytics.quick_summary(conn)


@api.post("/sessions/manual")
@endpoint(True)
def manual_session(conn):
    return sessions.manual(conn, body())


@api.get("/sessions/<int:ident>")
@endpoint()
def session_detail(conn, ident):
    return sessions.detail(conn, ident)


@api.patch("/sessions/<int:ident>")
@endpoint(True)
def correct_session(conn, ident):
    return corrections.correct(conn, ident, body())


@api.get("/sessions/<int:ident>/corrections")
@endpoint()
def correction_history(conn, ident):
    return corrections.history(conn, ident)


@api.get("/analytics")
@endpoint()
def analytics_report(conn):
    return analytics.report(conn, request.args)


@api.get("/analytics/export.csv")
@endpoint()
def analytics_csv(conn):
    return Response(
        analytics.export_csv(conn, request.args),
        content_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="plano-estudos.csv"',
            "Cache-Control": "no-store",
        },
    )


@api.get("/diagnostics")
def diagnostics():
    path = current_app.config["DATABASE_PATH"]
    return jsonify({**db.diagnostics(path), "last_backup": storage.last_backup(path)})


@api.get("/topics")
@endpoint()
def topic_list(conn):
    return topics.listing(
        conn,
        analytics.number(request.args.get("subject_id"), "Disciplina"),
        request.args.get("review") == "1",
        request.args.get("archived") == "1",
    )


@api.post("/topics")
@endpoint(True)
def topic_create(conn):
    values = body()
    return topics.create(conn, values.get("subject_id"), values.get("name"))


@api.patch("/topics/<int:ident>")
@endpoint(True)
def topic_update(conn, ident):
    return topics.update(conn, ident, body())


@api.post("/subjects/<int:ident>/topics/preview")
@endpoint()
def topic_preview(conn, ident):
    return topics.preview(conn, ident, body())


@api.post("/subjects/<int:ident>/topics/confirm")
@endpoint(True)
def topic_confirm(conn, ident):
    return topics.create_many(conn, ident, body())


@api.get('/projects')
@endpoint()
def project_list(conn):
    return projects.listing(conn, request.args.get('archived') == '1')


@api.get('/project-steps')
@endpoint()
def project_steps(conn):
    return [dict(r) for r in conn.execute('SELECT id,project_id,name,completed FROM project_steps ORDER BY project_id,id')]


@api.post('/projects')
@endpoint(True)
def project_create(conn):
    return projects.save(conn, body())


@api.get('/projects/<int:ident>')
@endpoint()
def project_detail(conn, ident):
    return projects.detail(conn, ident)


@api.patch('/projects/<int:ident>')
@endpoint(True)
def project_update(conn, ident):
    return projects.save(conn, body(), ident)


@api.post('/projects/<int:ident>/steps')
@endpoint(True)
def step_create(conn, ident):
    return projects.save_step(conn, ident, body())


@api.patch('/projects/<int:ident>/steps/<int:step>')
@endpoint(True)
def step_update(conn, ident, step):
    return projects.save_step(conn, ident, body(), step)
