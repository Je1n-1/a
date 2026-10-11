"""Mede somente bases sintéticas isoladas (0, 1.000 e 10.000 sessões)."""

import argparse
from contextlib import closing
from datetime import date, timedelta
import json
import os
from pathlib import Path
import platform
import socket
import statistics
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import create_app
from tracker import analytics, db


def seed(path, count):
    if path.exists():
        return
    db.initialize(path)
    today = date(2026, 10, 10)
    with db.transaction(path) as conn:
        conn.executemany(
            "INSERT INTO courses(id,name,created_at) VALUES (?,?,?)",
            [(i, "Curso de teste " + str(i), today.isoformat()) for i in range(1, 5)],
        )
        conn.executemany(
            "INSERT INTO subjects(id,course_id,name,name_key,created_at) VALUES (?,?,?,?,?)",
            [
                (
                    i,
                    1 + (i - 1) % 4,
                    "Disciplina " + str(i),
                    "disciplina " + str(i),
                    today.isoformat(),
                )
                for i in range(1, 17)
            ],
        )
        for i in range(1, count + 1):
            day = (today - timedelta(days=(i - 1) % 365)).isoformat()
            seconds = 600 + i % 3600
            conn.execute(
                """INSERT INTO study_sessions(id,subject_id,title,source,local_date,effective_seconds,created_at)
                VALUES (?,?,?,'manual',?,?,?)""",
                (i, 1 + (i - 1) % 16, "Sessão sintética", day, seconds, today.isoformat()),
            )
            conn.execute("INSERT INTO session_days VALUES (?,?,?,0)", (i, day, seconds))


def measured(function, repeats=9):
    function()  # Warm-up reported separately from process startup.
    times = []
    for _ in range(repeats):
        start = time.perf_counter()
        function()
        times.append((time.perf_counter() - start) * 1000)
    return {
        "median_ms": round(statistics.median(times), 3),
        "min_ms": round(min(times), 3),
        "max_ms": round(max(times), 3),
        "runs": repeats,
    }


def run(phase, directory):
    directory.mkdir(parents=True, exist_ok=True)
    result = {
        "phase": phase,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "cases": [],
    }
    for count in (0, 1000, 10000):
        path = directory / f"sessions-{count}.db"
        seed(path, count)
        startup = []
        for _ in range(5):
            code = "import time,sys; t=time.perf_counter(); from app import create_app; create_app(sys.argv[1]); print((time.perf_counter()-t)*1000)"
            out = subprocess.check_output(
                [sys.executable, "-c", code, str(path)], cwd=ROOT, text=True
            )
            startup.append(float(out.strip()))
        app = create_app(path)
        client = app.test_client()

        def report():
            with db.read_transaction(path) as conn:
                return analytics.report(conn, {"start": "2026-09-11", "end": "2026-10-10"})

        def full_year():
            with db.read_transaction(path) as conn:
                return analytics.report(conn, {"start": "2025-10-11", "end": "2026-10-10"})

        f = analytics.filters({"start": "2026-09-11", "end": "2026-10-10"})
        sql, args = analytics.history_query(f)
        with db.read_transaction(path) as conn:
            plan = [
                dict(r)
                for r in conn.execute(
                    "EXPLAIN QUERY PLAN " + sql + " LIMIT ? OFFSET ?", [*args, 20, 0]
                )
            ]
        item = {
            "sessions": count,
            "database_bytes": path.stat().st_size,
            "startup_import_and_create_app_ms": round(statistics.median(startup), 3),
            "report_30_days": measured(report),
            "report_365_days": measured(full_year),
            "http_analytics": measured(
                lambda: client.get("/api/analytics?start=2026-09-11&end=2026-10-10")
            ),
            "history_query_plan": plan,
        }
        with closing(socket.socket()) as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        process = subprocess.Popen(
            [sys.executable, str(ROOT / "app.py"), "--database", str(path), "--port", str(port)],
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        try:
            for _ in range(100):
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/timer", timeout=1):
                        break
                except OSError:
                    time.sleep(0.05)
            raw = subprocess.check_output(
                ["node", str(ROOT / "scripts" / "benchmark-browser.cjs"), str(port)],
                cwd=ROOT,
                text=True,
            )
            item["browser"] = json.loads(raw)
        finally:
            process.terminate()
            process.wait(timeout=10)
        result["cases"].append(item)
    destination = ROOT / "docs" / f"phase4-benchmark-{phase}.json"
    destination.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=["before", "after"], required=True)
    parser.add_argument("--directory", required=True)
    args = parser.parse_args()
    run(args.phase, Path(args.directory).resolve())
