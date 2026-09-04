import os

from flask import Flask, jsonify

from database.migrations import migrate
from routes.api import api
from routes.pages import pages


def create_app():
    app = Flask(__name__)
    migrate()
    app.register_blueprint(pages)
    app.register_blueprint(api)
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
