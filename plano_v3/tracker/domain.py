from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import re
import unicodedata

LOCAL_ZONE = ZoneInfo("America/Sao_Paulo")


class DomainError(ValueError):
    def __init__(self, message, status=400, details=None):
        super().__init__(message)
        self.status, self.details = status, details


def now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def clean(value, label, maximum=200, required=False):
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise DomainError(f"{label}: informe um texto.")
    value = value.strip()
    if (required and not value) or len(value) > maximum:
        raise DomainError(
            f"{label}: informe de 1 a {maximum} caracteres."
            if required
            else f"{label}: limite de {maximum} caracteres."
        )
    return value


def key(value):
    text = "".join(
        c for c in unicodedata.normalize("NFKD", value).casefold() if not unicodedata.combining(c)
    )
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def get(conn, table, ident):
    # table é sempre constante definida pelo serviço, nunca entrada HTTP.
    row = conn.execute(f"SELECT * FROM {table} WHERE id=?", (ident,)).fetchone()
    if row is None:
        raise DomainError("Registro não encontrado.", 404)
    return dict(row)
