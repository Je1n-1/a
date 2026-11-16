CREATE TABLE study_routes (
 id INTEGER PRIMARY KEY,
 subject_id INTEGER NOT NULL UNIQUE REFERENCES subjects(id),
 title TEXT NOT NULL,
 description TEXT NOT NULL DEFAULT '',
 content_signature TEXT NOT NULL,
 version INTEGER NOT NULL DEFAULT 1 CHECK(version >= 1),
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL
);
CREATE TABLE study_route_modules (
 id INTEGER PRIMARY KEY,
 route_id INTEGER NOT NULL REFERENCES study_routes(id) ON DELETE CASCADE,
 module_key TEXT NOT NULL,
 title TEXT NOT NULL,
 description TEXT NOT NULL DEFAULT '',
 position INTEGER NOT NULL,
 UNIQUE(route_id,module_key),
 UNIQUE(route_id,position)
);
CREATE TABLE study_route_items (
 id INTEGER PRIMARY KEY,
 module_id INTEGER NOT NULL REFERENCES study_route_modules(id) ON DELETE CASCADE,
 topic_id INTEGER NOT NULL REFERENCES topics(id) ON DELETE RESTRICT,
 item_key TEXT NOT NULL,
 description TEXT NOT NULL DEFAULT '',
 estimated_minutes INTEGER CHECK(estimated_minutes IS NULL OR estimated_minutes BETWEEN 1 AND 600000),
 source_reference TEXT NOT NULL DEFAULT '',
 position INTEGER NOT NULL,
 UNIQUE(module_id,item_key),
 UNIQUE(module_id,position)
);
CREATE INDEX study_route_modules_order ON study_route_modules(route_id,position);
CREATE INDEX study_route_items_order ON study_route_items(module_id,position);
CREATE INDEX study_route_items_topic ON study_route_items(topic_id);
CREATE TABLE study_route_imports (
 operation_key TEXT PRIMARY KEY,
 subject_id INTEGER NOT NULL REFERENCES subjects(id),
 request_signature TEXT NOT NULL,
 route_id INTEGER NOT NULL REFERENCES study_routes(id),
 created_at TEXT NOT NULL
);
