from pathlib import Path


ROOT = Path(__file__).resolve().parent
INSTANCE = ROOT / "instance"
DATABASE_PATH = INSTANCE / "plano.db"
DEFAULT_SESSION_MINUTES = 50
TIMEZONE = "America/Sao_Paulo"
