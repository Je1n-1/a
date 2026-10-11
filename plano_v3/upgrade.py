"""Atualização explícita: backup íntegro, ensaio em cópia e preservação dos dados.

Execute com o servidor parado. Não substitui nem apaga o arquivo de origem.
"""

import argparse
from contextlib import closing
from datetime import datetime
import json
from pathlib import Path
import shutil
import sqlite3
from tracker import db


def quote(name):
    return '"' + name.replace('"', '""') + '"'


def contents(path):
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as conn:
        if (
            conn.execute("PRAGMA integrity_check").fetchall() != [("ok",)]
            or conn.execute("PRAGMA foreign_key_check").fetchall()
        ):
            raise RuntimeError("Banco sem integridade. Atualização interrompida.")
        applied = dict(conn.execute("SELECT version,checksum FROM v3_migrations"))
        known = {v: checksum for v, checksum, _ in db.versions()}
        if not applied or any(known.get(v) != checksum for v, checksum in applied.items()):
            raise RuntimeError("Versões desconhecidas ou alteradas. Atualização interrompida.")
        tables = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name!='v3_migrations'"
            )
        ]
        return {
            t: {
                "columns": [r[1] for r in conn.execute("PRAGMA table_info(" + quote(t) + ")")],
                "rows": conn.execute("SELECT * FROM " + quote(t) + " ORDER BY rowid").fetchall(),
            }
            for t in tables
        }


def verify_preserved(path, before):
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as conn:
        for table, saved in before.items():
            rows = conn.execute(
                "SELECT "
                + ",".join(quote(c) for c in saved["columns"])
                + " FROM "
                + quote(table)
                + " ORDER BY rowid"
            ).fetchall()
            if rows != saved["rows"]:
                raise RuntimeError(
                    "Divergência na preservação de "
                    + table
                    + ". Consulte o backup antes de continuar."
                )
    db.diagnostics(path)


def upgrade(database, backup_dir):
    source = Path(database).resolve()
    directory = Path(backup_dir).resolve()
    if not source.is_file():
        raise RuntimeError("Banco inexistente; este comando não cria bancos.")
    if directory == source.parent:
        raise RuntimeError("Guarde backups em outro diretório.")
    contents(source)
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    backup = directory / f"before-upgrade-{stamp}.db"
    candidate = directory / f"verified-upgrade-{stamp}.db"
    with backup.open("xb"):
        pass
    with (
        closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as src,
        closing(sqlite3.connect(backup)) as dst,
    ):
        src.backup(dst)
    before = contents(backup)
    shutil.copy2(backup, candidate)
    db.initialize(candidate)
    verify_preserved(candidate, before)
    # No writes to the source before the backup and trial migration succeed.
    if contents(source) != before:
        raise RuntimeError(
            "O banco mudou durante o ensaio. Pare o servidor e tente novamente. Cópias preservadas."
        )
    changed = db.initialize(source)
    verify_preserved(source, before)
    return {
        "database": str(source),
        "backup": str(backup),
        "verified_copy": str(candidate),
        "applied": changed,
        "existing_rows_preserved": True,
        "counts_before": {t: len(v["rows"]) for t, v in before.items()},
        "diagnostics": db.diagnostics(source),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True)
    parser.add_argument("--backup-dir", required=True)
    args = parser.parse_args()
    print(json.dumps(upgrade(args.database, args.backup_dir), ensure_ascii=False, indent=2))
