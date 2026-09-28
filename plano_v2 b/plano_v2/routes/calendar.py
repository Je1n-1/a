"""Feed iCalendar local para os blocos planejados."""
from datetime import timedelta

from flask import Blueprint, Response, jsonify, redirect, request

from config import TIMEZONE
from database.connection import connect
from services import core, google_calendar
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


def _calendar_error(error):
    return jsonify({"error": str(error), "code": error.code}), error.status


@calendar_api.get("/calendar/google/status")
def google_status():
    with connect() as conn:
        return jsonify(google_calendar.status(conn))


@calendar_api.post("/calendar/google/authorize")
def google_authorize():
    try:
        values = request.get_json(silent=True) or {}
        with connect() as conn:
            return jsonify(google_calendar.authorization_url(conn, values.get("calendar_id", "primary")))
    except google_calendar.CalendarIntegrationError as error:
        return _calendar_error(error)


@calendar_api.get("/calendar/google/callback")
def google_callback():
    try:
        if request.args.get("error"):
            raise google_calendar.CalendarIntegrationError(
                "A autorização do Google foi cancelada.", "google_oauth_cancelled", 409,
            )
        with connect() as conn:
            google_calendar.complete_authorization(conn, request.args.get("code"), request.args.get("state"))
        return redirect("/settings/integrations?google=connected", code=303)
    except google_calendar.CalendarIntegrationError as error:
        return redirect(f"/settings/integrations?google=error&code={error.code}", code=303)


@calendar_api.post("/calendar/google/sync")
def google_sync():
    try:
        with connect() as conn:
            return jsonify(google_calendar.sync_pending(conn))
    except google_calendar.CalendarIntegrationError as error:
        return _calendar_error(error)


@calendar_api.post("/calendar/google/disconnect")
def google_disconnect():
    try:
        with connect() as conn:
            return jsonify(google_calendar.disconnect(conn))
    except google_calendar.CalendarIntegrationError as error:
        return _calendar_error(error)
