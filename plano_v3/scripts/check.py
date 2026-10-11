"""Formatação e verificações locais; migrations aplicadas ficam intocadas."""

import argparse
from pathlib import Path
import subprocess
import sys

import jsbeautifier

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fix", action="store_true")
    args = parser.parse_args()
    commands = [
        [sys.executable, "-m", "ruff", "format", ".", *([] if args.fix else ["--check"])],
        [sys.executable, "-m", "ruff", "check", ".", *(["--fix"] if args.fix else [])],
    ]
    failed = False
    for command in commands:
        failed |= subprocess.run(command, cwd=ROOT).returncode != 0
    options = jsbeautifier.default_options()
    options.indent_size = 2
    options.end_with_newline = True
    for path in sorted((ROOT / "static/js").glob("*.js")):
        source = path.read_text(encoding="utf-8")
        formatted = jsbeautifier.beautify(source, options)
        if source != formatted:
            if args.fix:
                path.write_text(formatted, encoding="utf-8")
            else:
                print(f"Formatação pendente: {path.relative_to(ROOT)}")
                failed = True
        failed |= subprocess.run(["node", "--check", str(path)], cwd=ROOT).returncode != 0
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
