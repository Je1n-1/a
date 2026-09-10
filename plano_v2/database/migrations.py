"""Runner pequeno para migrations SQL imutáveis."""
from __future__ import annotations

import argparse
import hashlib
import logging
import re
import sqlite3
from pathlib import Path

from database.connection import active_database_path, connect


ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "migrations"
PATTERN = re.compile(r"^(\d{4})_([a-z0-9_]+)\.sql$")

# As migrations 0007 e 0008 recriam tabelas SQLite preservando IDs, chaves,
# sessões e anotações. O SQLite não permite desligar foreign_keys dentro de uma
# transação, portanto a troca é feita antes do BEGIN e sempre seguida da mesma
# verificação que protege exclusões.
REBUILD_WITH_FOREIGN_KEYS_DISABLED = {7, 8}

# Entidades que carregam dados do usuário. Uma migration estrutural não pode
# reduzir nenhuma dessas contagens sem ser tratada como alteração excepcional e
# auditada. Tabelas novas simplesmente não entram na comparação anterior.
PRESERVED_TABLES = (
    "formacoes",
    "disciplinas_grade",
    "materias_estudo",
    "topicos",
    "sessoes_estudo",
    "sessoes_planejadas",
    "avaliacoes",
    "revisoes",
    "anotacoes_estudo",
)
LOGGER = logging.getLogger(__name__)


def available(directory: Path = MIGRATIONS):
    items = []
    for file in sorted(directory.glob("*.sql")):
        match = PATTERN.fullmatch(file.name)
        if not match:
            raise RuntimeError(f"Nome de migration inválido: {file.name}")
        raw = file.read_bytes()
        items.append((int(match.group(1)), match.group(2), raw.decode("utf-8"), hashlib.sha256(raw).hexdigest()))
    return items


def migration_status(path=None):
    """Relata o estado das migrations sem abrir um banco novo nem alterá-lo."""
    database = active_database_path(path)
    known = {version: (name, checksum) for version, name, _, checksum in available()}
    report = {
        "database_path": str(database),
        "exists": database.is_file(),
        "current_version": 0,
        "latest_available_version": max(known, default=0),
        "applied_versions": [],
        "pending_versions": sorted(known),
        "checksum_mismatches": [],
        "unknown_applied_versions": [],
        "healthy": False,
    }
    if not database.is_file():
        return report
    try:
        uri = f"{database.as_uri()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        try:
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
            ).fetchone()
            if not exists:
                report["error"] = "schema_migrations_not_found"
                return report
            applied = {
                int(version): (name, checksum)
                for version, name, checksum in conn.execute(
                    "SELECT version,name,checksum FROM schema_migrations ORDER BY version"
                )
            }
        finally:
            conn.close()
    except sqlite3.Error as error:
        report["error"] = str(error)
        return report

    report["applied_versions"] = sorted(applied)
    report["current_version"] = max(applied, default=0)
    report["pending_versions"] = [version for version in sorted(known) if version not in applied]
    report["unknown_applied_versions"] = [version for version in sorted(applied) if version not in known]
    report["checksum_mismatches"] = [
        version for version, value in applied.items()
        if version in known and known[version] != value
    ]
    report["healthy"] = not (
        report["pending_versions"]
        or report["checksum_mismatches"]
        or report["unknown_applied_versions"]
    )
    return report


def _table_counts(conn: sqlite3.Connection) -> dict[str, int]:
    existing = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    return {
        table: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        for table in PRESERVED_TABLES
        if table in existing
    }


def _validate_after_migration(conn: sqlite3.Connection, version: int, before_counts: dict[str, int]) -> dict[str, int]:
    """Valida a migration ainda na transação, antes de torná-la definitiva."""
    integrity = [row[0] for row in conn.execute("PRAGMA integrity_check")]
    if integrity != ["ok"]:
        raise RuntimeError(f"Migration {version:04d} falhou na integridade SQLite: {integrity}")
    violations = [tuple(row) for row in conn.execute("PRAGMA foreign_key_check")]
    if violations:
        raise RuntimeError(f"Migration {version:04d} criou violações de chave estrangeira: {violations[:5]}")
    after_counts = _table_counts(conn)
    losses = {
        table: {"before": count, "after": after_counts.get(table)}
        for table, count in before_counts.items()
        if after_counts.get(table) is None or after_counts[table] < count
    }
    if losses:
        raise RuntimeError(
            f"Migration {version:04d} reduziria registros preservados: {losses}. "
            "A migration foi desfeita antes da confirmação."
        )
    return after_counts


def migrate(path=None):
    applied_now = []
    with connect(path) as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY, name TEXT NOT NULL, checksum TEXT NOT NULL,
            applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        )""")
        applied = {row["version"]: (row["name"], row["checksum"])
                   for row in conn.execute("SELECT version, name, checksum FROM schema_migrations")}
        for version, name, sql, checksum in available():
            if version in applied:
                if applied[version] != (name, checksum):
                    raise RuntimeError(f"Migration {version:04d} foi alterada após aplicação.")
                continue
            foreign_keys_disabled = version in REBUILD_WITH_FOREIGN_KEYS_DISABLED
            before_counts = _table_counts(conn)
            if foreign_keys_disabled:
                # Sem uma transação aberta, esta é a única forma segura de
                # recriar uma tabela pai preservando as FKs das tabelas filhas.
                conn.commit()
                conn.execute("PRAGMA foreign_keys = OFF")
            try:
                conn.executescript("BEGIN IMMEDIATE;\n" + sql)
                after_counts = _validate_after_migration(conn, version, before_counts)
                conn.execute("INSERT INTO schema_migrations (version, name, checksum) VALUES (?, ?, ?)", (version, name, checksum))
                conn.execute("COMMIT")
            except Exception:
                conn.rollback()
                raise
            finally:
                if foreign_keys_disabled:
                    conn.execute("PRAGMA foreign_keys = ON")
                    violations = conn.execute("PRAGMA foreign_key_check").fetchall()
                    if violations:
                        raise RuntimeError(f"Migration {version:04d} criou violações de chave estrangeira.")
            applied_now.append(version)
            LOGGER.info(
                "PLANO_MIGRATION version=%04d name=%s records_before=%s records_after=%s",
                version,
                name,
                before_counts,
                after_counts,
            )
    return applied_now


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["migrate", "status"])
    args = parser.parse_args()
    if args.command == "migrate":
        print("Aplicadas:", migrate() or "nenhuma")
    else:
        with connect() as conn:
            done = {r[0] for r in conn.execute("SELECT version FROM schema_migrations")} if conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='schema_migrations'").fetchone() else set()
        for version, name, _, _ in available():
            print(f"{version:04d}_{name}: {'aplicada' if version in done else 'pendente'}")
