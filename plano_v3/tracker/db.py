"""SQLite V3 explícito. Abrir a aplicação nunca cria/migra um banco."""

from contextlib import closing, contextmanager
from pathlib import Path
import hashlib
import sqlite3
import runpy

MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"


def connect(path):
    # mode=rw falha se o arquivo desaparecer, em vez de criar outro vazio.
    conn = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=rw", uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def read_transaction(path):
    conn = connect(path)
    try:
        # Um snapshot envolve várias consultas; todas devem observar a mesma versão.
        conn.execute("BEGIN")
        yield conn
    finally:
        conn.rollback()
        conn.close()


@contextmanager
def transaction(path):
    conn = connect(path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def versions():
    result = []
    for p in sorted(MIGRATIONS.glob("*.sql")):
        hook = p.with_suffix(".py")
        data = p.read_bytes() + (b"\0" + hook.read_bytes() if hook.exists() else b"")
        result.append((p.stem, hashlib.sha256(data).hexdigest(), p.read_text(encoding="utf-8")))
    return result


def initialize(path):
    path = Path(path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    # A criação acontece somente na ação explícita --init-db.
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        existing = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if existing and "v3_migrations" not in existing:
            raise RuntimeError(
                "Este arquivo não é um banco V3. Escolha um novo caminho; a V2 não será convertida."
            )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS v3_migrations(version TEXT PRIMARY KEY, checksum TEXT NOT NULL)"
        )
        conn.commit()
        applied = dict(conn.execute("SELECT version,checksum FROM v3_migrations"))
        known = {v: checksum for v, checksum, _ in versions()}
        if any(known.get(v) != checksum for v, checksum in applied.items()):
            raise RuntimeError("Versão desconhecida ou migration alterada. Banco preservado.")
        changed = []
        for version, checksum, sql in versions():
            if version in applied:
                continue
            try:
                conn.executescript("BEGIN IMMEDIATE;\n" + sql)
                hook = MIGRATIONS / (version + ".py")
                if hook.exists():
                    runpy.run_path(str(hook))["migrate"](conn)
                if conn.execute("PRAGMA foreign_key_check").fetchall():
                    raise RuntimeError("Migration gerou relações inválidas.")
                conn.execute("INSERT INTO v3_migrations VALUES (?,?)", (version, checksum))
                conn.commit()
                changed.append(version)
            except Exception:
                conn.rollback()
                raise
        return changed
    finally:
        conn.close()


def diagnostics(path):
    path = Path(path).resolve()
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "v3_migrations" not in tables:
            raise RuntimeError("Banco incompatível: use um banco V3 criado por --init-db.")
        required = {
            "topics",
            "projects",
            "project_steps",
            "courses",
            "subjects",
            "timers",
            "timer_intervals",
            "study_sessions",
            "timer_recoveries",
            "session_days",
            "session_corrections",
        }
        if not required.issubset(tables):
            raise RuntimeError("Banco V3 incompleto: faltam tabelas. Restaure uma cópia íntegra.")
        applied = dict(conn.execute("SELECT version,checksum FROM v3_migrations"))
        expected = {v: checksum for v, checksum, _ in versions()}
        if applied != expected:
            raise RuntimeError(
                "Esquema diferente do esperado. Verifique migrations antes de iniciar."
            )
        integrity = [r[0] for r in conn.execute("PRAGMA integrity_check")]
        foreign_keys = conn.execute("PRAGMA foreign_key_check").fetchall()
        if integrity != ["ok"] or foreign_keys:
            raise RuntimeError("Falha na integridade do banco; inicialização interrompida.")
        mismatch = conn.execute("""SELECT x.id FROM study_sessions x LEFT JOIN
            (SELECT session_id,SUM(effective_seconds) focus,SUM(break_seconds) pauses,SUM(rest_seconds) rests FROM session_days GROUP BY session_id) d
            ON d.session_id=x.id WHERE d.session_id IS NULL OR d.focus!=x.effective_seconds OR d.pauses!=x.break_seconds OR d.rests!=x.rest_seconds LIMIT 1""").fetchone()
        if mismatch:
            raise RuntimeError(
                "Rateio diário inconsistente com as sessões. Confira uma cópia antes de continuar."
            )
        for table in ("timers", "study_sessions"):
            mismatch = conn.execute(
                f"SELECT x.id FROM {table} x LEFT JOIN topics t ON t.id=x.topic_id WHERE (x.topic_id IS NOT NULL AND (t.id IS NULL OR x.subject_id IS NOT t.subject_id OR x.topic_name IS NULL)) OR (x.session_kind='review' AND x.topic_id IS NULL) LIMIT 1"
            ).fetchone()
            if mismatch:
                raise RuntimeError("Vínculo de tópico inconsistente com a disciplina.")
        for table in ("timers", "study_sessions"):
            mismatch = conn.execute(f"""SELECT x.id FROM {table} x LEFT JOIN project_steps st ON st.id=x.step_id
                WHERE (x.project_id IS NOT NULL AND (x.subject_id IS NOT NULL OR x.topic_id IS NOT NULL OR x.project_name IS NULL OR x.session_kind='review'))
                OR (x.step_id IS NOT NULL AND (x.project_id IS NULL OR st.project_id IS NOT x.project_id OR x.step_name IS NULL)) LIMIT 1""").fetchone()
            if mismatch:
                raise RuntimeError("Vínculo de projeto ou etapa inconsistente.")
        return {
            "path": str(path),
            "schema": list(applied),
            "integrity": "ok",
            "foreign_key_violations": len(foreign_keys),
            "last_backup": None,
        }
