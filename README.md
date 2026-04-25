# Baulog

AI-powered data relevancy assessment system using LangChain and Google Gemini. Evaluates unstructured data (emails, PDFs, ERP data) to determine business relevance.

## Features

- **FastAPI Server**: RESTful API for data evaluation
- **LangChain Agent**: Intelligent agent using Google Gemini model
- **Multi-format Support**: Evaluates emails, PDFs, ERP data, and other unstructured data
- **Relevancy Assessment**: Determines if data is relevant to business operations
- **Entity Extraction**: Extracts key entities from documents

## Prerequisites

- Python 3.11+
- Google API Key for Gemini access (get it from [ai.google.dev](https://ai.google.dev))

## Setup

1. **Clone and navigate to the project:**
   ```bash
   cd baulog
   ```

2. **Create a `.env` file with your Google API key:**
   ```bash
   cp .env.example .env
   # Edit .env and add your GOOGLE_API_KEY
   ```

3. **Install dependencies:**
   ```bash
   pip install -e .
   ```

## Running the Server

Start the FastAPI server:

```bash
python main.py
```

The server will run on `http://localhost:8000`

### Available Endpoints

- **`GET /`** - Welcome message
- **`GET /health`** - Health check and agent status
- **`POST /evaluate`** - Evaluate data for relevancy

## API Usage

### Evaluate Data

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

## Using the Agent Programmatically

```python
from agents.relevancy_agent import RelevancyAgent

# Initialize agent
agent = RelevancyAgent()

# Evaluate data
result = agent.evaluate("Your unstructured data here...")
print(result["assessment"])
```

## Project Structure

```
baulog/
├── main.py                 # FastAPI application
├── agents/
│   ├── __init__.py
│   └── relevancy_agent.py  # LangChain agent implementation
├── pyproject.toml          # Project dependencies
├── .env.example            # Environment variables template
└── README.md               # This file
```

## Dependencies

- `fastapi[standard]` - Web framework
- `langchain` - LLM orchestration framework
- `langchain-google-genai` - Google Gemini integration
- `google-generativeai` - Google Generative AI SDK
- `python-dotenv` - Environment variable management

## Testing the Agent

The `agents/relevancy_agent.py` file includes a test example. Run it directly:

```bash
python -m agents.relevancy_agent
```

## Configuration

Edit the agent behavior in [agents/relevancy_agent.py](agents/relevancy_agent.py):

- **Model**: Change from `gemini-1.5-flash` to `gemini-1.5-pro` for better quality
- **Temperature**: Adjust from 0.3 (consistent) to higher values for more creative responses
- **Tools**: Add custom tools for domain-specific evaluation

## Environment Variables

- `GOOGLE_API_KEY`: Your Google API key for Gemini access (required)

## License

MIT