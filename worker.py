"""Worker process for processing queued webhook data.

This module runs continuously, fetching items from the queue and running
them through the relevancy agent's agentic workflow.

Usage:
    python worker.py
"""

import json
import argparse
from email import policy
from email.parser import BytesParser
import logging
import signal
import time
import threading
from pathlib import Path

from queue_manager import QueueManager, DataSource


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class QueueWorker:
    """Worker that processes items from the queue."""

    def __init__(
        self,
        batch_size: int = 10,
        poll_interval: int = 5,
        initialize_agent: bool = True,
        agent=None,
    ):
        self.batch_size = batch_size
        self.poll_interval = poll_interval
        self.queue_manager = QueueManager()
        self.stop_event = threading.Event()

        if agent is not None:
            self.agent = agent
            logger.info("✓ Reusing existing relevancy agent")
        elif initialize_agent:
            try:
                from agents.relevancy_agent import RelevancyAgent
                self.agent = RelevancyAgent()
                logger.info("✓ Relevancy agent initialized")
            except ValueError as e:
                logger.error(f"✗ Failed to initialize relevancy agent: {e}")
                self.agent = None
        else:
            self.agent = None

        try:
            from agents.content_agent import ContentAgent
            self.content_agent = ContentAgent()
            logger.info("✓ Content agent initialized")
        except ValueError as e:
            logger.error(f"✗ Failed to initialize content agent: {e}")
            self.content_agent = None

        self.running = True
        self.stats = {
            "processed": 0,
            "completed": 0,
            "failed": 0,
            "errors": 0,
            "skipped": 0,
        }

    def format_webhook_data(self, source: str, payload: dict) -> str:
        """Convert webhook data to text for agent evaluation.

        Args:
            source: Data source (email, slack, erp)
            payload: Raw webhook payload

        Returns:
            Formatted text for agent
        """
        try:
            if source == DataSource.PDF_INVOICE.value:
                return self.parse_pdf_invoice_upload(payload)

            elif source == DataSource.CSV.value:
                return self.parse_csv_upload(payload)

            elif source == DataSource.EML.value:
                return self.parse_eml_upload(payload)

            else:
                logger.warning(f"Unknown source: {source}")
                return json.dumps(payload)

        except Exception as e:
            logger.error(f"Error formatting webhook data: {e}")
            return json.dumps(payload)

    def parse_pdf_invoice_upload(self, payload: dict) -> str:
        """Return pre-extracted PDF text from the queue payload."""
        return payload["text"]

    def parse_csv_upload(self, payload: dict) -> str:
        """Return pre-extracted CSV row text from the queue payload."""
        return payload["text"]

    def parse_eml_upload(self, payload: dict) -> str:
        """Parse an uploaded .eml file into plain text for the agent."""
        file_path = Path(payload["file_path"])
        if not file_path.exists():
            raise FileNotFoundError(f"EML file not found: {file_path}")

        message = BytesParser(policy=policy.default).parsebytes(file_path.read_bytes())
        body = message.get_body(preferencelist=("plain", "html"))
        body_text = body.get_content() if body else ""
        attachments = [
            part.get_filename()
            for part in message.iter_attachments()
            if part.get_filename()
        ]

        return "\n".join(
            [
                f"From: {message.get('from', 'Unknown')}",
                f"To: {message.get('to', 'Unknown')}",
                f"Subject: {message.get('subject', '')}",
                f"Date: {message.get('date', '')}",
                f"Attachments: {', '.join(attachments) if attachments else 'None'}",
                "",
                body_text.strip(),
            ]
        )

    def _apply_to_markdown(self, item_id: str, assessment: dict) -> None:
        """Call the content agent to write the assessment back into the markdown file.

        Failures here are logged but do not cause the queue item to be retried —
        the relevancy assessment already succeeded and is stored in the DB.
        """
        if not self.content_agent:
            logger.warning("Content agent not available — skipping markdown update for %s", item_id)
            return

        property_name = assessment.get("property") or ""
        category = assessment.get("category") or ""

        if not property_name or not category:
            logger.warning(
                "Skipping markdown update for %s — assessment missing property or category", item_id
            )
            return

        try:
            update = self.content_agent.adjust(assessment)
            logger.info(
                "Markdown updated for %s: section=%r  chars_before=%d  chars_after=%d",
                item_id,
                update.get("section_path"),
                len(update.get("original_content") or ""),
                len(update.get("adjusted_content") or ""),
            )
        except ValueError as e:
            # Section not found in the markdown — assessment is still valid
            logger.warning("Could not update markdown for %s: %s", item_id, e)
        except Exception as e:
            logger.error("Unexpected error updating markdown for %s: %s", item_id, e)

    def process_item(self, item: dict) -> bool:
        """Process a single queue item.

        Args:
            item: Queue item from database

        Returns:
            True if processing was successful, False otherwise
        """
        item_id = item["id"]
        source = item["source"]

        try:
            if not self.agent:
                raise ValueError("Agent not initialized")

            # Atomically claim the item so multiple worker processes can run safely.
            if not self.queue_manager.set_processing(item_id):
                logger.info(f"Skipping already-claimed item: {item_id}")
                self.stats["skipped"] += 1
                return False

            # Parse payload
            payload = json.loads(item["payload"])
            text_to_evaluate = self.format_webhook_data(source, payload)

            logger.info(f"Processing {source} item: {item_id}")
            logger.debug(
                "Sending to relevancy agent [%s chars]:\n%s",
                len(text_to_evaluate),
                text_to_evaluate[:500] + (" ..." if len(text_to_evaluate) > 500 else ""),
            )

            # Step 1 — relevancy agent: classify the document
            result = self.agent.evaluate(text_to_evaluate)
            assessment = result["assessment"]

            logger.info(
                "Relevancy assessment for %s: property=%r  building=%r  unit=%r  category=%r  action=%r",
                item_id,
                assessment.get("property"),
                assessment.get("building"),
                assessment.get("unit"),
                assessment.get("category"),
                assessment.get("action"),
            )

            # Step 2 — content agent: apply the assessment to the markdown file
            self._apply_to_markdown(item_id, assessment)

            # Mark as completed
            self.queue_manager.mark_completed(item_id, json.dumps(assessment))

            logger.info(f"✓ Completed: {item_id}")
            self.stats["completed"] += 1

            return True

        except Exception as e:
            logger.error(f"✗ Error processing {item_id}: {e}")
            self.queue_manager.mark_failed(item_id, str(e), retry=True)
            self.stats["errors"] += 1
            return False

    def process_batch(self) -> int:
        """Process a batch of pending items.

        Returns:
            Number of items processed
        """
        items = self.queue_manager.get_pending_items(limit=self.batch_size)

        if not items:
            return 0

        logger.info(f"Processing batch of {len(items)} items...")

        processed = 0
        for item in items:
            if self.process_item(item):
                processed += 1
            self.stats["processed"] += 1

        return processed

    def print_stats(self):
        """Print worker statistics."""
        queue_stats = self.queue_manager.get_queue_stats()
        logger.info(f"Queue Stats: {queue_stats}")
        logger.info(f"Worker Stats: {self.stats}")

    def run_once(self) -> int:
        """Run a single scheduled processing tick.

        Returns:
            Number of items successfully processed
        """
        if not self.agent:
            logger.error("Cannot process queue: agent not initialized")
            return 0

        processed = self.process_batch()

        if processed > 0:
            logger.info(f"Batch complete. Processed {processed} items.")
            self.print_stats()

        return processed

    def run(self):
        """Run worker on a periodic schedule until stopped."""
        if not self.agent:
            logger.error("Cannot start worker: agent not initialized")
            return

        logger.info(
            "Starting worker scheduler "
            f"(batch_size={self.batch_size}, interval={self.poll_interval}s)"
        )
        logger.info("Press Ctrl+C to stop")

        try:
            next_run = time.monotonic()
            while self.running and not self.stop_event.is_set():
                now = time.monotonic()
                wait_seconds = max(0, next_run - now)
                if self.stop_event.wait(wait_seconds):
                    break

                started_at = time.monotonic()
                self.run_once()
                next_run = max(next_run + self.poll_interval, started_at + self.poll_interval)

        except KeyboardInterrupt:
            logger.info("Stopping worker...")
            self.running = False
        except Exception as e:
            logger.error(f"Worker error: {e}")
            self.running = False

        self.print_stats()
        logger.info("Worker stopped")

    def signal_handler(self, sig, frame):
        """Handle shutdown signals."""
        logger.info("Received shutdown signal")
        self.running = False
        self.stop_event.set()


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Process pending Baulog queue items on a periodic schedule."
    )
    parser.add_argument(
        "--items",
        "--batch-size",
        type=int,
        default=10,
        dest="batch_size",
        help="Number of pending queue items to process per scheduled run.",
    )
    parser.add_argument(
        "--poll-interval",
        "--interval",
        type=int,
        default=5,
        dest="poll_interval",
        help="Seconds between scheduled queue checks.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Process one batch of pending items, then exit.",
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="Print queue statistics, then exit.",
    )
    parser.add_argument(
        "--show-pending",
        action="store_true",
        help="Print pending queue items, then exit.",
    )
    parser.add_argument(
        "--show-completed",
        type=int,
        metavar="LIMIT",
        help="Print recently completed queue items, then exit.",
    )
    return parser.parse_args()


def print_items(items: list[dict]) -> None:
    """Print queue items in a compact CLI-friendly format."""
    if not items:
        print("No queue items found.")
        return

    for item in items:
        created_at = item.get("created_at", "")
        source = item.get("source", "")
        status = item.get("status", "")
        retries = item.get("retry_count", 0)
        print(f"{item['id']} | {source} | {status} | retries={retries} | {created_at}")


if __name__ == "__main__":
    args = parse_args()
    needs_agent = not (args.stats or args.show_pending or args.show_completed is not None)
    worker = QueueWorker(
        batch_size=args.batch_size,
        poll_interval=args.poll_interval,
        initialize_agent=needs_agent,
    )

    # Handle graceful shutdown
    signal.signal(signal.SIGINT, worker.signal_handler)
    signal.signal(signal.SIGTERM, worker.signal_handler)

    if args.stats:
        worker.print_stats()
    elif args.show_pending:
        print_items(worker.queue_manager.get_pending_items(limit=args.batch_size))
    elif args.show_completed is not None:
        print_items(worker.queue_manager.get_completed_items(limit=args.show_completed))
    elif args.once:
        worker.run_once()
        worker.print_stats()
    else:
        worker.run()
