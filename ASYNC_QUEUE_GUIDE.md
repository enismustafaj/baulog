# Asynchronous Queue System Guide

## Overview

Baulog now uses an asynchronous queue-based system for webhook processing:

1. **Webhooks receive data** → immediately enqueue and return acknowledgment
2. **Worker process** → picks up items from queue in background
3. **Agent evaluation** → runs agentic workflow on queued data
4. **Results storage** → assessments saved in queue for retrieval

This approach provides:
- ✅ Fast webhook response times (no waiting for agent)
- ✅ Resilient processing (persistent queue with retry logic)
- ✅ Scalability (multiple workers can process in parallel)
- ✅ Result tracking (query status and assessments via API)

## Architecture

```
Email/Slack/ERP Webhook
    ↓
API Receives → Enqueues → Returns 200 OK (fast!)
    ↓
SQLite Queue (persistent storage)
    ↓
Worker Process (background task)
    ↓
Agent Evaluation (LangChain + Gemini)
    ↓
Results Stored in Queue
    ↓
Query Results API (/queue/item/{id})
```

## Quick Start

### 1. Start the Server
```bash
python main.py
```

### 2. Start the Worker (in another terminal)
```bash
python worker.py
```

The worker will continuously process pending items from the queue.

### 3. Send Webhook Data
```bash
curl -X POST http://localhost:8000/webhooks/email \
  -H "Content-Type: application/json" \
  -d '{
    "sender": "customer@example.com",
    "recipients": ["sales@company.com"],
    "subject": "Purchase Order",
    "body": "We need 100 units of Product A",
    "message_id": "msg_123"
  }'
```

Response (immediate):
```json
{
  "status": "enqueued",
  "message": "Email from customer@example.com enqueued for processing",
  "data_id": "550e8400-e29b-41d4-a716-446655440000",
  "enqueued_at": "2024-04-25T10:30:00Z"
}
```

### 4. Check Status
```bash
# Get queue statistics
curl http://localhost:8000/queue/status

# Get specific item status and assessment
curl http://localhost:8000/queue/item/550e8400-e29b-41d4-a716-446655440000

# Get recently completed items
curl http://localhost:8000/queue/completed?limit=10
```

## Webhook Endpoints

All webhooks now **enqueue data immediately** and don't wait for processing.

### Email Webhook
```bash
POST /webhooks/email
```

### Slack Webhook
```bash
POST /webhooks/slack
```

### ERP Webhook
```bash
POST /webhooks/erp
```

## Queue Management API

### Get Queue Statistics
```bash
GET /queue/status
```

Response:
```json
{
  "pending": 5,
  "processing": 1,
  "completed": 42,
  "failed": 0
}
```

### Get Item Status
```bash
GET /queue/item/{item_id}
```

Response (pending):
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "source": "email",
  "status": "pending",
  "created_at": "2024-04-25T10:30:00Z"
}
```

Response (completed):
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "source": "email",
  "status": "completed",
  "created_at": "2024-04-25T10:30:00Z",
  "assessment": "RELEVANT - This is a purchase order with specific product requirements and quantities..."
}
```

### Get Completed Items
```bash
GET /queue/completed?limit=10&hours=24
```

Returns recent completed items with their assessments.

## Worker Configuration

### Start with Custom Settings
```bash
# Process items one at a time
python worker.py --items 1

# Process 20 items per batch, wait 2 seconds between polls
python worker.py --items 20 --poll-interval 2

# Process one batch and exit
python worker.py --once

# Run for testing (process 5 items then stop)
python worker.py --items 5 --once
```

### View Queue Status
```bash
# Show queue statistics
python worker.py --stats

# Show pending items
python worker.py --show-pending

# Show last 10 completed items
python worker.py --show-completed 10
```

### Multiple Worker Instances
For high-volume scenarios, run multiple workers:

```bash
# Terminal 1
python worker.py --items 10

# Terminal 2
python worker.py --items 10

# Terminal 3
python worker.py --items 10
```

All workers safely share the same SQLite queue.

## Data Persistence

Queue data is stored in SQLite at: `data/baulog_queue.db`

### Database Schema
```sql
CREATE TABLE queue (
  id TEXT PRIMARY KEY,          -- Unique item ID
  source TEXT NOT NULL,          -- email, slack, erp
  status TEXT NOT NULL,          -- pending, processing, completed, failed
  payload TEXT NOT NULL,         -- JSON webhook data
  assessment TEXT,               -- Agent assessment (after processing)
  error_message TEXT,            -- Error if failed
  created_at TIMESTAMP,          -- When enqueued
  processed_at TIMESTAMP,        -- When completed/failed
  retry_count INTEGER,           -- Number of retries
  metadata TEXT                  -- JSON metadata (sender, channel, etc.)
)
```

## Error Handling & Retries

If processing fails:
1. Worker catches the error
2. Item is marked as failed with error message
3. Item is automatically returned to pending queue for retry
4. Retry count is incremented

### Max Retries
Set in worker.py to prevent infinite retry loops. Failed items are moved to permanent failure after max retries.

## Examples

### Example 1: Email Processing Flow

```bash
# 1. Send email webhook (fast response)
curl -X POST http://localhost:8000/webhooks/email \
  -H "Content-Type: application/json" \
  -d '{
    "sender": "customer@example.com",
    "recipients": ["sales@company.com"],
    "subject": "Purchase Order #PO-2024-001",
    "body": "We need 100 units at $50 per unit. Total: $5,000.",
    "message_id": "msg_001"
  }'
# Response: {"status": "enqueued", "data_id": "abc-123..."}

# 2. Check queue status
curl http://localhost:8000/queue/status
# Response: {"pending": 1, "processing": 0, "completed": 0, "failed": 0}

# 3. Wait for worker to process (check logs)
# Worker output: "Processing email_handler item: abc-123..."

# 4. Check item status
curl http://localhost:8000/queue/item/abc-123...
# Response: {"status": "completed", "assessment": "RELEVANT - This is a purchase order..."}
```

### Example 2: Multiple Webhooks

```bash
# Send 3 emails quickly (all enqueued immediately)
for i in {1..3}; do
  curl -X POST http://localhost:8000/webhooks/email \
    -H "Content-Type: application/json" \
    -d "{\"sender\": \"customer$i@example.com\", \"recipients\": [\"sales@company.com\"], \"subject\": \"Order $i\", \"body\": \"We need products\", \"message_id\": \"msg_$i\"}"
done

# Check queue
curl http://localhost:8000/queue/status
# Response: {"pending": 3, "processing": 0, "completed": 0, "failed": 0}

# Worker processes all 3 in background
# Later...
curl http://localhost:8000/queue/status
# Response: {"pending": 0, "processing": 0, "completed": 3, "failed": 0}

# Retrieve all assessments
curl http://localhost:8000/queue/completed?limit=3
```

### Example 3: Slack Webhook with URL Verification

```bash
# Slack sends URL verification challenge
curl -X POST http://localhost:8000/webhooks/slack \
  -H "Content-Type: application/json" \
  -d '{
    "type": "url_verification",
    "challenge": "3eZbrw1aBrm2K0Oo7YPvAq"
  }'
# Response: {"challenge": "3eZbrw1aBrm2K0Oo7YPvAq"} (immediate, not queued)

# Later, Slack sends message event
curl -X POST http://localhost:8000/webhooks/slack \
  -H "Content-Type: application/json" \
  -d '{
    "type": "event_callback",
    "event": {
      "type": "message",
      "channel": "C123456",
      "user": "U789012",
      "text": "We need expedited shipping",
      "timestamp": "1234567890.123456"
    }
  }'
# Response: {"status": "enqueued", "data_id": "def-456..."} (enqueued for async processing)
```

## Monitoring

### View Worker Logs
```bash
# Run worker with logging
python worker.py
```

Output:
```
2024-04-25 10:30:00 - QueueWorker - INFO - Starting worker (batch_size=10, poll_interval=5s)
2024-04-25 10:30:05 - QueueWorker - INFO - Processing batch of 3 items...
2024-04-25 10:30:06 - QueueWorker - INFO - Processing email item: abc-123...
2024-04-25 10:30:08 - QueueWorker - INFO - ✓ Completed: abc-123
2024-04-25 10:30:08 - QueueWorker - INFO - Batch complete. Processed 1 items.
2024-04-25 10:30:08 - QueueWorker - INFO - Queue Stats: {'pending': 2, 'processing': 0, 'completed': 1, 'failed': 0}
2024-04-25 10:30:08 - QueueWorker - INFO - Worker Stats: {'processed': 1, 'completed': 1, 'failed': 0, 'errors': 0}
```

### Monitor Queue Size
```bash
watch -n 1 'curl -s http://localhost:8000/queue/status'
```

## Production Deployment

### Using Supervisor (for process management)
```ini
# /etc/supervisor/conf.d/baulog.conf

[program:baulog-api]
command=/path/to/venv/bin/gunicorn main:app --workers 4 --worker-class uvicorn.workers.UvicornWorker
directory=/path/to/baulog
autostart=true
autorestart=true

[program:baulog-worker]
command=/path/to/venv/bin/python worker.py
directory=/path/to/baulog
autostart=true
autorestart=true
numprocs=3
process_name=%(program_name)s_%(process_num)d
```

### Using Docker
```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY . .
RUN pip install -e .

# Run API
CMD ["gunicorn", "main:app", "--workers", "4", "--worker-class", "uvicorn.workers.UvicornWorker"]

# Or run worker
# CMD ["python", "worker.py"]
```

### Database Backup
```bash
# Backup queue database
cp data/baulog_queue.db data/baulog_queue.db.backup

# Restore from backup
cp data/baulog_queue.db.backup data/baulog_queue.db
```

## Troubleshooting

### Worker not processing items?
```bash
# Check if worker is running
ps aux | grep worker.py

# Check queue status
curl http://localhost:8000/queue/status

# Run worker in test mode
python worker.py --once

# Check logs for errors
tail -f /var/log/baulog-worker.log
```

### Items stuck in "processing"?
Worker crashed mid-processing. Options:
1. Restart worker (will retry automatically)
2. Manually update database:
   ```sql
   UPDATE queue SET status='pending' WHERE status='processing';
   ```

### SQLite locked error?
Multiple workers accessing simultaneously. Solution:
- SQLite handles this with a lock
- If persistent, consider PostgreSQL for high-volume

### Assessment is empty/NULL?
Item hasn't been processed yet. Check:
1. Is worker running? `ps aux | grep worker.py`
2. Check queue status: `curl http://localhost:8000/queue/status`
3. Wait for worker to process and check again

## Performance Tips

1. **Multiple workers**: Run 3-5 worker instances for parallel processing
2. **Batch size**: Increase `--items` for more throughput
3. **Poll interval**: Decrease for lower latency
4. **Database**: Use PostgreSQL for millions of queue items
5. **Cleanup**: Remove old completed items regularly

## Comparison: Old vs New

| Aspect | Synchronous (Old) | Asynchronous (New) |
|--------|---|---|
| Webhook response | Slow (waits for agent) | Fast (immediate) |
| Agent processing | Blocks webhook | Background worker |
| Error handling | Limited | Retry logic |
| Scalability | Single threaded | Multiple workers |
| Result tracking | Returned immediately | Query via API |
| Persistence | Memory only | SQLite database |

---

**Start processing:** `python worker.py` in another terminal while the API runs!
