# Baulog

AI-powered data relevancy assessment system using LangChain and Google Gemini. Evaluates unstructured data (emails, PDFs, ERP data) to determine business relevance.

## Features

- **FastAPI Server**: RESTful API for data evaluation
- **LangChain Agent**: Intelligent agent using Google Gemini model
- **Asynchronous Queue System**: Webhooks enqueue data, background worker processes asynchronously
- **Webhook Support**: Email, Slack, and ERP webhooks for real-time data ingestion
- **Persistent Queue**: SQLite-based queue with retry logic and result tracking
- **Multi-format Support**: Evaluates emails, PDFs, ERP data, and other unstructured data
- **Relevancy Assessment**: Determines if data is relevant to business operations
- **Entity Extraction**: Extracts key entities from documents

## How It Works

```
Webhook Receives Data
    ↓
Data Enqueued (fast response)
    ↓
Worker Process (background)
    ↓
Agent Evaluation (LangChain + Gemini)
    ↓
Results Stored (query via API)
```

## Prerequisites

- Python 3.11+
- Google API Key for Gemini access (get it from [ai.google.dev](https://ai.google.dev))
- Optional: Email provider credentials, Slack app credentials, ERP system access

## Quick Start

1. **Install dependencies:**
   ```bash
   pip install -e .
   ```

2. **Configure API key:**
   ```bash
   cp .env.example .env
   # Edit .env and add your GOOGLE_API_KEY
   ```

3. **Start the API server:**
   ```bash
   python main.py
   ```

4. **Start the worker** (in another terminal):
   ```bash
   python worker.py
   ```

That's it! Webhooks will now enqueue data and the worker will process it asynchronously.

- **`GET /`** - Welcome message
- **`GET /health`** - Health check and agent status
- **`POST /evaluate`** - Evaluate data for relevancy

#### Webhook Endpoints

- **`POST /webhooks/email`** - Receive and process email data
- **`POST /webhooks/slack`** - Receive and process Slack messages
- **`POST /webhooks/erp`** - Receive and process ERP records

## API Usage

### 1. Synchronous Evaluation

For immediate evaluation without queueing:

**Request:**
```bash
curl -X POST "http://localhost:8000/evaluate" \
  -H "Content-Type: application/json" \
  -d '{
    "data": "From: customer@example.com\nSubject: Purchase Order\n\nWe need 50 units of Product A",
    "data_type": "email"
  }'
```

**Response:**
```json
{
  "relevant": true,
  "assessment": "RELEVANT - This is a business transaction (purchase order) with specific quantity and product requirements.",
  "confidence": "HIGH"
}
```

### 2. Async Webhook: Email

Webhooks enqueue data for asynchronous processing. No waiting for agent evaluation.

**Request:**
```bash
curl -X POST "http://localhost:8000/webhooks/email" \
  -H "Content-Type: application/json" \
  -d '{
    "sender": "customer@example.com",
    "recipients": ["sales@yourcompany.com"],
    "subject": "Purchase Order Request",
    "body": "We would like to order 100 units of Product X at $50 per unit. Please confirm availability.",
    "message_id": "msg_12345",
    "timestamp": "2024-04-25T10:30:00Z"
  }'
```

**Response (immediate - data enqueued):**
```json
{
  "status": "enqueued",
  "message": "Email from customer@example.com enqueued for processing",
  "data_id": "550e8400-e29b-41d4-a716-446655440000",
  "enqueued_at": "2024-04-25T10:30:00Z"
}
```

**Get results later:**
```bash
curl http://localhost:8000/queue/item/550e8400-e29b-41d4-a716-446655440000
```

Response:
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "source": "email",
  "status": "completed",
  "created_at": "2024-04-25T10:30:00Z",
  "assessment": "RELEVANT - This is a purchase order with specific product and pricing information."
}
```

### 3. Async Webhook: Slack

**Setup:**
1. Create a Slack App at [api.slack.com](https://api.slack.com)
2. Enable Event Subscriptions and set Request URL to `http://your-domain.com:8000/webhooks/slack`
3. Subscribe to events: `message.channels`, `message.groups`, `message.im`

**Slack sends verification challenge (handled automatically):**
```bash
curl -X POST "http://localhost:8000/webhooks/slack" \
  -H "Content-Type: application/json" \
  -d '{
    "type": "url_verification",
    "challenge": "3eZbrw1aBrm2K0Oo7YPvAq"
  }'
```

Response: `{"challenge": "3eZbrw1aBrm2K0Oo7YPvAq"}`

**Slack message event (enqueued for async processing):**
```bash
curl -X POST "http://localhost:8000/webhooks/slack" \
  -H "Content-Type: application/json" \
  -d '{
    "type": "event_callback",
    "event": {
      "type": "message",
      "channel": "C123456",
      "user": "U789012",
      "text": "We need to expedite the shipment due to production delays",
      "timestamp": "1234567890.123456"
    },
    "team_id": "T123456",
    "api_app_id": "A123456",
    "event_id": "Ev123456",
    "event_time": 1234567890
  }'
```

Response (enqueued):
```json
{
  "status": "enqueued",
  "message": "Slack message from U789012 enqueued for processing",
  "data_id": "def-456...",
  "enqueued_at": "2024-04-25T10:30:00Z"
}
```

### 4. Async Webhook: ERP

**Setup:**
Configure your ERP system (SAP, Oracle, NetSuite, etc.) to send notifications to `http://your-domain.com:8000/webhooks/erp`

**Request - Purchase Order:**
```bash
curl -X POST "http://localhost:8000/webhooks/erp" \
  -H "Content-Type: application/json" \
  -d '{
    "record_type": "purchase_order",
    "record_id": "PO-2024-001",
    "system": "SAP",
    "priority": "HIGH",
    "timestamp": "2024-04-25T10:30:00Z",
    "data": {
      "vendor": "Supplier Inc.",
      "total_amount": 15000,
      "items": [
        {
          "material_id": "MAT-123",
          "quantity": 100,
          "unit_price": 150
        }
      ],
      "delivery_date": "2024-05-10",
      "status": "RELEASED"
    }
  }'
```

**Response (enqueued immediately):**
```json
{
  "status": "enqueued",
  "message": "ERP purchase_order (ID: PO-2024-001) enqueued for processing",
  "data_id": "ghi-789...",
  "enqueued_at": "2024-04-25T10:30:00Z"
}
```

**Get results:**
```bash
curl http://localhost:8000/queue/item/ghi-789...
```

## Queue Management API

Track and retrieve webhook results:

### Queue Status
```bash
curl http://localhost:8000/queue/status
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

### Get Item Status & Assessment
```bash
curl http://localhost:8000/queue/item/{item_id}
```

### Recent Completed Items
```bash
curl http://localhost:8000/queue/completed?limit=10&hours=24
```

## Using the Agent Programmatically

```python
from agents.relevancy_agent import RelevancyAgent

# Initialize agent
agent = RelevancyAgent()

# Evaluate data
result = agent.evaluate("Your unstructured data here...")
print(result["assessment"])
```

## Webhook Security

All webhooks support signature verification:

### Email Webhook Security
```python
from webhooks.email_handler import EmailWebhookHandler

is_valid = EmailWebhookHandler.validate_webhook_signature(
    signature="provided_signature",
    payload="raw_payload",
    secret="your_shared_secret"
)
```

### Slack Webhook Security
The Slack webhook automatically validates:
- Request timestamp (must be within 5 minutes)
- Request signature using Slack signing secret

### ERP Webhook Security
```python
from webhooks.erp_handler import ERPWebhookHandler

is_valid = ERPWebhookHandler.validate_webhook_signature(
    signature="provided_signature",
    payload="raw_payload",
    secret="your_shared_secret"
)
```

## Project Structure

```
baulog/
├── main.py                      # FastAPI server with webhook & queue endpoints
├── worker.py                    # Background worker for async processing
├── queue_manager.py             # SQLite queue management
├── agents/
│   ├── __init__.py
│   └── relevancy_agent.py       # LangChain agent implementation
├── webhooks/
│   ├── __init__.py
│   ├── email_handler.py         # Email webhook handler
│   ├── slack_handler.py         # Slack webhook handler
│   └── erp_handler.py           # ERP webhook handler
├── data/
│   └── baulog_queue.db          # SQLite queue database (auto-created)
├── ASYNC_QUEUE_GUIDE.md         # Detailed async processing guide
├── WEBHOOK_GUIDE.md             # Webhook integration guide
├── pyproject.toml               # Project dependencies
├── .env.example                 # Environment variables template
└── README.md                    # This file
```

## Running the System

### 1. Start the API Server
```bash
python main.py
```

### 2. Start the Worker (in another terminal)
```bash
python worker.py
```

The worker will continuously poll the queue every 5 seconds and process items in batches of 10.

## Configuration

### Environment Variables

Create a `.env` file with:
```env
GOOGLE_API_KEY=your_google_api_key_here
EMAIL_WEBHOOK_SECRET=optional_email_secret
SLACK_SIGNING_SECRET=optional_slack_secret
ERP_WEBHOOK_SECRET=optional_erp_secret
```

### Agent Configuration

Edit [agents/relevancy_agent.py](agents/relevancy_agent.py) to customize:
- **Model**: Change from `gemini-1.5-flash` to `gemini-1.5-pro`
- **Temperature**: Adjust from 0.3 (consistent) to higher values
- **Tools**: Add custom tools for domain-specific evaluation

## Dependencies

- `fastapi[standard]` - Web framework
- `langchain` - LLM orchestration framework
- `langchain-google-genai` - Google Gemini integration
- `google-generativeai` - Google Generative AI SDK
- `python-dotenv` - Environment variable management
- `email-validator` - Email validation

## Testing Webhooks Locally

Use ngrok for local testing with external webhooks:

```bash
# Install ngrok
brew install ngrok

# Start ngrok tunnel
ngrok http 8000

# Use the provided ngrok URL (e.g., https://abc123.ngrok.io)
# to configure webhooks in Slack, email provider, or ERP system
```

## Asynchronous Processing Flow

```
Email/Slack/ERP Data 
    ↓
Webhook Endpoint (Fast Response)
    ↓
Data Enqueued to SQLite Queue
    ↓
Worker Process Picks Up Item
    ↓
Data Formatting & Validation
    ↓
Relevancy Agent (LangChain + Gemini)
    ↓
Assessment Stored in Queue
    ↓
Query Results via API (/queue/item/{id})
```

## Troubleshooting

**Agent not initialized:**
```
Error: GOOGLE_API_KEY environment variable not set
```
Solution: Create `.env` file and set `GOOGLE_API_KEY`

**Webhooks not being processed:**
- Check if worker is running: `ps aux | grep worker.py`
- Check queue status: `curl http://localhost:8000/queue/status`
- Start worker: `python worker.py`

**Items stuck in pending:**
- Restart worker process
- Check worker logs for errors
- Verify agent is initialized

**Slow processing:**
- Run multiple worker instances: `python worker.py &` (run in background)
- Adjust batch size: `python worker.py --items 20`
- Reduce poll interval: `python worker.py --poll-interval 1`

See [ASYNC_QUEUE_GUIDE.md](ASYNC_QUEUE_GUIDE.md) for detailed troubleshooting.

## Production Deployment

For production, use:
- **Supervisor** or **systemd** for process management
- **Docker** for containerization
- **PostgreSQL** for queue storage (large scale)
- **Gunicorn** with multiple workers for the API
- **Multiple worker instances** for processing scale

See [ASYNC_QUEUE_GUIDE.md](ASYNC_QUEUE_GUIDE.md) for deployment examples.

## License

MIT