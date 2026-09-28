-- Sincronização unidirecional e idempotente Plano -> Google Calendar.
-- O calendário local continua funcional e nenhuma credencial é obrigatória.

CREATE TABLE calendar_integrations (
 id INTEGER PRIMARY KEY,
 provider TEXT NOT NULL UNIQUE CHECK(provider IN ('google')),
 calendar_id TEXT NOT NULL DEFAULT 'primary',
 status TEXT NOT NULL DEFAULT 'disconnected'
   CHECK(status IN ('disconnected','authorizing','connected','error')),
 encrypted_credentials TEXT,
 granted_scope TEXT,
 oauth_state_hash TEXT,
 state_expires_at TEXT,
 connected_at TEXT,
 last_sync_at TEXT,
 last_error TEXT,
 version INTEGER NOT NULL DEFAULT 1 CHECK(version > 0),
 created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
 updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE external_calendar_events (
 id INTEGER PRIMARY KEY,
 provider TEXT NOT NULL DEFAULT 'google' CHECK(provider IN ('google')),
 planned_session_id INTEGER NOT NULL UNIQUE
   REFERENCES sessoes_planejadas(id) ON DELETE RESTRICT,
 external_event_id TEXT,
 external_etag TEXT,
 content_hash TEXT NOT NULL,
 sync_status TEXT NOT NULL DEFAULT 'pending'
   CHECK(sync_status IN ('pending','synced','error','delete_pending','deleted')),
 last_error TEXT,
 last_synced_at TEXT,
 created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
 updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX idx_external_calendar_status
  ON external_calendar_events(provider,sync_status,planned_session_id);

CREATE TABLE calendar_sync_queue (
 id INTEGER PRIMARY KEY,
 provider TEXT NOT NULL DEFAULT 'google' CHECK(provider IN ('google')),
 planned_session_id INTEGER NOT NULL
   REFERENCES sessoes_planejadas(id) ON DELETE RESTRICT,
 action TEXT NOT NULL CHECK(action IN ('upsert','delete')),
 content_hash TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'pending'
   CHECK(status IN ('pending','processing','done','error')),
 attempts INTEGER NOT NULL DEFAULT 0 CHECK(attempts >= 0),
 next_attempt_at TEXT,
 last_error TEXT,
 idempotency_key TEXT NOT NULL UNIQUE,
 created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
 updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX idx_calendar_queue_pending
  ON calendar_sync_queue(provider,status,next_attempt_at,id);

INSERT OR IGNORE INTO calendar_integrations(provider,calendar_id,status)
VALUES ('google','primary','disconnected');
