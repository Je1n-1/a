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
    return result
