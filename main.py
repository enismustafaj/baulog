import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from agents.relevancy_agent import RelevancyAgent

app = FastAPI(title="Baulog", description="Baulog API", version="0.1.0")

# Initialize the relevancy agent
try:
    relevancy_agent = RelevancyAgent()
except ValueError as e:
    print(f"Warning: Relevancy agent not initialized: {e}")
    relevancy_agent = None


class DataInput(BaseModel):
    """Input model for data evaluation."""

    data: str
    data_type: str = "unstructured"  # email, pdf, erp, etc.


class RelevancyResponse(BaseModel):
    """Response model for relevancy evaluation."""

    relevant: bool
    assessment: str
    confidence: str = "MEDIUM"


@app.get("/")
def read_root():
    """Root endpoint"""
    return {"message": "Welcome to Baulog API"}


@app.get("/health")
def health_check():
    """Health check endpoint"""
    agent_status = "ready" if relevancy_agent else "not_initialized"
    return {"status": "healthy", "agent_status": agent_status}


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


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
