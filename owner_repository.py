"""SQLite-backed repository for property owner/manager records."""

from __future__ import annotations

import sqlite3
import threading
import uuid
from pathlib import Path

_COLUMNS = [
    "street",
    "postal_code",
    "city",
    "email",
    "phone",
    "iban",
    "bic",
    "bank",
    "tax_number",
]


class OwnerRepository:
    """Stores owner → property mappings in the shared SQLite database."""

    def __init__(self, db_path: str = "data/baulog_queue.db"):
        self.db_path = db_path
        self.lock = threading.Lock()
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        self._migrate_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS owners (
                    id            TEXT PRIMARY KEY,
                    name          TEXT NOT NULL,
                    property_name TEXT NOT NULL,
                    street        TEXT,
                    postal_code   TEXT,
                    city          TEXT,
                    email         TEXT,
                    phone         TEXT,
                    iban          TEXT,
                    bic           TEXT,
                    bank          TEXT,
                    tax_number    TEXT,
                    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_owners_name ON owners(name)"
            )
            conn.commit()

    def _migrate_db(self) -> None:
        """Add any columns that were introduced after the table was first created."""
        with sqlite3.connect(self.db_path) as conn:
            existing = {
                row[1]
                for row in conn.execute("PRAGMA table_info(owners)").fetchall()
            }
            for col in _COLUMNS:
                if col not in existing:
                    conn.execute(f"ALTER TABLE owners ADD COLUMN {col} TEXT")
            conn.commit()

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def add(
        self,
        name: str,
        property_name: str,
        *,
        street: str | None = None,
        postal_code: str | None = None,
        city: str | None = None,
        email: str | None = None,
        phone: str | None = None,
        iban: str | None = None,
        bic: str | None = None,
        bank: str | None = None,
        tax_number: str | None = None,
    ) -> str:
        """Insert a new owner record. Returns the generated ID."""
        owner_id = str(uuid.uuid4())
        with self.lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO owners
                        (id, name, property_name, street, postal_code, city,
                         email, phone, iban, bic, bank, tax_number)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        owner_id, name, property_name,
                        street, postal_code, city,
                        email, phone, iban, bic, bank, tax_number,
                    ),
                )
                conn.commit()
        return owner_id

    def delete(self, owner_id: str) -> bool:
        with self.lock:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute(
                    "DELETE FROM owners WHERE id = ?", (owner_id,)
                )
                conn.commit()
                return cursor.rowcount > 0

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def search(self, query: str) -> list[dict]:
        """Search owners by name, email, or IBAN (case-insensitive substring).

        First tries the full query string. If nothing is found it falls back to
        word-by-word matching so that STT transcription variants (e.g. 'und'
        instead of '&') still resolve correctly.
        """
        results = self._search_like(query)
        if results:
            return results

        # Fallback: search each significant word individually and merge unique hits.
        # Skip short tokens that add noise ('und', 'and', 'the', 'GmbH', 'AG' …).
        _SKIP = {"und", "and", "or", "the", "gmbh", "ag", "kg", "e.v.", "mbh"}
        words = [w for w in query.split() if len(w) > 3 and w.lower() not in _SKIP]
        seen: set[str] = set()
        merged: list[dict] = []
        for word in words:
            for row in self._search_like(word):
                if row["id"] not in seen:
                    seen.add(row["id"])
                    merged.append(row)
        return merged

    def _search_like(self, query: str) -> list[dict]:
        """Raw substring search across name, email, and IBAN."""
        like = f"%{query}%"
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT * FROM owners
                WHERE lower(name)  LIKE lower(?)
                   OR lower(email) LIKE lower(?)
                   OR lower(iban)  LIKE lower(?)
                ORDER BY name
                """,
                (like, like, like),
            ).fetchall()
            return [dict(r) for r in rows]

    def list_all(self) -> list[dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            return [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM owners ORDER BY name"
                ).fetchall()
            ]


owner_repository = OwnerRepository()
