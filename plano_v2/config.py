from pathlib import Path


ROOT = Path(__file__).resolve().parent
INSTANCE = ROOT / "instance"
DATABASE_PATH = INSTANCE / "plano.db"
CURRICULUM_TEMPLATE_PATH = ROOT / "static" / "downloads" / "modelo_grade_curricular.xlsx"
DEFAULT_SESSION_MINUTES = 50
TIMEZONE = "America/Sao_Paulo"
