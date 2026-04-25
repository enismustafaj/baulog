import logging
import os
import threading
from contextlib import asynccontextmanager
from typing import AsyncIterator

import uvicorn
from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel
from datetime import datetime
from agents.relevancy_agent import RelevancyAgent
from webhooks.email_handler import EmailWebhookHandler, EmailData
from webhooks.slack_handler import SlackWebhookHandler, SlackEvent
from webhooks.erp_handler import ERPWebhookHandler, ERPRecord
from queue_manager import queue_manager, DataSource
from worker import QueueWorker

logger = logging.getLogger(__name__)

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


@app.post("/evaluate", response_model=RelevancyResponse)
def evaluate_data(input_data: DataInput) -> RelevancyResponse:
    """Evaluate the relevancy of unstructured data using the relevancy agent.

    Args:
        input_data: The data to evaluate (email, PDF content, ERP data, etc.)

    Returns:
        RelevancyResponse with assessment and confidence level

    Raises:
        HTTPException: If agent is not initialized or evaluation fails
    """
    if not relevancy_agent:
        raise HTTPException(
            status_code=503,
            detail="Relevancy agent is not initialized. "
            "Please set GOOGLE_API_KEY environment variable.",
        )

    try:
        result = relevancy_agent.evaluate(input_data.data)
        assessment_text = result["assessment"].lower()

        # Parse the assessment to determine relevancy
        relevant = "relevant" in assessment_text and "not relevant" not in assessment_text

        return RelevancyResponse(
            relevant=relevant,
            assessment=result["assessment"],
            confidence="HIGH" if "high" in assessment_text else "MEDIUM",
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error evaluating data: {str(e)}",
        )


@app.post("/webhooks/email", response_model=WebhookResponse)
def email_webhook(
    payload: EmailData,
    x_signature: str | None = Header(None),
    x_secret: str | None = Header(None),
) -> WebhookResponse:
    """Webhook endpoint for receiving email data.

    Data is enqueued for asynchronous processing by the worker.

    Args:
        payload: Email webhook payload
        x_signature: Optional webhook signature for validation
        x_secret: Optional secret key for signature validation

    Returns:
        WebhookResponse with enqueue confirmation
    """
    try:
        # Convert payload to dict
        data = payload.model_dump()

        # Enqueue data for processing
        item_id = queue_manager.enqueue(
            data=data,
            source=DataSource.EMAIL,
            metadata={"sender": payload.sender, "subject": payload.subject},
        )

        return WebhookResponse(
            status="enqueued",
            message=f"Email from {payload.sender} enqueued for processing",
            data_id=item_id,
        )

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error enqueueing email: {str(e)}",
        )


@app.post("/webhooks/slack", response_model=WebhookResponse | dict)
def slack_webhook(
    payload: dict,
    x_slack_request_timestamp: str | None = Header(None),
    x_slack_signature: str | None = Header(None),
) -> WebhookResponse | dict:
    """Webhook endpoint for receiving Slack messages and events.

    Data is enqueued for asynchronous processing by the worker.
    Handles URL verification challenges immediately.

    Args:
        payload: Slack webhook payload
        x_slack_request_timestamp: Slack request timestamp
        x_slack_signature: Slack request signature

    Returns:
        WebhookResponse with enqueue confirmation, or challenge response for URL verification
    """
    try:
        # Handle URL verification challenge (must respond immediately)
        if payload.get("type") == "url_verification":
            return {"challenge": payload.get("challenge")}

        # Enqueue the event for processing
        event_id = payload.get("event_id") or f"slack_{int(datetime.now().timestamp())}"
        event = payload.get("event", {})
        user = event.get("user", "unknown")

        item_id = queue_manager.enqueue(
            data=payload,
            source=DataSource.SLACK,
            metadata={"user": user, "channel": event.get("channel")},
        )

        return WebhookResponse(
            status="enqueued",
            message=f"Slack message from {user} enqueued for processing",
            data_id=item_id,
        )

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error enqueueing Slack webhook: {str(e)}",
        )


@app.post("/webhooks/erp", response_model=WebhookResponse)
def erp_webhook(
    payload: ERPRecord,
    x_signature: str | None = Header(None),
    x_secret: str | None = Header(None),
) -> WebhookResponse:
    """Webhook endpoint for receiving ERP system data.

    Data is enqueued for asynchronous processing by the worker.

    Args:
        payload: ERP webhook payload
        x_signature: Optional webhook signature for validation
        x_secret: Optional secret key for signature validation

    Returns:
        WebhookResponse with enqueue confirmation
    """
    try:
        # Convert payload to dict
        data = payload.model_dump()

        # Enqueue data for processing
        item_id = queue_manager.enqueue(
            data=data,
            source=DataSource.ERP,
            metadata={
                "record_type": payload.record_type,
                "record_id": payload.record_id,
                "system": payload.system,
            },
        )

        return WebhookResponse(
            status="enqueued",
            message=f"ERP {payload.record_type} (ID: {payload.record_id}) enqueued for processing",
            data_id=item_id,
        )

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error enqueueing ERP webhook: {str(e)}",
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
