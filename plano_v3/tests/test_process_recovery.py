"""Reinício real após interrupção abrupta, exclusivamente em SQLite temporário."""

import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from contextlib import closing
from tracker import db

ROOT = Path(__file__).resolve().parents[1]


class ProcessRecovery(unittest.TestCase):
    def test_crash_restart_running_paused_and_transaction_rollback(self):
        with tempfile.TemporaryDirectory() as folder:
            database = Path(folder) / "crash.db"
            db.initialize(database)
            with closing(socket.socket()) as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]
            base = f"http://127.0.0.1:{port}/api"
            process = None

            def request(route, payload=None):
                body = json.dumps(payload).encode() if payload is not None else None
                req = urllib.request.Request(
                    base + route, data=body, headers={"Content-Type": "application/json"}
                )
                with urllib.request.urlopen(req, timeout=3) as response:
                    return json.load(response)

            def launch():
                child = subprocess.Popen(
                    [
                        sys.executable,
                        str(ROOT / "app.py"),
                        "--database",
                        str(database),
                        "--port",
                        str(port),
                    ],
                    cwd=ROOT,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
                for _ in range(100):
                    try:
                        request("/diagnostics")
                        return child
                    except (OSError, urllib.error.URLError):
                        if child.poll() is not None:
                            break
                        time.sleep(0.05)
                child.kill()
                child.wait(timeout=5)
                self.fail("Servidor de teste não iniciou.")

            try:
                process = launch()
                t = request("/timer", {"operation_key": "crash-test", "title": "Teste"})
                process.kill()
                process.wait(timeout=5)
                time.sleep(1.1)
                process = launch()
                recovered = request("/timer")
                self.assertEqual((recovered["id"], recovered["status"]), (t["id"], "running"))
                self.assertGreaterEqual(recovered["effective_seconds"], 1)
                paused = request(f"/timer/{t['id']}/pause", {"version": recovered["version"]})
                process.kill()
                process.wait(timeout=5)
                process = launch()
                recovered = request("/timer")
                self.assertEqual(
                    (recovered["status"], recovered["effective_seconds"]),
                    ("paused", paused["effective_seconds"]),
                )
                finished = request(f"/timer/{t['id']}/finish", {"version": recovered["version"]})
                repeat = request(f"/timer/{t['id']}/finish", {"version": recovered["version"]})
                self.assertEqual(finished["session_id"], repeat["session_id"])
                self.assertEqual(len(request("/sessions/recent")), 1)
            finally:
                if process and process.poll() is None:
                    process.kill()
                    process.wait(timeout=5)
            # A killed writer cannot leave half a transaction in the history.
            code = "import sqlite3,sys,os; c=sqlite3.connect(sys.argv[1]); c.execute('BEGIN IMMEDIATE'); c.execute(\"INSERT INTO courses(name,created_at) VALUES ('uncommitted','2026-10-10')\"); os._exit(9)"
            result = subprocess.run(
                [sys.executable, "-c", code, str(database)], capture_output=True
            )
            self.assertEqual(result.returncode, 9)
            with closing(db.connect(database)) as conn:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM courses").fetchone()[0], 0)
            self.assertEqual(db.diagnostics(database)["integrity"], "ok")
