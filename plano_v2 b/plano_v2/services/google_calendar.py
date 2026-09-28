"""Adaptador unidirecional e idempotente Plano -> Google Calendar.

O banco local é a fonte de verdade. Falhas externas ficam na fila e nunca
desfazem um bloco ou uma sessão. Credenciais OAuth só são persistidas no
Windows, protegidas para o usuário atual pelo DPAPI.
"""
from __future__ import annotations

import base64
import ctypes
from ctypes import wintypes
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
import secrets
from urllib import error as urlerror
from urllib import parse, request

from config import LOCAL_TIMEZONE, TIMEZONE
from database.repositories import core as repo


PROVIDER = "google"
SCOPE = "https://www.googleapis.com/auth/calendar.events"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
API_ROOT = "https://www.googleapis.com/calendar/v3"


class CalendarIntegrationError(ValueError):
    def __init__(self, message, code="calendar_integration_error", status=400):
        super().__init__(message)
        self.code = code
        self.status = status


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _protect(raw: bytes) -> str:
    if os.name != "nt":
        raise CalendarIntegrationError(
            "O armazenamento protegido de credenciais ainda requer Windows; use o ICS neste ambiente.",
            "credential_store_unavailable", 501,
        )
    payload = ctypes.create_string_buffer(raw)
    source = _DataBlob(len(raw), ctypes.cast(payload, ctypes.POINTER(ctypes.c_byte)))
    result = _DataBlob()
    if not ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(source), "Plano Google Calendar", None, None, None, 0,
        ctypes.byref(result),
    ):
        raise CalendarIntegrationError("Não foi possível proteger as credenciais Google.", "credential_store_error", 500)
    try:
        protected = ctypes.string_at(result.pbData, result.cbData)
        return base64.b64encode(protected).decode("ascii")
    finally:
        ctypes.windll.kernel32.LocalFree(result.pbData)


def _unprotect(encoded: str) -> dict:
    if not encoded or os.name != "nt":
        return {}
    raw = base64.b64decode(encoded)
    payload = ctypes.create_string_buffer(raw)
    source = _DataBlob(len(raw), ctypes.cast(payload, ctypes.POINTER(ctypes.c_byte)))
    result = _DataBlob()
    if not ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(source), None, None, None, None, 0, ctypes.byref(result),
    ):
        raise CalendarIntegrationError("Não foi possível abrir as credenciais Google.", "credential_store_error", 500)
    try:
        return json.loads(ctypes.string_at(result.pbData, result.cbData).decode("utf-8"))
    finally:
        ctypes.windll.kernel32.LocalFree(result.pbData)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _configuration() -> dict:
    return {
        "client_id": os.environ.get("PLANO_GOOGLE_CLIENT_ID", "").strip(),
        "client_secret": os.environ.get("PLANO_GOOGLE_CLIENT_SECRET", "").strip(),
        "redirect_uri": os.environ.get(
            "PLANO_GOOGLE_REDIRECT_URI",
            "http://127.0.0.1:5051/api/calendar/google/callback",
        ).strip(),
    }


def _integration(conn) -> dict:
    row = repo.one(conn, "SELECT * FROM calendar_integrations WHERE provider='google'")
    if row:
        return row
    ident = repo.insert(conn, "calendar_integrations", {
        "provider": PROVIDER, "calendar_id": "primary", "status": "disconnected",
    })
    return repo.one(conn, "SELECT * FROM calendar_integrations WHERE id=?", (ident,))


def status(conn) -> dict:
    integration = _integration(conn)
    config = _configuration()
    counts = repo.one(conn, """
        SELECT
          SUM(CASE WHEN sync_status IN ('pending','delete_pending') THEN 1 ELSE 0 END) pending,
          SUM(CASE WHEN sync_status='synced' THEN 1 ELSE 0 END) synced,
          SUM(CASE WHEN sync_status='error' THEN 1 ELSE 0 END) errors
        FROM external_calendar_events WHERE provider='google'
    """) or {}
    oauth_ready = bool(config["client_id"] and config["client_secret"] and os.name == "nt")
    return {
        "provider": PROVIDER,
        "configured": oauth_ready,
        "connected": integration["status"] == "connected" and bool(integration.get("encrypted_credentials")),
        "status": integration["status"],
        "calendar_id": integration["calendar_id"],
        "scope": SCOPE,
        "redirect_uri": config["redirect_uri"],
        "pending": int(counts.get("pending") or 0),
        "synced": int(counts.get("synced") or 0),
        "errors": int(counts.get("errors") or 0),
        "last_sync_at": integration.get("last_sync_at"),
        "last_error": integration.get("last_error"),
        "local_fallback": "/api/calendar.ics",
    }


def authorization_url(conn, calendar_id="primary") -> dict:
    config = _configuration()
    if not config["client_id"] or not config["client_secret"]:
        raise CalendarIntegrationError(
            "Configure PLANO_GOOGLE_CLIENT_ID e PLANO_GOOGLE_CLIENT_SECRET antes de conectar.",
            "google_oauth_not_configured", 409,
        )
    if os.name != "nt":
        raise CalendarIntegrationError("A conexão protegida está disponível nesta versão para Windows.", "credential_store_unavailable", 501)
    state = secrets.token_urlsafe(32)
    state_hash = hashlib.sha256(state.encode()).hexdigest()
    expiry = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(timespec="seconds")
    conn.execute("""
        UPDATE calendar_integrations
        SET calendar_id=?,status='authorizing',oauth_state_hash=?,state_expires_at=?,last_error=NULL,
            version=version+1,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')
        WHERE provider='google'
    """, (str(calendar_id or "primary"), state_hash, expiry))
    query = parse.urlencode({
        "client_id": config["client_id"], "redirect_uri": config["redirect_uri"],
        "response_type": "code", "scope": SCOPE, "access_type": "offline",
        "include_granted_scopes": "true", "prompt": "consent", "state": state,
    })
    return {"authorization_url": f"{AUTH_URL}?{query}", "expires_at": expiry, "scope": SCOPE}


def _post_form(url: str, values: dict) -> dict:
    encoded = parse.urlencode(values).encode("utf-8")
    try:
        with request.urlopen(request.Request(url, data=encoded, method="POST"), timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urlerror.URLError, json.JSONDecodeError) as exc:
        raise CalendarIntegrationError("O Google não concluiu a autorização.", "google_oauth_failed", 502) from exc


def complete_authorization(conn, code: str, state: str) -> dict:
    integration = _integration(conn)
    expected = integration.get("oauth_state_hash")
    expires = integration.get("state_expires_at")
    if not code or not state or not expected or not secrets.compare_digest(hashlib.sha256(state.encode()).hexdigest(), expected):
        raise CalendarIntegrationError("A autorização expirou ou não pertence a esta solicitação.", "google_oauth_state_invalid", 409)
    if not expires or datetime.fromisoformat(expires) < datetime.now(timezone.utc):
        raise CalendarIntegrationError("A autorização expirou. Inicie a conexão novamente.", "google_oauth_state_expired", 409)
    config = _configuration()
    tokens = _post_form(TOKEN_URL, {
        "code": code, "client_id": config["client_id"], "client_secret": config["client_secret"],
        "redirect_uri": config["redirect_uri"], "grant_type": "authorization_code",
    })
    if not tokens.get("access_token"):
        raise CalendarIntegrationError("O Google não retornou um token de acesso.", "google_oauth_failed", 502)
    tokens["expires_at"] = int(datetime.now(timezone.utc).timestamp()) + int(tokens.get("expires_in") or 3600)
    protected = _protect(json.dumps(tokens, separators=(",", ":")).encode("utf-8"))
    conn.execute("""
        UPDATE calendar_integrations SET status='connected',encrypted_credentials=?,granted_scope=?,
          oauth_state_hash=NULL,state_expires_at=NULL,connected_at=?,last_error=NULL,version=version+1,
          updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE provider='google'
    """, (protected, tokens.get("scope") or SCOPE, _now()))
    return status(conn)


def disconnect(conn) -> dict:
    # Revogação remota não é presumida: o app remove imediatamente a credencial
    # protegida local. Eventos já criados permanecem até decisão explícita.
    conn.execute("""
        UPDATE calendar_integrations SET status='disconnected',encrypted_credentials=NULL,
          granted_scope=NULL,oauth_state_hash=NULL,state_expires_at=NULL,last_error=NULL,
          version=version+1,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE provider='google'
    """)
    return status(conn)


def _planned_row(conn, planned_id: int) -> dict | None:
    return repo.one(conn, """
        SELECT p.*,COALESCE(d.name,s.personal_name) subject_name,t.name topic_name
        FROM sessoes_planejadas p
        JOIN materias_estudo s ON s.id=p.study_subject_id
        LEFT JOIN disciplinas_grade d ON d.id=s.curriculum_subject_id
        LEFT JOIN topicos t ON t.id=p.topic_id
        WHERE p.id=?
    """, (planned_id,))


def event_payload(block: dict) -> dict:
    title = f"Estudar: {block.get('subject_name') or 'Disciplina'}"
    description = "Plano de estudo"
    if block.get("topic_name"):
        description += f" — {block['topic_name']}"
    private = {"planoPlannedSessionId": str(block["id"]), "managedBy": "Plano"}
    if block.get("start_time"):
        start = datetime.fromisoformat(f"{block['scheduled_date']}T{block['start_time']}").replace(tzinfo=LOCAL_TIMEZONE)
        end = start + timedelta(minutes=int(block["planned_duration_minutes"]))
        timing = {
            "start": {"dateTime": start.isoformat(timespec="seconds"), "timeZone": TIMEZONE},
            "end": {"dateTime": end.isoformat(timespec="seconds"), "timeZone": TIMEZONE},
        }
    else:
        start_day = datetime.fromisoformat(block["scheduled_date"]).date()
        timing = {"start": {"date": start_day.isoformat()}, "end": {"date": (start_day + timedelta(days=1)).isoformat()}}
    return {"summary": title, "description": description, **timing, "extendedProperties": {"private": private}}


def _hash(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def queue_block(conn, planned_id: int) -> dict | None:
    block = _planned_row(conn, planned_id)
    if not block or block.get("source") != "automatic" or not block.get("plan_run_id"):
        return None
    mapping = repo.one(conn, "SELECT * FROM external_calendar_events WHERE planned_session_id=?", (planned_id,))
    active = block.get("status") == "planned"
    action = "upsert" if active else "delete"
    payload_hash = _hash(event_payload(block)) if active else hashlib.sha256(f"delete:{planned_id}".encode()).hexdigest()
    if action == "delete" and not mapping:
        return None
    if active and mapping and mapping.get("content_hash") == payload_hash and mapping.get("sync_status") == "synced":
        return None
    if not active and mapping and mapping.get("sync_status") == "deleted":
        return None
    if mapping:
        conn.execute("""
            UPDATE external_calendar_events SET content_hash=?,sync_status=?,last_error=NULL,
              updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?
        """, (payload_hash, "pending" if active else "delete_pending", mapping["id"]))
    else:
        repo.insert(conn, "external_calendar_events", {
            "provider": PROVIDER, "planned_session_id": planned_id, "content_hash": payload_hash,
            "sync_status": "pending",
        })
    key = f"google:{planned_id}:{action}:{payload_hash}"
    existing = repo.one(conn, "SELECT * FROM calendar_sync_queue WHERE idempotency_key=?", (key,))
    if not existing:
        ident = repo.insert(conn, "calendar_sync_queue", {
            "provider": PROVIDER, "planned_session_id": planned_id, "action": action,
            "content_hash": payload_hash, "status": "pending", "idempotency_key": key,
        })
        existing = repo.one(conn, "SELECT * FROM calendar_sync_queue WHERE id=?", (ident,))
    return existing


def reconcile(conn) -> dict:
    integration = _integration(conn)
    if integration["status"] != "connected":
        return {"queued": 0, "connected": False}
    active_ids = [row["id"] for row in repo.many(conn, """
        SELECT id FROM sessoes_planejadas
        WHERE source='automatic' AND plan_run_id IS NOT NULL AND status='planned'
    """)]
    managed_ids = [row["planned_session_id"] for row in repo.many(conn, "SELECT planned_session_id FROM external_calendar_events WHERE provider='google' AND sync_status!='deleted'")]
    queued = 0
    for planned_id in sorted(set(active_ids + managed_ids)):
        if queue_block(conn, planned_id):
            queued += 1
    return {"queued": queued, "connected": True}


class GoogleTransport:
    def __init__(self, conn):
        self.conn = conn
        self.integration = _integration(conn)
        self.credentials = _unprotect(self.integration.get("encrypted_credentials"))

    def _access_token(self) -> str:
        expires = int(self.credentials.get("expires_at") or 0)
        if self.credentials.get("access_token") and expires > int(datetime.now(timezone.utc).timestamp()) + 60:
            return self.credentials["access_token"]
        refresh = self.credentials.get("refresh_token")
        config = _configuration()
        if not refresh:
            raise CalendarIntegrationError("Reconecte o Google Agenda para renovar a autorização.", "google_reauthorization_required", 409)
        refreshed = _post_form(TOKEN_URL, {
            "client_id": config["client_id"], "client_secret": config["client_secret"],
            "refresh_token": refresh, "grant_type": "refresh_token",
        })
        self.credentials.update(refreshed)
        self.credentials["refresh_token"] = refresh
        self.credentials["expires_at"] = int(datetime.now(timezone.utc).timestamp()) + int(refreshed.get("expires_in") or 3600)
        conn_blob = _protect(json.dumps(self.credentials, separators=(",", ":")).encode("utf-8"))
        self.conn.execute("UPDATE calendar_integrations SET encrypted_credentials=?,version=version+1,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE provider='google'", (conn_blob,))
        return self.credentials["access_token"]

    def _call(self, method: str, path: str, payload=None):
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = request.Request(f"{API_ROOT}{path}", data=data, method=method, headers={
            "Authorization": f"Bearer {self._access_token()}", "Content-Type": "application/json",
        })
        try:
            with request.urlopen(req, timeout=20) as response:
                raw = response.read()
                return json.loads(raw.decode("utf-8")) if raw else {}
        except urlerror.HTTPError as exc:
            if method == "DELETE" and exc.code == 410:
                return {}
            raise CalendarIntegrationError("O Google Agenda recusou a sincronização.", "google_sync_failed", 502) from exc
        except (urlerror.URLError, json.JSONDecodeError) as exc:
            raise CalendarIntegrationError("Não foi possível acessar o Google Agenda.", "google_sync_failed", 502) from exc

    def upsert(self, calendar_id: str, external_id: str | None, payload: dict) -> dict:
        calendar = parse.quote(calendar_id, safe="")
        if external_id:
            return self._call("PUT", f"/calendars/{calendar}/events/{parse.quote(external_id, safe='')}", payload)
        return self._call("POST", f"/calendars/{calendar}/events", payload)

    def delete(self, calendar_id: str, external_id: str):
        calendar = parse.quote(calendar_id, safe="")
        return self._call("DELETE", f"/calendars/{calendar}/events/{parse.quote(external_id, safe='')}")


def sync_pending(conn, transport=None, limit=50) -> dict:
    integration = _integration(conn)
    if integration["status"] != "connected":
        raise CalendarIntegrationError("Conecte o Google Agenda antes de sincronizar.", "google_not_connected", 409)
    reconcile(conn)
    client = transport or GoogleTransport(conn)
    rows = repo.many(conn, """
        SELECT * FROM calendar_sync_queue
        WHERE provider='google' AND status IN ('pending','error')
          AND (next_attempt_at IS NULL OR next_attempt_at<=?)
        ORDER BY id LIMIT ?
    """, (_now(), int(limit)))
    result = {"processed": 0, "synced": 0, "deleted": 0, "errors": 0}
    for item in rows:
        mapping = repo.one(conn, "SELECT * FROM external_calendar_events WHERE planned_session_id=?", (item["planned_session_id"],))
        block = _planned_row(conn, item["planned_session_id"])
        conn.execute("UPDATE calendar_sync_queue SET status='processing',attempts=attempts+1,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?", (item["id"],))
        result["processed"] += 1
        try:
            if item["action"] == "delete":
                if mapping and mapping.get("external_event_id"):
                    client.delete(integration["calendar_id"], mapping["external_event_id"])
                conn.execute("UPDATE external_calendar_events SET sync_status='deleted',last_error=NULL,last_synced_at=?,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE planned_session_id=?", (_now(), item["planned_session_id"]))
                result["deleted"] += 1
            else:
                if not block or block.get("status") != "planned":
                    queue_block(conn, item["planned_session_id"])
                    conn.execute("UPDATE calendar_sync_queue SET status='done',updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?", (item["id"],))
                    continue
                remote = client.upsert(integration["calendar_id"], mapping.get("external_event_id") if mapping else None, event_payload(block))
                conn.execute("""
                    UPDATE external_calendar_events SET external_event_id=?,external_etag=?,content_hash=?,
                      sync_status='synced',last_error=NULL,last_synced_at=?,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')
                    WHERE planned_session_id=?
                """, (remote.get("id") or mapping.get("external_event_id"), remote.get("etag"), item["content_hash"], _now(), item["planned_session_id"]))
                result["synced"] += 1
            conn.execute("UPDATE calendar_sync_queue SET status='done',last_error=NULL,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?", (item["id"],))
        except CalendarIntegrationError as exc:
            retry_at = (datetime.now(timezone.utc) + timedelta(minutes=min(60, 2 ** min(6, int(item["attempts"]) + 1)))).isoformat(timespec="seconds")
            conn.execute("UPDATE calendar_sync_queue SET status='error',last_error=?,next_attempt_at=?,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?", (str(exc), retry_at, item["id"]))
            conn.execute("UPDATE external_calendar_events SET sync_status='error',last_error=?,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE planned_session_id=?", (str(exc), item["planned_session_id"]))
            result["errors"] += 1
    conn.execute("UPDATE calendar_integrations SET last_sync_at=?,last_error=?,version=version+1,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE provider='google'", (_now(), None if not result["errors"] else "Há itens pendentes para nova tentativa."))
    result["status"] = status(conn)
    return result
