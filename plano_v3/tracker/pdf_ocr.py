"""OCR local do Windows, executado somente em PDFs que precisam dele."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading

MAX_OCR_PAGES = 12
_worker = threading.BoundedSemaphore(1)


def lines_from_words(words: list[dict]) -> list[str]:
    """Reconstrói linhas pela altura, unindo nome e carga em colunas separadas."""
    rows = []
    for word in sorted(words, key=lambda w: w["y"] + w["height"] / 2):
        center = word["y"] + word["height"] / 2
        if not rows or abs(center - rows[-1][0]) > max(5, word["height"] * 0.5):
            rows.append((center, []))
        rows[-1][1].append(word)
    return [" ".join(w["text"] for w in sorted(row, key=lambda w: w["x"])) for _, row in rows]


def extract(content: bytes) -> str:
    if os.name != "nt":
        raise ValueError(
            "Este PDF precisa de OCR. A leitura local de imagens requer Windows com OCR em português."
        )
    executable = (
        Path(os.environ.get("SystemRoot", r"C:\Windows"))
        / "System32/WindowsPowerShell/v1.0/powershell.exe"
    )
    if not _worker.acquire(blocking=False):
        raise ValueError(
            "Outra grade está sendo lida por OCR. Aguarde alguns segundos e tente novamente."
        )
    try:
        with tempfile.TemporaryDirectory(prefix="plano-ocr-") as directory:
            path = Path(directory) / "grade.pdf"
            path.write_bytes(content)
            try:
                result = subprocess.run(
                    [
                        str(executable),
                        "-NoProfile",
                        "-NonInteractive",
                        "-ExecutionPolicy",
                        "Bypass",
                        "-File",
                        str(Path(__file__).with_suffix(".ps1")),
                        "-PdfPath",
                        str(path),
                    ],
                    capture_output=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=90,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            except subprocess.TimeoutExpired as error:
                raise ValueError(
                    "A leitura por OCR excedeu 90 segundos. Divida o PDF em arquivos menores."
                ) from error
            except OSError as error:
                raise ValueError("Não foi possível iniciar o OCR local do Windows.") from error
        if result.returncode:
            if "OCR_PAGE_LIMIT" in result.stderr:
                raise ValueError(
                    "O OCR aceita PDFs de até 12 páginas. Divida o arquivo para continuar."
                )
            if "OCR_PORTUGUESE_UNAVAILABLE" in result.stderr:
                raise ValueError(
                    "Instale o recurso de reconhecimento de texto em português do Windows para ler este PDF."
                )
            raise ValueError(
                "Não foi possível reconhecer este PDF por OCR. Confira se ele está íntegro e sem senha."
            )
        try:
            data = json.loads(result.stdout.lstrip("\ufeff"))
            text = "\n".join("\n".join(lines_from_words(page["words"])) for page in data["pages"])
        except (ValueError, KeyError, TypeError) as error:
            raise ValueError(
                "O OCR retornou um resultado inválido. Tente ler a grade novamente."
            ) from error
        if not text.strip():
            raise ValueError(
                "O PDF não contém texto legível, mesmo após OCR. Use uma imagem mais nítida ou uma planilha."
            )
        return text
    finally:
        _worker.release()
