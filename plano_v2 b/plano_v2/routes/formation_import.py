"""Importação inicial atômica, reutilizando o parser e as regras curriculares.

A prévia não cria formação. Confirmar cria formação e grade na mesma transação.
Não consulta disponibilidade, esforço pessoal ou motor de planejamento.
"""
from flask import Blueprint, request

from routes.api import body, run
from services import core
from services.grade_import import normalized, preview

formation_import = Blueprint("formation_import", __name__, url_prefix="/api/formation-import")


@formation_import.post("/preview")
def preview_new_formation():
    def operation(conn):
        upload = request.files.get("file")
        if not upload or not upload.filename:
            raise core.DomainError("Selecione um arquivo PDF.")
        return preview(upload, upload.filename, request.form.get("sheet"))
    return run(operation)


@formation_import.post("/confirm")
def confirm_new_formation():
    data = body()
    def operation(conn):
        if not core._confirmed(data.get("confirmed")):
            raise core.DomainError("Confira a grade antes de salvar.")
        items = data.get("items")
        if not isinstance(items, list) or not any(row.get("include", True) for row in items if isinstance(row, dict)):
            raise core.DomainError("Selecione pelo menos uma disciplina.")
        metadata = data.get("formation") or {}
        if not isinstance(metadata, dict):
            raise core.DomainError("Informe os dados da formação.")
        # Uma repetição de confirmação não deve criar outra formação idêntica.
        conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute("SELECT name,institution FROM formacoes WHERE archived_at IS NULL").fetchall()
        if any(normalized(row["name"]) == normalized(metadata.get("name")) and
               normalized(row["institution"]) == normalized(metadata.get("institution")) for row in existing):
            raise core.DomainError("Essa formação já existe. Selecione-a e use Importar PDF para atualizar sua grade.", 409, "formation_exists")
        formation = core.create_formation(conn, metadata)
        result = core.import_curriculum(conn, formation["id"], items, True)
        if not result["summary"]["inserted"]:
            raise core.DomainError("Nenhuma disciplina válida foi selecionada.")
        return {"formation": formation, **result}
    return run(operation)
