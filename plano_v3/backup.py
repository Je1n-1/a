"""Cópia consistente explícita, sem restauração ou sobrescrita de arquivos."""

import argparse
from pathlib import Path
from tracker.storage import create_backup

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backup local V3, por ação explícita")
    parser.add_argument("--database", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    source, target = Path(args.database).resolve(), Path(args.output).resolve()
    if source == target or target.exists():
        parser.error("Escolha um destino novo; nenhum arquivo será sobrescrito.")
    create_backup(source, target)
    print("Backup íntegro:", target)
