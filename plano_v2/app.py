import os
import logging

from flask import Flask, jsonify

from config import LEGACY_ROOT_DATABASE_PATH
from database.connection import active_database_path, database_health
from database.migrations import migrate, migration_status
from routes.api import api
from routes.calendar import calendar_api
from routes.pages import pages


def create_app():
    app = Flask(__name__)
    # Flask herda WARNING do logger raiz em muitos ambientes. O diagnóstico de
    # abertura do SQLite é operacionalmente importante, então este aplicativo
    # local o deixa visível sem alterar a configuração de log de outros módulos.
    app.logger.setLevel(logging.INFO)
    applied_now = migrate()
    migrations = migration_status()
    health = database_health()
    active_path = active_database_path()
    startup_diagnostics = {
        "database_path": str(active_path),
        "migrations": migrations,
        "database": health,
        "migrations_applied_now": applied_now,
    }
    # Também deixa o dado disponível para suporte e testes sem que a interface
    # tenha de adivinhar onde o SQLite foi aberto.
    app.config["PLANO_STARTUP_DIAGNOSTICS"] = startup_diagnostics
    app.logger.info(
        "PLANO_STARTUP database=%s migration=%s/%s integrity=%s foreign_key_violations=%s counts=%s applied_now=%s",
        health["path"],
        migrations["current_version"],
        migrations["latest_available_version"],
        health["integrity"],
        len(health["foreign_key_violations"]),
        health["counts"],
        applied_now or "none",
    )
    if LEGACY_ROOT_DATABASE_PATH.is_file() and LEGACY_ROOT_DATABASE_PATH != active_path:
        app.logger.warning(
            "PLANO_STARTUP legacy_database_ignored=%s active_database=%s",
            LEGACY_ROOT_DATABASE_PATH,
            active_path,
        )
    if health["integrity"] != "ok" or health["foreign_key_violations"]:
        raise RuntimeError(
            "A verificação de integridade do banco ativo falhou. "
            "A aplicação não foi iniciada para evitar alterações inseguras."
        )
    app.register_blueprint(pages)
    app.register_blueprint(api)
    app.register_blueprint(calendar_api)
    @app.errorhandler(404)
    def not_found(_): return jsonify({"error":"Recurso não encontrado."}),404
    return app


app = create_app()

if __name__ == "__main__":
    app.run(
        debug=os.environ.get("FLASK_DEBUG", "").lower() in {"1", "true", "yes"},
        host="127.0.0.1",
        port=int(os.environ.get("PLANO_PORT", "5051")),
    )
