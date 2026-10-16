"""Backups consistentes e recuperação em arquivo novo, sem trocar o banco ativo."""

from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import tempfile
from uuid import uuid4

from . import db
from .domain import DomainError

MAX_BACKUP_BYTES = 64 * 1024 * 1024


def copy_database(source: Path, target: Path) -> dict:
    source, target = Path(source).resolve(), Path(target).resolve()
    db.diagnostics(source)
    if source == target:
        raise DomainError("Escolha um arquivo novo; o banco ativo será preservado.")
    target.parent.mkdir(parents=True, exist_ok=True)
    # Reserva exclusiva: mesmo um destino criado entre a validação e a cópia é recusado.
    with target.open("xb"):
        pass
    try:
        with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as src:
            with closing(sqlite3.connect(target)) as dst:
                src.backup(dst)
        return db.diagnostics(target)
    except Exception:
        target.unlink(missing_ok=True)  # Somente o arquivo que esta chamada acabou de criar.
        raise


def metadata_path(database: Path) -> Path:
    return Path(database).with_suffix(".last-backup.json")


def last_backup(database: Path) -> dict | None:
    try:
        data = json.loads(metadata_path(database).read_text(encoding="utf-8"))
        if data["database"] != str(Path(database).resolve()):
            return None
        datetime.fromisoformat(data["created_at"])
        return {
            "created_at": data["created_at"],
            "path": data["path"],
            "available": Path(data["path"]).is_file(),
        }
    except (OSError, ValueError, KeyError, TypeError):
        return None


def create_backup(database: Path, target: Path) -> dict:
    report = copy_database(database, target)
    data = {
        "database": str(Path(database).resolve()),
        "path": report["path"],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    destination = metadata_path(database)
    temporary = destination.with_name(destination.name + "." + uuid4().hex + ".tmp")
    try:
        with temporary.open("x", encoding="utf-8") as output:
            json.dump(data, output, ensure_ascii=False)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return data


def new_destination(database: Path, kind: str) -> Path:
    if kind not in ("backups", "recovered"):
        raise ValueError("Destino de armazenamento inválido.")
    directory = Path(database).resolve().parent.parent / kind
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return directory / f"plano-{stamp}-{uuid4().hex[:12]}.db"


def recover_copy(database: Path, upload) -> dict:
    """Valida um backup enviado e o recupera em diretório separado, sem ativá-lo."""
    destination = new_destination(database, "recovered")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="validate-", dir=destination.parent) as folder:
        source = Path(folder) / "upload.db"
        size = 0
        with source.open("xb") as output:
            while chunk := upload.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_BACKUP_BYTES:
                    raise DomainError("Escolha um backup de até 64 MB.", 413)
                output.write(chunk)
        try:
            # Only the uploaded temporary copy is migrated. The active DB is never switched.
            from upgrade import contents, verify_preserved

            before = contents(source)
            db.initialize(source)
            verify_preserved(source, before)
            copy_database(source, destination)
        except (sqlite3.DatabaseError, RuntimeError) as error:
            raise DomainError(
                "Backup inválido ou incompatível com esta V3. O banco ativo foi preservado."
            ) from error
    with db.read_transaction(destination) as conn:
        sessions = conn.execute(
            "SELECT COUNT(*),COALESCE(SUM(effective_seconds),0),COALESCE(SUM(break_seconds),0) FROM study_sessions"
        ).fetchone()
        counts = {
            name: conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
            for name in ("courses", "subjects", "topics")
        }
    return {
        "path": str(destination),
        "active_database_changed": False,
        **counts,
        "sessions": sessions[0],
        "effective_seconds": sessions[1],
        "break_seconds": sessions[2],
    }
