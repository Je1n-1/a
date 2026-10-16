"""Leitura da tela Hoje em uma única transação, sem alterar o relógio."""

from sqlite3 import Connection

from . import analytics, catalog, timer


def overview(conn: Connection, *, include_catalog: bool = True) -> dict[str, object]:
    result = {
        "timer": timer.active(conn),
        "recent": timer.recent(conn),
        "summary": analytics.quick_summary(conn),
    }
    if include_catalog:
        result["courses"] = catalog.courses(conn)
        result["subjects"] = catalog.subjects(conn)
        result["review_subject_ids"] = [
            row[0] for row in conn.execute("""SELECT DISTINCT t.subject_id
                FROM topics t JOIN subjects s ON s.id=t.subject_id
                JOIN courses c ON c.id=s.course_id
                WHERE t.needs_review=1 AND s.archived_at IS NULL AND c.archived_at IS NULL
                ORDER BY t.subject_id""")
        ]
    return result
