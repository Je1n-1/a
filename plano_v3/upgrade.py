"""Atualização explícita: backup íntegro, ensaio em cópia e preservação dos dados.

Execute com o servidor parado. Não substitui nem apaga o arquivo de origem.
"""

import argparse
from contextlib import closing
from datetime import datetime
import json
import hashlib
import struct
from pathlib import Path
import shutil
import sqlite3
from tracker import db


def quote(name):
    return '"' + name.replace('"', '""') + '"'


def fingerprint(conn, table, columns):
    """Hash typed, length-delimited values in bounded batches, in stable row order."""
    digest = hashlib.sha256()
    count = 0
    cursor = conn.execute('SELECT ' + ','.join(quote(c) for c in columns) + ' FROM ' + quote(table) + ' ORDER BY rowid')
    while batch := cursor.fetchmany(128):
        for row in batch:
            digest.update(b'R')
            for value in row:
                if value is None:
                    kind, raw = b'N', b''
                elif isinstance(value, int):
                    kind, raw = b'I', str(value).encode('ascii')
                elif isinstance(value, float):
                    kind, raw = b'F', struct.pack('!d', value)
                elif isinstance(value, bytes):
                    kind, raw = b'B', value
                else:
                    kind, raw = b'T', value.encode('utf-8')
                digest.update(kind + struct.pack('!Q', len(raw)))
                digest.update(raw)
            count += 1
    return {'count': count, 'sha256': digest.hexdigest()}


def contents(path):
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as conn:
        conn.execute('BEGIN')
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
        result = {}
        for table in tables:
            columns = [r[1] for r in conn.execute('PRAGMA table_info(' + quote(table) + ')')]
            result[table] = {'columns': columns, **fingerprint(conn, table, columns)}
        return result


def verify_preserved(path, before):
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as conn:
        conn.execute('BEGIN')
        for table, saved in before.items():
            actual = fingerprint(conn, table, saved['columns'])
            if actual != {key: saved[key] for key in ('count', 'sha256')}:
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
        "counts_before": {t: v['count'] for t, v in before.items()},
        "diagnostics": db.diagnostics(source),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True)
    parser.add_argument("--backup-dir", required=True)
    args = parser.parse_args()
    print(json.dumps(upgrade(args.database, args.backup_dir), ensure_ascii=False, indent=2))
