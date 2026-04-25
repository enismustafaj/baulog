"""Queue management system for webhook data processing.

Stores webhook payloads in a queue for asynchronous processing by the worker.
Uses SQLite for persistent, reliable queue storage.
"""

import sqlite3
import json
import uuid
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Optional
import threading


class DataStatus(str, Enum):
    """Status of queued data item."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class DataSource(str, Enum):
    """Source of webhook data."""

    EMAIL = "email"
    SLACK = "slack"
    ERP = "erp"


class QueueManager:
    """Manages a SQLite-based queue for webhook data."""

    def __init__(self, db_path: str = "data/baulog_queue.db"):
        """Initialize queue manager.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = db_path
        self.lock = threading.Lock()

        # Ensure directory exists
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        # Initialize database
        self._init_db()

    def _init_db(self):
        """Initialize database schema."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS queue (
                    id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    payload TEXT NOT NULL,
                    assessment TEXT,
                    error_message TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    processed_at TIMESTAMP,
                    retry_count INTEGER DEFAULT 0,
                    metadata TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_status ON queue(status)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_created_at ON queue(created_at)
                """
            )
            conn.commit()

    def enqueue(
        self,
        data: dict,
        source: DataSource,
        metadata: Optional[dict] = None,
    ) -> str:
        """Add item to queue.

        Args:
            data: Webhook payload to store
            source: Data source (email, slack, erp)
            metadata: Optional metadata (sender, channel, etc.)

        Returns:
            Unique item ID
        """
        item_id = str(uuid.uuid4())
        payload_json = json.dumps(data)
        metadata_json = json.dumps(metadata) if metadata else None

        with self.lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO queue (id, source, status, payload, metadata)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (item_id, source.value, DataStatus.PENDING.value, payload_json, metadata_json),
                )
                conn.commit()

        return item_id

    def get_pending_items(self, limit: int = 10) -> list[dict]:
        """Get pending items from queue.

        Args:
            limit: Maximum number of items to retrieve

        Returns:
            List of pending queue items
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            items = conn.execute(
                """
                SELECT * FROM queue
                WHERE status = ?
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (DataStatus.PENDING.value, limit),
            ).fetchall()

            return [dict(row) for row in items]

    def set_processing(self, item_id: str) -> bool:
        """Mark item as being processed.

        Args:
            item_id: Queue item ID

        Returns:
            True if successful, False otherwise
        """
        with self.lock:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute(
                    """
                    UPDATE queue
                    SET status = ?, processed_at = CURRENT_TIMESTAMP
                    WHERE id = ? AND status = ?
                    """,
                    (DataStatus.PROCESSING.value, item_id, DataStatus.PENDING.value),
                )
                conn.commit()
                return cursor.rowcount > 0

    def mark_completed(self, item_id: str, assessment: str) -> bool:
        """Mark item as completed with assessment result.

        Args:
            item_id: Queue item ID
            assessment: Assessment result from agent

        Returns:
            True if successful, False otherwise
        """
        with self.lock:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute(
                    """
                    UPDATE queue
                    SET status = ?, assessment = ?, processed_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (DataStatus.COMPLETED.value, assessment, item_id),
                )
                conn.commit()
                return cursor.rowcount > 0

    def mark_failed(self, item_id: str, error_message: str, retry: bool = True) -> bool:
        """Mark item as failed.

        Args:
            item_id: Queue item ID
            error_message: Error description
            retry: If True, mark as pending for retry; if False, mark as failed

        Returns:
            True if successful, False otherwise
        """
        with self.lock:
            with sqlite3.connect(self.db_path) as conn:
                status = DataStatus.PENDING.value if retry else DataStatus.FAILED.value
                cursor = conn.execute(
                    """
                    UPDATE queue
                    SET status = ?, error_message = ?, retry_count = retry_count + 1
                    WHERE id = ?
                    """,
                    (status, error_message, item_id),
                )
                conn.commit()
                return cursor.rowcount > 0

    def get_item(self, item_id: str) -> Optional[dict]:
        """Get a specific queue item by ID.

        Args:
            item_id: Queue item ID

        Returns:
            Queue item or None if not found
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            item = conn.execute(
                """
                SELECT * FROM queue WHERE id = ?
                """,
                (item_id,),
            ).fetchone()

            return dict(item) if item else None

    def get_completed_items(
        self, limit: int = 100, hours: int = 24
    ) -> list[dict]:
        """Get recently completed items.

        Args:
            limit: Maximum number of items to retrieve
            hours: Only include items from last N hours

        Returns:
            List of completed queue items
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cutoff_time = datetime.now() - timedelta(hours=hours)
            items = conn.execute(
                """
                SELECT * FROM queue
                WHERE status = ? AND created_at > ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (DataStatus.COMPLETED.value, cutoff_time, limit),
            ).fetchall()

            return [dict(row) for row in items]

    def get_failed_items(self, limit: int = 100) -> list[dict]:
        """Get failed items.

        Args:
            limit: Maximum number of items to retrieve

        Returns:
            List of failed queue items
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            items = conn.execute(
                """
                SELECT * FROM queue
                WHERE status = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (DataStatus.FAILED.value, limit),
            ).fetchall()

            return [dict(row) for row in items]

    def get_queue_stats(self) -> dict[str, int]:
        """Get queue statistics.

        Returns:
            Dictionary with counts by status
        """
        with sqlite3.connect(self.db_path) as conn:
            stats = {}
            for status in DataStatus:
                count = conn.execute(
                    """
                    SELECT COUNT(*) FROM queue WHERE status = ?
                    """,
                    (status.value,),
                ).fetchone()[0]
                stats[status.value] = count

            return stats

    def clear_old_items(self, days: int = 30) -> int:
        """Remove completed items older than N days.

        Args:
            days: Number of days to keep

        Returns:
            Number of items removed
        """
        cutoff_time = datetime.now() - timedelta(days=days)

        with self.lock:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute(
                    """
                    DELETE FROM queue
                    WHERE status = ? AND created_at < ?
                    """,
                    (DataStatus.COMPLETED.value, cutoff_time),
                )
                conn.commit()
                return cursor.rowcount


# Global queue manager instance
queue_manager = QueueManager()
