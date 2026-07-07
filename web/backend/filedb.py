"""Baza SQLite pamiętająca ostatnie ID API użyte dla danego pliku (dopasowanie po nazwie).

Cel: przy kolejnym uploadzie pliku o tej samej nazwie podsunąć ID z poprzedniego renderu,
bez ręcznego wpisywania go znowu. Zakres per-sid (`DATA_DIR/<sid>/file_ids.db`) — tak jak
katalogi zadań — żeby nazwa pliku jednego użytkownika nie podsuwała ID innemu. Zapis dopiero
po kliknięciu „Renderuj" (`api.start_render`): same przymiarki (fetch/analyze) nie zaśmiecają
bazy błędnymi ID. Klucz = nazwa pliku (PRIMARY KEY), więc `INSERT OR REPLACE` naturalnie
trzyma tylko najnowszy wpis, gdy ktoś się pomyli i poda inne ID dla tego samego pliku.
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS file_ids ("
        " filename TEXT PRIMARY KEY, result_id INTEGER NOT NULL, updated_at REAL NOT NULL"
        ")")
    return conn


def remember(db_path: Path, filename: str, result_id: int) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO file_ids (filename, result_id, updated_at) "
            "VALUES (?, ?, ?)",
            (filename, result_id, time.time()))


def lookup(db_path: Path, filename: str) -> int | None:
    if not db_path.exists():
        return None
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT result_id FROM file_ids WHERE filename = ?", (filename,)).fetchone()
    return row[0] if row else None
