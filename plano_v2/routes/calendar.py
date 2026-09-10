"""Feed iCalendar local para os blocos planejados."""
from datetime import timedelta

from flask import Blueprint, Response, request

from config import TIMEZONE
from database.connection import connect
from services import core
from services.calendar_export import calendar_ics


calendar_api = Blueprint("calendar_api", __name__, url_prefix="/api")


@calendar_api.get("/calendar.ics")
def calendar_feed():
    """Exporta somente blocos ainda ativos, sem criar evento externo algum."""
    try:
        start = request.args.get("start") or core._today()
        end = request.args.get("end") or (core._local_now().date() + timedelta(days=90)).isoformat()
        start_day = core._date(start, "Data inicial")
        end_day = core._date(end, "Data final")
        if end_day < start_day:
            raise core.DomainError("A data final não pode ser anterior à inicial.")
        with connect() as conn:
            blocks = core.planned(conn, start_day.isoformat(), end_day.isoformat())
        payload = calendar_ics(blocks, timezone=TIMEZONE)
        # ``mimetype`` acrescenta charset por conta própria; passar o valor
        # completo nele produz dois charset no cabeçalho em algumas versões do
        # Flask. O tipo completo mantém o feed compatível com calendários.
        response = Response(payload, content_type="text/calendar; charset=utf-8")
        response.headers["Content-Disposition"] = (
            f'attachment; filename="plano-{start_day.isoformat()}-{end_day.isoformat()}.ics"'
        )
        return response
    except core.DomainError as error:
        return {"error": str(error), "code": error.code}, error.status
