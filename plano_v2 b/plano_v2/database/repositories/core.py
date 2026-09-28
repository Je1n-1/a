"""Consultas pequenas, sem regra de produto."""
from __future__ import annotations

import sqlite3


def one(conn: sqlite3.Connection, sql: str, params=()):
    row = conn.execute(sql, params).fetchone()
    return dict(row) if row else None


def many(conn: sqlite3.Connection, sql: str, params=()):
    return [dict(row) for row in conn.execute(sql, params).fetchall()]


def insert(conn: sqlite3.Connection, table: str, values: dict):
    columns = list(values)
    cursor = conn.execute(
        f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
        [values[column] for column in columns],
    )
    return cursor.lastrowid


def update(conn: sqlite3.Connection, table: str, ident: int, values: dict):
    if not values:
        return
    columns = list(values)
    conn.execute(
        f"UPDATE {table} SET {', '.join(f'{column}=?' for column in columns)}, updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
        [values[column] for column in columns] + [ident],
    )


def delete(conn: sqlite3.Connection, table: str, ident: int):
    return conn.execute(f"DELETE FROM {table} WHERE id=?", (ident,)).rowcount
