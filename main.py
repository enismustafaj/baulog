from __future__ import annotations

import csv
import logging
import os
import sqlite3
import threading
import uuid
from contextlib import asynccontextmanager
from io import BytesIO, StringIO
from pathlib import Path
from typing import AsyncIterator

import uvicorn
from fastapi import FastAPI, File, HTTPException, UploadFile
from pydantic import BaseModel
from datetime import datetime
from pypdf import PdfReader
from agents.config import ADJUSTMENTS_DB
from agents.relevancy_agent import RelevancyAgent
from agents.query_agent import QueryAgent
from queue_manager import queue_manager, DataSource
from worker import QueueWorker

logger = logging.getLogger(__name__)
_EML_UPLOAD_DIR = Path("data/uploads/eml")

# Initialize the relevancy agent
try:
    relevancy_agent = RelevancyAgent()
except ValueError as e:
    print(f"Warning: Relevancy agent not initialized: {e}")
    relevancy_agent = None

# Initialize the query agent for the /query endpoint
try:
    query_agent = QueryAgent()
except ValueError as e:
    print(f"Warning: Query agent not initialized: {e}")
    query_agent = None


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


class UploadResponse(BaseModel):
    """Response model for a single-file upload."""

    status: str
    message: str
    data_id: str
    enqueued_at: datetime = None

    def __init__(self, **data):
        if "enqueued_at" not in data or data["enqueued_at"] is None:
            data["enqueued_at"] = datetime.now()
        super().__init__(**data)


class CsvUploadResponse(BaseModel):
    """Response model for CSV upload (one queue entry per row)."""

    status: str
    message: str
    row_count: int
    data_ids: list[str]
    enqueued_at: datetime = None

    def __init__(self, **data):
        if "enqueued_at" not in data or data["enqueued_at"] is None:
            data["enqueued_at"] = datetime.now()
        super().__init__(**data)


async def _save_eml(filename: str, contents: bytes) -> tuple[str, Path]:
    """Persist an EML file to disk for later worker processing. Returns (upload_id, stored_path)."""
    upload_id = str(uuid.uuid4())
    _EML_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    stored_path = _EML_UPLOAD_DIR / f"{upload_id}_{filename}"
    stored_path.write_bytes(contents)
    return upload_id, stored_path


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
        "query_agent_status": "ready" if query_agent else "not_initialized",
        "worker_status": worker_status,
        "worker_stats": worker.stats if worker else None,
    }


@app.post("/upload/pdf", response_model=UploadResponse)
async def upload_pdf(file: UploadFile = File(...)) -> UploadResponse:
    """Accept a PDF file, extract its text, and enqueue it for processing."""
    original_filename = Path(file.filename or "").name
    if not original_filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Invalid file type. Expected: .pdf")

    try:
        contents = await file.read()
        if not contents:
            raise HTTPException(status_code=400, detail="Uploaded file is empty")

        reader = PdfReader(BytesIO(contents))
        page_texts = []
        for page_num, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            page_texts.append(f"--- Page {page_num} ---\n{text.strip()}")
        extracted_text = "\n\n".join(page_texts).strip() or "[No extractable PDF text found]"

        item_id = queue_manager.enqueue(
            data={"text": extracted_text, "filename": original_filename},
            source=DataSource.PDF_INVOICE,
            metadata={"document_type": "invoice", "filename": original_filename},
        )

        return UploadResponse(
            status="enqueued",
            message=f"{original_filename} text extracted and enqueued",
            data_id=item_id,
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing PDF: {str(e)}")


@app.post("/upload/csv", response_model=CsvUploadResponse)
async def upload_csv(file: UploadFile = File(...)) -> CsvUploadResponse:
    """Accept a CSV file and enqueue each data row as a separate queue item."""
    original_filename = Path(file.filename or "").name
    if not original_filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Invalid file type. Expected: .csv")

    try:
        contents = await file.read()
        if not contents:
            raise HTTPException(status_code=400, detail="Uploaded file is empty")

        reader = csv.DictReader(StringIO(contents.decode("utf-8-sig")))

        if not reader.fieldnames:
            raise HTTPException(status_code=400, detail="CSV file has no header row")

        data_ids: list[str] = []
        for row_number, row in enumerate(reader, start=1):
            row_text = ", ".join(f"{k}: {v}" for k, v in row.items())
            item_id = queue_manager.enqueue(
                data={"text": row_text, "row_number": row_number, "filename": original_filename},
                source=DataSource.CSV,
                metadata={"document_type": "csv", "filename": original_filename, "row_number": row_number},
            )
            data_ids.append(item_id)

        if not data_ids:
            raise HTTPException(status_code=400, detail="CSV file has no data rows")

        return CsvUploadResponse(
            status="enqueued",
            message=f"{original_filename} parsed and {len(data_ids)} rows enqueued",
            row_count=len(data_ids),
            data_ids=data_ids,
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing CSV: {str(e)}")


@app.post("/upload/eml", response_model=UploadResponse)
async def upload_eml(file: UploadFile = File(...)) -> UploadResponse:
    """Accept an .eml file and enqueue it for processing."""
    original_filename = Path(file.filename or "").name
    if not original_filename.lower().endswith(".eml"):
        raise HTTPException(status_code=400, detail="Invalid file type. Expected: .eml")

    try:
        contents = await file.read()
        if not contents:
            raise HTTPException(status_code=400, detail="Uploaded file is empty")

        upload_id, stored_path = await _save_eml(original_filename, contents)

        item_id = queue_manager.enqueue(
            data={"filename": original_filename, "file_path": str(stored_path)},
            source=DataSource.EML,
            metadata={"document_type": "email", "filename": original_filename},
        )

        return UploadResponse(
            status="enqueued",
            message=f"{original_filename} enqueued for processing",
            data_id=item_id,
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing EML: {str(e)}")


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


# ============================================================================
# Query Endpoint
# ============================================================================


class QueryRequest(BaseModel):
    """Request body for the /query endpoint."""

    prompt: str


class QueryResponse(BaseModel):
    """Response from the /query endpoint."""

    answer: str
    sources: list[str]


@app.post("/query", response_model=QueryResponse)
async def query_endpoint(request: QueryRequest) -> QueryResponse:
    """Answer a natural-language prompt about managed properties.

    Performs a RAG search over property Markdown files, then passes the
    retrieved context and the user prompt to the query agent for an answer.
    """
    if not query_agent:
        raise HTTPException(
            status_code=503,
            detail="Query agent is not available. Check GOOGLE_API_KEY.",
        )

    if not request.prompt.strip():
        raise HTTPException(status_code=400, detail="Prompt cannot be empty")

    try:
        result = query_agent.query(request.prompt)
        return QueryResponse(answer=result["answer"], sources=result["sources"])
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Query failed: {str(e)}")


_ADJUSTMENTS_DB = ADJUSTMENTS_DB


class AdjustmentSummary(BaseModel):
    id: str
    timestamp: str
    summary: str | None = None
    property: str | None = None
    building: str | None = None
    unit: str | None = None
    category: str | None = None
    action: str | None = None
    section_path: str | None = None
    markdown_path: str | None = None


@app.get("/adjustments", response_model=list[AdjustmentSummary])
def get_adjustments(limit: int = 50) -> list[AdjustmentSummary]:
    """Return recent content-agent adjustment summaries."""
    if not _ADJUSTMENTS_DB.exists():
        return []
    with sqlite3.connect(_ADJUSTMENTS_DB) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM adjustments ORDER BY timestamp DESC LIMIT ?", (limit,)
        ).fetchall()
    return [AdjustmentSummary(**dict(row)) for row in rows]


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
