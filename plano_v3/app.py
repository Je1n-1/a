"""Plano V3 local: execute --init-db explicitamente antes de servir."""

import argparse
import os
from pathlib import Path
from urllib.parse import urlsplit
from flask import Flask, jsonify, render_template, request, url_for
from werkzeug.exceptions import RequestEntityTooLarge
from tracker import db
from tracker.http import api
from tracker.storage_http import api as storage_api

ROOT = Path(__file__).resolve().parent


def create_app(database_path=None):
    selected = database_path or os.environ.get("PLANO_V3_DATABASE_PATH")
    if not selected:
        raise RuntimeError(
            "Defina PLANO_V3_DATABASE_PATH ou passe --database com um caminho absoluto V3."
        )
    path = Path(selected).expanduser()
    if not path.is_absolute():
        raise RuntimeError("O caminho do banco V3 deve ser absoluto.")
    path = path.resolve()
    if not path.is_file():
        raise RuntimeError(
            f"Banco V3 não encontrado: {path}. Inicialize explicitamente com --init-db."
        )
    report = db.diagnostics(path)
    app = Flask(__name__)
    app.config.update(DATABASE_PATH=path, MAX_CONTENT_LENGTH=65 * 1024 * 1024)
    app.register_blueprint(api)
    app.register_blueprint(storage_api)

    @app.before_request
    def local_requests():
        if request.host.split(":")[0] not in ("localhost", "127.0.0.1"):
            return jsonify(error="Aplicação disponível somente no endereço local."), 403
        origin = request.headers.get("Origin")
        if (
            request.method not in ("GET", "HEAD", "OPTIONS")
            and origin
            and urlsplit(origin).netloc != request.host
        ):
            return jsonify(error="Abra o Plano no endereço local para continuar."), 403
        if (
            request.endpoint != "storage.recover"
            and (request.content_length or 0) > 6 * 1024 * 1024
        ):
            raise RequestEntityTooLarge()

    @app.context_processor
    def assets():
        def asset(name):
            return url_for("static", filename=name, v=(ROOT / "static" / name).stat().st_mtime_ns)

        return {"asset": asset}

    @app.get("/")
    @app.get("/focus")
    def today():
        return render_template("today.html", page="today", title="Hoje")

    @app.get("/subjects")
    def subjects():
        return render_template("subjects.html", page="subjects", title="Disciplinas")

    @app.get("/analytics")
    def analytics():
        return render_template("analytics.html", page="analytics", title="Análises")

    @app.errorhandler(413)
    def too_large(_):
        limit = 64 if request.endpoint == "storage.recover" else 5
        return jsonify(error=f"O envio excede o limite. Use um arquivo de até {limit} MB."), 413

    app.logger.info("Plano V3: schema=%s integrity=%s", report["schema"], report["integrity"])
    return app


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Plano V3 — registro de estudos local")
    parser.add_argument("--database", default=os.environ.get("PLANO_V3_DATABASE_PATH"))
    parser.add_argument(
        "--init-db", action="store_true", help="Inicializar/migrar explicitamente e sair"
    )
    parser.add_argument("--port", type=int, default=5054)
    args = parser.parse_args()
    if not args.database or not Path(args.database).is_absolute():
        parser.error("Informe --database com caminho absoluto, ou PLANO_V3_DATABASE_PATH.")
    if args.init_db:
        print("Migrations:", db.initialize(args.database))
        print("Banco:", Path(args.database).resolve())
    else:
        create_app(args.database).run(
            host="127.0.0.1", port=args.port, debug=False, use_reloader=False
        )
