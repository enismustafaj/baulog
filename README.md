# Baulog

Property management document processing system. Accepts uploaded files (PDF, CSV, EML), classifies them against a Markdown-based property registry using LangChain and Google Gemini, updates the relevant section in the property file, and exposes a natural-language query interface over the registry.

## How it works

```
File uploaded via API
        ↓
Text extracted & enqueued (immediate response)
        ↓
Worker picks up item
        ↓
RelevancyAgent — identifies property, building, unit, category
  └─ calls lookup_property_by_owner tool if needed
        ↓
ContentAgent — updates the matching section in the Markdown file
        ↓
Assessment stored in DB, result queryable via API
```

The property registry lives as Markdown files on the filesystem. The `QueryAgent` performs RAG over those files to answer natural-language questions about any property.

---

## Setup

**Requirements:** Python 3.11+, [uv](https://docs.astral.sh/uv/)

```bash
# Install dependencies
uv sync

# Configure environment
cp .env.example .env
# Fill in GOOGLE_API_KEY in .env

# Start the API server (worker starts automatically)
uv run python main.py
```

---

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `GOOGLE_API_KEY` | — | **Required.** Google Gemini API key |
| `GEMINI_MODEL` | `gemini-2.5-flash-preview-05-20` | Gemini model used by all agents |
| `BAULOG_PROPERTIES_DIR` | `data/properties` | Directory where property Markdown files are stored |
| `BAULOG_RUN_WORKER` | `true` | Set to `false` to disable the background worker on startup |
| `BAULOG_WORKER_BATCH_SIZE` | `10` | Queue items processed per worker batch |
| `BAULOG_WORKER_POLL_INTERVAL` | `5` | Seconds between worker queue polls |

---

## Property Markdown schema

Properties are stored as Markdown files in `BAULOG_PROPERTIES_DIR`. Each file follows this heading hierarchy:

```markdown
# Property Name

## owner
- Owner or management company name

## insurance
- Policy details

## maintanance
- Property-level maintenance notes

## buildings

### building 12
#### maintenance
#### rent

### building 16
#### maintenance
#### rent

#### units

##### unit WE 01
###### maintenance
###### rent
###### tenant

##### unit WE 02
...
```

Section content is a list of `- item` bullet points. Empty sections are valid placeholders.

---

## Owner database

Owners are stored in SQLite (`data/baulog_queue.db`) and used by the RelevancyAgent to match documents that reference a management company rather than the property name directly.

```python
from owner_repository import OwnerRepository

repo = OwnerRepository()
repo.add(
    name="Huber & Partner Immobilienverwaltung GmbH",
    property_name="WEG Immanuelkirchstraße 26",
    street="Friedrichstrasse 112",
    postal_code="10117",
    city="Berlin",
    email="info@huber-partner-verwaltung.de",
    phone="+49 30 12345-0",
    iban="DE89 3704 0044 0532 0130 00",
    bic="COBADEFFXXX",
    bank="Commerzbank Berlin",
    tax_number="13/456/78901",
)
```

The agent searches by name, email address, or IBAN, so any of those identifiers appearing in a document will resolve to the correct property.

---

## API endpoints

### File upload

| Method | Path | Description |
|---|---|---|
| `POST` | `/upload/pdf` | Upload a PDF — text extracted in-memory, enqueued |
| `POST` | `/upload/csv` | Upload a CSV — each data row enqueued as a separate item |
| `POST` | `/upload/eml` | Upload an `.eml` email file |

All upload endpoints accept `multipart/form-data` with a single `file` field. No extra headers required.

**PDF / EML response:**
```json
{
  "status": "enqueued",
  "message": "invoice.pdf text extracted and enqueued",
  "data_id": "550e8400-...",
  "enqueued_at": "2026-01-01T10:00:00"
}
```

**CSV response** (one entry per row):
```json
{
  "status": "enqueued",
  "message": "data.csv parsed and 42 rows enqueued",
  "row_count": 42,
  "data_ids": ["abc-123", "def-456", "..."],
  "enqueued_at": "2026-01-01T10:00:00"
}
```

---

### Queue management

| Method | Path | Description |
|---|---|---|
| `GET` | `/queue/status` | Counts by status (pending / processing / completed / failed) |
| `GET` | `/queue/item/{id}` | Details and assessment for a single item |
| `GET` | `/queue/completed?limit=100&hours=24` | Recently completed items |

---

### Query (RAG)

```
POST /query
Content-Type: application/json

{ "prompt": "What is the maintenance schedule for building 16?" }
```

Response:
```json
{
  "answer": "The maintenance schedule for building 16 includes...",
  "sources": ["weg-immanuelkirchstrasse-26.md — WEG Immanuelkirchstraße 26 > buildings > building 16 > maintenance"]
}
```

The query agent parses all property files into heading-based sections, scores each section by relevance to the prompt (path matches weighted 3× over body matches), and feeds the top results to the LLM as grounded context.

---

### Adjustment history

```
GET /adjustments?limit=50
```

Returns the most recent content-agent updates — which section was changed, the original and updated content, and the action that triggered the change.

---

### Health check

```
GET /health
```

```json
{
  "status": "healthy",
  "agent_status": "ready",
  "query_agent_status": "ready",
  "worker_status": "running",
  "worker_stats": { "processed": 10, "completed": 9, "failed": 1, "errors": 1, "skipped": 0 }
}
```

---

## Agents

### RelevancyAgent

Reads uploaded document text and outputs:

```json
{
  "property": "WEG Immanuelkirchstraße 26",
  "building": null,
  "unit": "unit WE 49",
  "category": "maintenance",
  "action": "Invoice for janitorial services, garbage bin provision, and winter service."
}
```

- `property` — exact name from the Markdown registry (required)
- `building` — null when the document is property-level
- `unit` — null when not unit-specific
- `category` — one of `insurance | maintenance | rent | tenant`
- `action` — one or two sentence summary

When the property name is not in the document, the agent calls the `lookup_property_by_owner` tool with every name, email, and IBAN it finds. The tool searches the owner database and returns the matching property name.

### ContentAgent

Takes the RelevancyAgent output, finds the matching section in the Markdown file (using substring path matching so `WE 49` matches heading `unit WE 49`), asks the LLM to update the content based on the action, and writes the result back to the file. Property-level documents prefer the shallowest matching section.

### QueryAgent

RAG pipeline over the property Markdown files:
1. Parses all files into `MarkdownSection` objects with heading paths and line numbers
2. Skips pure structural headings with no body
3. Scores sections: path hits × 3 + body hits
4. Takes top 8 by score, re-sorts into document order
5. Passes formatted sections to Gemini with a system prompt that restricts the answer to the retrieved data

---

## Worker

The background worker runs inside the same process as the API server (controlled by `BAULOG_RUN_WORKER`). It can also be run standalone:

```bash
uv run python worker.py               # continuous polling
uv run python worker.py --once        # process one batch then exit
uv run python worker.py --stats       # print queue stats then exit
uv run python worker.py --batch-size 20 --poll-interval 2
```

Items that fail are retried up to 3 times before being permanently marked as failed.

---

## Project structure

```
baulog/
├── main.py                  # FastAPI app, upload endpoints, query endpoint
├── worker.py                # Background queue worker
├── queue_manager.py         # SQLite queue (baulog_queue.db)
├── owner_repository.py      # SQLite owner → property index
├── agents/
│   ├── config.py            # Shared config (model, paths)
│   ├── relevancy_agent.py   # Document classifier with owner tool
│   ├── content_agent.py     # Markdown section updater
│   └── query_agent.py       # RAG query agent
├── context_engine/
│   ├── engine.py            # ContextEngine — searches property files
│   ├── markdown_parser.py   # Parses heading-based Markdown into sections
│   └── models.py            # PropertyContext, BuildingContext, UnitContext
├── data/
│   ├── properties/          # Property Markdown files (BAULOG_PROPERTIES_DIR)
│   ├── uploads/eml/         # Saved EML files (worker reads these)
│   ├── baulog_queue.db      # Queue + owner database
│   └── adjustments.db       # Content-agent update history
├── .env.example
└── pyproject.toml
```
