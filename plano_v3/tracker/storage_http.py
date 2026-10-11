"""Ações explícitas de armazenamento, fora das transações do relógio."""

from functools import wraps
import sqlite3

from flask import Blueprint, current_app, jsonify, request, send_file

from . import storage
from .domain import DomainError

api = Blueprint("storage", __name__, url_prefix="/api")


def storage_errors(function):
    @wraps(function)
    def wrapped():
        try:
            return function()
        except DomainError as error:
            return jsonify(error=str(error)), error.status
        except (OSError, RuntimeError, sqlite3.DatabaseError):
            current_app.logger.error("Falha na operação de armazenamento local")
            return jsonify(
                error="Não foi possível concluir a cópia. Confira espaço e permissão na pasta de dados. O banco ativo foi preservado."
            ), 503

    return wrapped


@api.post("/backups")
@storage_errors
def backup():
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or body.get("confirmed") is not True:
        raise DomainError("Confirme a criação do backup.")
    database = current_app.config["DATABASE_PATH"]
    target = storage.new_destination(database, "backups")
    storage.create_backup(database, target)
    response = send_file(
        target, as_attachment=True, download_name=target.name, mimetype="application/vnd.sqlite3"
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@api.post("/backups/recover")
@storage_errors
def recover():
    if request.form.get("confirmed") != "true":
        raise DomainError("Confirme a recuperação em arquivo separado.")
    upload = request.files.get("file")
    if upload is None or not upload.filename:
        raise DomainError("Escolha um backup do Plano V3.")
    return jsonify(storage.recover_copy(current_app.config["DATABASE_PATH"], upload))
