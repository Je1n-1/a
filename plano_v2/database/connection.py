import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from config import DATABASE_PATH


def active_database_path(path: str | Path | None = None) -> Path:
    """Devolve o caminho absoluto do banco que esta conexão usará.

    Toda a aplicação passa por este ponto para abrir SQLite.  O parâmetro
    opcional existe para migrations e testes isolados; no uso normal ele aponta
    para ``config.DATABASE_PATH`` (``instance/plano.db`` por padrão).

    O nome do módulo é mantido como variável para que a suíte de testes possa
    continuar a substituir ``connection.DATABASE_PATH`` sem tocar no banco do
    usuário.
    """
    selected = Path(DATABASE_PATH if path is None else path).expanduser()
    return selected.resolve()


def database_health(path: str | Path | None = None) -> dict[str, Any]:
    """Inspeciona um SQLite existente sem criar nem modificar arquivos.

    Este diagnóstico é seguro para a inicialização e para a tela de suporte:
    relata integridade, FKs e contagens estruturais, sem expor conteúdo de
    estudo, anotações ou sessões individuais.
    """
    database = active_database_path(path)
    report: dict[str, Any] = {
        "path": str(database),
        "exists": database.is_file(),
        "integrity": "not_checked",
        "foreign_key_violations": [],
        "counts": {},
    }
    if not database.is_file():
        report["integrity"] = "database_not_found"
        return report

    tables = {
        "formations": "formacoes",
        "curriculum_subjects": "disciplinas_grade",
        "studies": "materias_estudo",
        "topics": "topicos",
        "study_sessions": "sessoes_estudo",
        "planned_sessions": "sessoes_planejadas",
        "evaluations": "avaliacoes",
        "reviews": "revisoes",
        "notes": "anotacoes_estudo",
        "focus_sessions": "sessoes_foco",
        "canonical_study_links": "curriculum_study_links",
    }
    try:
        # ``mode=ro`` evita até a criação de um journal durante a leitura.
        uri = f"{database.as_uri()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        try:
            integrity_rows = [row[0] for row in conn.execute("PRAGMA integrity_check")]
            report["integrity"] = "ok" if integrity_rows == ["ok"] else "failed"
            if integrity_rows != ["ok"]:
                report["integrity_details"] = integrity_rows
            report["foreign_key_violations"] = [
                {"table": row[0], "rowid": row[1], "parent": row[2], "fkid": row[3]}
                for row in conn.execute("PRAGMA foreign_key_check")
            ]
            existing_tables = {
                row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            report["counts"] = {
                label: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                for label, table in tables.items()
                if table in existing_tables
            }
        finally:
            conn.close()
    except sqlite3.Error as error:
        report["integrity"] = "unavailable"
        report["error"] = str(error)
    return report


@contextmanager
def connect(path: str | Path | None = None):
    database = active_database_path(path)
    database.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(database)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
