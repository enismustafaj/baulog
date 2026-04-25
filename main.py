import csv
import logging
import os
import threading
import uuid
from contextlib import asynccontextmanager
from io import BytesIO, StringIO
from pathlib import Path
from typing import AsyncIterator

import uvicorn
from fastapi import FastAPI, File, HTTPException, Header, UploadFile
from pydantic import BaseModel
from datetime import datetime
from pypdf import PdfReader
from agents.relevancy_agent import RelevancyAgent
from queue_manager import queue_manager, DataSource
from worker import QueueWorker

logger = logging.getLogger(__name__)
UPLOAD_DIR = Path(os.getenv("BAULOG_UPLOAD_DIR", "data/uploads"))

# Initialize the relevancy agent (optional - not needed for webhooks)
try:
    relevancy_agent = RelevancyAgent()
except ValueError as e:
    print(f"Warning: Relevancy agent not initialized: {e}")
    relevancy_agent = None


def _env_bool(name: str, default: bool = True) -> bool:
    """Read a boolean environment variable."""
    value = os.getenv(name)
    if value is None:
        return default

    return value.strip().lower() not in {"0", "false", "no", "off"}


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Start and stop the queue worker with the API server."""
    worker = None
    worker_thread = None

    if _env_bool("BAULOG_RUN_WORKER", default=True):
        if relevancy_agent is None:
            logger.warning("Queue worker not started because the relevancy agent is not initialized")
        else:
            batch_size = int(os.getenv("BAULOG_WORKER_BATCH_SIZE", "10"))
            poll_interval = int(os.getenv("BAULOG_WORKER_POLL_INTERVAL", "5"))
            worker = QueueWorker(
                batch_size=batch_size,
                poll_interval=poll_interval,
                initialize_agent=False,
                agent=relevancy_agent,
            )
            worker_thread = threading.Thread(
                target=worker.run,
                name="baulog-queue-worker",
                daemon=True,
            )
            app.state.queue_worker = worker
            app.state.queue_worker_thread = worker_thread
            worker_thread.start()
            logger.info("Queue worker started with the API server")
    else:
        logger.info("Queue worker disabled by BAULOG_RUN_WORKER")

    try:
        yield
    finally:
        if worker is not None:
            worker.running = False
            worker.stop_event.set()
        if worker_thread is not None:
            worker_thread.join(timeout=10)
            logger.info("Queue worker stopped")


app = FastAPI(
    title="Baulog",
    description="Baulog API",
    version="0.1.0",
    lifespan=lifespan,
)


class DataInput(BaseModel):
    """Input model for data evaluation."""

    data: str
    data_type: str = "unstructured"  # email, pdf, erp, etc.


class RelevancyResponse(BaseModel):
    """Response model for relevancy evaluation."""

    relevant: bool
    assessment: str
    confidence: str = "MEDIUM"


class WebhookResponse(BaseModel):
    """Response model for webhook enqueue."""

    status: str
    message: str
    data_id: str
    enqueued_at: datetime = None

    def __init__(self, **data):
        if "enqueued_at" not in data or data["enqueued_at"] is None:
            data["enqueued_at"] = datetime.now()
        super().__init__(**data)


class CsvWebhookResponse(BaseModel):
    """Response model for CSV webhook enqueue (one entry per row)."""

    status: str
    message: str
    row_count: int
    data_ids: list[str]
    enqueued_at: datetime = None

    def __init__(self, **data):
        if "enqueued_at" not in data or data["enqueued_at"] is None:
            data["enqueued_at"] = datetime.now()
        super().__init__(**data)


async def _save_upload(file: UploadFile, source: DataSource) -> tuple[str, Path, bytes]:
    """Read, validate, and persist an uploaded file. Returns (upload_id, stored_path, contents)."""
    original_filename = Path(file.filename or "").name
    contents = await file.read()
    if not contents:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    upload_id = str(uuid.uuid4())
    upload_dir = UPLOAD_DIR / source.value
    upload_dir.mkdir(parents=True, exist_ok=True)
    stored_path = upload_dir / f"{upload_id}_{original_filename}"
    stored_path.write_bytes(contents)
    return upload_id, stored_path, contents


@app.get("/")
def read_root():
    """Root endpoint"""
    return {"message": "Welcome to Baulog API"}


@app.get("/health")
def health_check():
    """Health check endpoint"""
    agent_status = "ready" if relevancy_agent else "not_initialized"
    worker = getattr(app.state, "queue_worker", None)
    worker_thread = getattr(app.state, "queue_worker_thread", None)
    worker_status = (
        "running"
        if worker_thread is not None and worker_thread.is_alive()
        else "not_running"
    )
    return {
        "status": "healthy",
        "agent_status": agent_status,
        "worker_status": worker_status,
        "worker_stats": worker.stats if worker else None,
    }


@app.post("/webhooks/invoices/pdf", response_model=WebhookResponse)
async def invoice_pdf_webhook(
    file: UploadFile = File(...),
    x_signature: str | None = Header(None),
    x_secret: str | None = Header(None),
) -> WebhookResponse:
    """Webhook endpoint for receiving invoice PDF uploads.

    Extracts text from the PDF at upload time and enqueues the plain text
    so the worker can pass it directly to the relevancy agent.
    """
    original_filename = Path(file.filename or "").name
    if not original_filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Invalid file type. Expected: .pdf")

    try:
        upload_id, stored_path, contents = await _save_upload(file, DataSource.PDF_INVOICE)

        reader = PdfReader(BytesIO(contents))
        page_texts = []
        for page_num, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            page_texts.append(f"--- Page {page_num} ---\n{text.strip()}")
        extracted_text = "\n\n".join(page_texts).strip() or "[No extractable PDF text found]"

        item_id = queue_manager.enqueue(
            data={
                "text": extracted_text,
                "filename": original_filename,
                "upload_id": upload_id,
                "file_path": str(stored_path),
            },
            source=DataSource.PDF_INVOICE,
            metadata={"document_type": "invoice", "filename": original_filename},
        )

        return WebhookResponse(
            status="enqueued",
            message=f"Invoice PDF {original_filename} text extracted and enqueued",
            data_id=item_id,
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error processing invoice PDF: {str(e)}",
        )


@app.post("/webhooks/csv", response_model=CsvWebhookResponse)
async def csv_webhook(
    file: UploadFile = File(...),
    x_signature: str | None = Header(None),
    x_secret: str | None = Header(None),
) -> CsvWebhookResponse:
    """Webhook endpoint for receiving CSV file uploads.

    Each data row is parsed at upload time and enqueued as a separate queue
    item so the worker processes rows independently via the relevancy agent.
    """
    original_filename = Path(file.filename or "").name
    if not original_filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Invalid file type. Expected: .csv")

    try:
        upload_id, stored_path, contents = await _save_upload(file, DataSource.CSV)

        raw_text = contents.decode("utf-8-sig")
        reader = csv.DictReader(StringIO(raw_text))

        if not reader.fieldnames:
            raise HTTPException(status_code=400, detail="CSV file has no header row")

        data_ids: list[str] = []
        for row_number, row in enumerate(reader, start=1):
            row_text = ", ".join(f"{k}: {v}" for k, v in row.items())
            item_id = queue_manager.enqueue(
                data={
                    "text": row_text,
                    "row_number": row_number,
                    "filename": original_filename,
                    "upload_id": upload_id,
                    "file_path": str(stored_path),
                },
                source=DataSource.CSV,
                metadata={
                    "document_type": "csv",
                    "filename": original_filename,
                    "row_number": row_number,
                },
            )
            data_ids.append(item_id)

        if not data_ids:
            raise HTTPException(status_code=400, detail="CSV file has no data rows")

        return CsvWebhookResponse(
            status="enqueued",
            message=f"CSV file {original_filename} parsed and {len(data_ids)} rows enqueued",
            row_count=len(data_ids),
            data_ids=data_ids,
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error processing CSV file: {str(e)}",
        )


@app.post("/webhooks/email", response_model=WebhookResponse)
async def email_webhook(
    file: UploadFile = File(...),
    x_signature: str | None = Header(None),
    x_secret: str | None = Header(None),
) -> WebhookResponse:
    """Webhook endpoint for receiving .eml email uploads."""
    original_filename = Path(file.filename or "").name
    if not original_filename.lower().endswith(".eml"):
        raise HTTPException(status_code=400, detail="Invalid file type. Expected: .eml")

    try:
        upload_id, stored_path, contents = await _save_upload(file, DataSource.EML)

        item_id = queue_manager.enqueue(
            data={
                "upload_id": upload_id,
                "filename": original_filename,
                "file_path": str(stored_path),
                "content_type": file.content_type,
                "size_bytes": len(contents),
                "uploaded_at": datetime.now().isoformat(),
            },
            source=DataSource.EML,
            metadata={"document_type": "email", "filename": original_filename},
        )

        return WebhookResponse(
            status="enqueued",
            message=f"Email file {original_filename} enqueued for processing",
            data_id=item_id,
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error enqueueing email file: {str(e)}",
        )


# ============================================================================
# Queue Management Endpoints
# ============================================================================


class QueueStats(BaseModel):
    """Queue statistics response."""

    pending: int
    processing: int
    completed: int
    failed: int


class QueueItemResponse(BaseModel):
    """Single queue item response."""

    id: str
    source: str
    status: str
    created_at: str
    assessment: str | None = None
    error_message: str | None = None


@app.get("/queue/status", response_model=QueueStats)
def queue_status() -> QueueStats:
    """Get queue statistics.

    Returns:
        Queue status with counts by state
    """
    stats = queue_manager.get_queue_stats()
    return QueueStats(
        pending=stats.get("pending", 0),
        processing=stats.get("processing", 0),
        completed=stats.get("completed", 0),
        failed=stats.get("failed", 0),
    )


@app.get("/queue/item/{item_id}", response_model=QueueItemResponse)
def get_queue_item(item_id: str) -> QueueItemResponse:
    """Get details of a specific queue item.

    Args:
        item_id: The queue item ID

    Returns:
        Queue item details including assessment if completed

    Raises:
        HTTPException: If item not found
    """
    item = queue_manager.get_item(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Queue item not found")

    return QueueItemResponse(
        id=item["id"],
        source=item["source"],
        status=item["status"],
        created_at=item["created_at"],
        assessment=item["assessment"],
        error_message=item["error_message"],
    )


@app.get("/queue/completed", response_model=list[QueueItemResponse])
def queue_completed(limit: int = 100, hours: int = 24) -> list[QueueItemResponse]:
    """Get recently completed queue items.

    Args:
        limit: Maximum number of items to return
        hours: Only include items from last N hours

    Returns:
        List of completed queue items
    """
    items = queue_manager.get_completed_items(limit=limit, hours=hours)
    return [
        QueueItemResponse(
            id=item["id"],
            source=item["source"],
            status=item["status"],
            created_at=item["created_at"],
            assessment=item["assessment"],
        )
        for item in items
    ]


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
