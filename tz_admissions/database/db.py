"""Database connection and query helpers for the admissions app."""

from __future__ import annotations
import re
import sqlite3
from pathlib import Path
from typing import Any, Dict, Iterable

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "admissions.db"
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


def get_connection(db_path: Path = DB_PATH) -> sqlite3.Connection:
    """Return a SQLite connection with row access by column name."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """Initialize database tables from schema.sql."""
    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
    conn.executescript(schema_sql)
    conn.commit()
    migrate_programs_columns(conn)


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {r[1] for r in rows}


def migrate_programs_columns(conn: sqlite3.Connection) -> None:
    """Add guidebook/Gemini columns to programs if missing (existing DBs)."""
    cols = _table_columns(conn, "programs")
    alters: list[tuple[str, str]] = []
    if "program_code" not in cols:
        alters.append(("program_code", "TEXT"))
    if "duration_years" not in cols:
        alters.append(("duration_years", "REAL"))
    if "minimum_points" not in cols:
        alters.append(("minimum_points", "REAL"))
    if "admission_capacity" not in cols:
        alters.append(("admission_capacity", "INTEGER"))
    if "requirements_raw" not in cols:
        alters.append(("requirements_raw", "TEXT"))
    for name, sql_type in alters:
        conn.execute(f"ALTER TABLE programs ADD COLUMN {name} {sql_type}")
    if alters:
        conn.commit()


def count_extracted_programs(conn: sqlite3.Connection, uni_id: int) -> int:
    """Programs with guidebook requirements already loaded for this university."""
    row = conn.execute(
        "SELECT COUNT(*) FROM programs WHERE uni_id = ? AND requirements_raw IS NOT NULL",
        (uni_id,),
    ).fetchone()
    return int(row[0]) if row else 0


def find_uni_id_by_name(conn: sqlite3.Connection, name: str) -> int | None:
    """Resolve uni_id by exact match, then prefix match (PDF vs DB with acronym)."""
    if not name or not str(name).strip():
        return None

    def normalize(s: str) -> str:
        s = s.strip()
        s = re.sub(r'-\s+', '-', s)   # "Al- Sumait" → "Al-Sumait"
        s = re.sub(r'\s+', ' ', s)    # collapse multiple spaces
        return s.lower()

    n = normalize(name)

    row = conn.execute(
        "SELECT uni_id, name FROM universities",
    ).fetchall()

    # Exact normalized match
    for r in row:
        if normalize(r["name"]) == n:
            return int(r["uni_id"])

    # Prefix match — PDF name is prefix of DB name (DB includes acronym)
    for r in row:
        if normalize(r["name"]).startswith(n) and len(n) >= 12:
            return int(r["uni_id"])

    return None


def delete_programs_for_university(conn: sqlite3.Connection, uni_id: int) -> None:
    conn.execute("DELETE FROM programs WHERE uni_id = ?", (uni_id,))
    conn.commit()


def insert_guidebook_programs(
    conn: sqlite3.Connection, uni_id: int, programs: Iterable[Dict[str, Any]]
) -> int:
    """Insert programs from guidebook extraction (keeps legacy columns nullable)."""
    rows = list(programs)
    if not rows:
        return 0
    conn.executemany(
        """
        INSERT INTO programs (
            uni_id, program_name, program_code, duration_years,
            minimum_points, admission_capacity, requirements_raw
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                uni_id,
                p.get("program_name") or "",
                p.get("program_code"),
                p.get("duration_years"),
                p.get("minimum_points"),
                p.get("admission_capacity"),
                p.get("requirements_raw") or p.get("admission_requirements_raw"),
            )
            for p in rows
        ],
    )
    conn.commit()
    return len(rows)


def insert_university_if_missing(conn: sqlite3.Connection, name: str, header: str) -> int:
    """Insert a university from the guidebook if it doesn't exist. Returns uni_id."""
    # Extract location from header e.g. "Water Institute (WI), Dar es Salaam"
    location_match = re.search(r'\([^)]+\),\s*(.+)$', header.strip())
    location = location_match.group(1).strip() if location_match else None

    # Extract acronym
    acronym_match = re.search(r'\(([^)]+)\)', header.strip())
    acronym = acronym_match.group(1).strip() if acronym_match else None

    # Full name with acronym for storage
    full_name = f"{name.strip()} ({acronym})" if acronym else name.strip()

    conn.execute(
        """
        INSERT OR IGNORE INTO universities (name, head_office, type, status)
        VALUES (?, ?, ?, ?)
        """,
        (full_name, location, 'Unknown', 'Guidebook'),
    )
    conn.commit()

    row = conn.execute(
        "SELECT uni_id FROM universities WHERE name = ?",
        (full_name,),
    ).fetchone()

    if row is None:
        raise RuntimeError(f"Failed to insert university: {full_name}")
    return int(row["uni_id"])
