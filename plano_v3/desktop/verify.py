"""Windows launcher integration checks; uses only a newly created temporary database."""
import json
import os
from pathlib import Path
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent.parent
WORK = Path(tempfile.mkdtemp(prefix="plano-launcher-" )).resolve()
ENV = dict(os.environ, PLANO_LAUNCHER_NO_BROWSER="1")
PROCESSES = []


def launch(folder, *args):
    process = subprocess.Popen(
        [str(folder / "Plano.exe"), *args], cwd=folder, env=ENV,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    PROCESSES.append(process)
    return process


def request(port, path, data=None):
    payload = None if data is None else json.dumps(data).encode()
    req = Request(f"http://127.0.0.1:{port}{path}", data=payload,
                  headers={"Content-Type": "application/json"})
    with urlopen(req, timeout=2) as response:
        return json.load(response)


def wait_for(predicate, seconds=30):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        try:
            if predicate():
                return
        except (OSError, ValueError):
            pass
        time.sleep(0.2)
    raise AssertionError("Timed out waiting for launcher state")


def listening(port):
    with socket.socket() as sock:
        sock.settimeout(0.2)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def fixture(name, database, port):
    folder = WORK / name
    folder.mkdir()
    shutil.copy2(ROOT / "Plano.exe", folder / "Plano.exe")
    (folder / "config.local.json").write_text(json.dumps({
        "database_path": str(database), "port": port,
        "python_path": sys.executable,
    }), encoding="utf-8")
    (folder / "app.py").write_text(
        f"import runpy, sys\nsys.path.insert(0, {str(ROOT)!r})\n"
        f"runpy.run_path({str(ROOT / 'app.py')!r}, run_name='__main__')\n",
        encoding="utf-8",
    )
    return folder


def stop(folder, owner, port):
    assert launch(folder, "--stop").wait(timeout=10) == 0
    assert owner.wait(timeout=20) == 0
    wait_for(lambda: not listening(port), 10)


def main():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    database = WORK / "test.db"
    subprocess.run([sys.executable, str(ROOT / "app.py"), "--database",
                    str(database), "--init-db"], check=True,
                   capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
    folder = fixture("installation with spaces", database, port)
    results = {}
    try:
        binary = (folder / "Plano.exe").read_bytes()
        pe = struct.unpack_from("<I", binary, 0x3C)[0]
        assert struct.unpack_from("<H", binary, pe + 24 + 68)[0] == 2
        results["windows_gui_executable"] = True
        owner = launch(folder)
        wait_for(lambda: request(port, "/api/diagnostics")["integrity"] == "ok")
        assert owner.poll() is None
        assert Path(request(port, "/api/diagnostics")["path"]) == database
        results["startup_correct_database"] = True
        saved = request(port, "/api/sessions/manual", {
            "operation_key": "launcher-persistence", "mode": "duration",
            "date": "2026-10-16", "duration_seconds": 600,
            "title": "Launcher persistence test",
        })
        assert launch(folder).wait(timeout=15) == 0
        assert owner.poll() is None
        results["duplicate_launch_reuses_server"] = True
        wrong_database = WORK / "another.db"
        shutil.copy2(database, wrong_database)
        other = fixture("occupied-port", wrong_database, port)
        assert launch(other).wait(timeout=15) == 1
        assert request(port, "/api/diagnostics")["integrity"] == "ok"
        results["occupied_port_preserves_existing_server"] = True
        stop(folder, owner, port)
        results["stop_closes_process_tree_and_port"] = True
        owner = launch(folder)
        wait_for(lambda: request(port, "/api/diagnostics")["integrity"] == "ok")
        assert request(port, f"/api/sessions/{saved['id']}") == saved
        results["restart_preserves_session"] = True
        stop(folder, owner, port)
        missing = WORK / "must-not-be-created.db"
        invalid = fixture("missing-database", missing, port)
        assert launch(invalid).wait(timeout=10) == 1
        assert not missing.exists() and not listening(port)
        results["missing_database_is_not_created"] = True
    finally:
        # Signal only this test installation. Never terminate a personal server.
        launch(folder, "--stop").wait(timeout=10)
        for process in PROCESSES:
            try:
                process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                               capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
        (WORK / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(json.dumps({"artifacts": str(WORK), "checks": results}, indent=2))


if __name__ == "__main__":
    main()
