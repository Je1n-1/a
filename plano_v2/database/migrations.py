"""Runner pequeno para migrations SQL imutáveis."""
from __future__ import annotations

import argparse
import hashlib
import re
from pathlib import Path

from database.connection import connect


ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "migrations"
PATTERN = re.compile(r"^(\d{4})_([a-z0-9_]+)\.sql$")


def available(directory: Path = MIGRATIONS):
    items = []
    for file in sorted(directory.glob("*.sql")):
        match = PATTERN.fullmatch(file.name)
        if not match:
            raise RuntimeError(f"Nome de migration inválido: {file.name}")
        raw = file.read_bytes()
        items.append((int(match.group(1)), match.group(2), raw.decode("utf-8"), hashlib.sha256(raw).hexdigest()))
    return items


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
            conn.executescript("BEGIN IMMEDIATE;\n" + sql)
            conn.execute("INSERT INTO schema_migrations (version, name, checksum) VALUES (?, ?, ?)", (version, name, checksum))
            conn.execute("COMMIT")
            applied_now.append(version)
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

