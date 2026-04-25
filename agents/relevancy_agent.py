"""Relevancy Agent using LangChain and Google Gemini.

This agent analyzes uploaded file content and extracts structured routing data.
"""

import json
import os
from typing import Any
from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from agents.config import GEMINI_MODEL

load_dotenv()


class RelevancyOutput(BaseModel):
    """Structured output extracted from uploaded file content."""

    property: str = Field(default="")
    building: str = Field(default="")
    unit: str = Field(default="")
    category: str = Field(default="")
    action: str = Field(default="")


class RelevancyAgent:
    """Agent for extracting structured routing data from uploaded content."""

    def __init__(self, api_key: str | None = None):
        """Initialize the relevancy agent.

        Args:
            api_key: Google API key. If not provided, uses GOOGLE_API_KEY env var.
        """
        if api_key is None:
            api_key = os.getenv("GOOGLE_API_KEY")
            if not api_key:
                raise ValueError(
                    "GOOGLE_API_KEY environment variable not set. "
                    "Please set it or pass api_key parameter."
                )

        self.llm = ChatGoogleGenerativeAI(
            model=GEMINI_MODEL,
            google_api_key=api_key,
            temperature=0,
        )

    def _parse_structured_output(self, content: str) -> RelevancyOutput:
        """Parse and validate the model response as the required JSON object."""
        text = content.strip()
        if text.startswith("```"):
            text = text.removeprefix("```json").removeprefix("```").strip()
            text = text.removesuffix("```").strip()

        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")
            if start == -1 or end == -1 or end <= start:
                raise
            payload = json.loads(text[start : end + 1])

        return RelevancyOutput.model_validate(payload)

    def evaluate(self, data: str) -> dict[str, Any]:
        """Extract structured routing data from uploaded file content.

        Args:
            data: Text extracted from an uploaded file.

        Returns:
            Dictionary containing the structured extraction and raw model response.
        """
        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You analyze only the content extracted from uploaded files. "
                    "Do not use filenames, upload metadata, or outside knowledge. "
                    "Extract the best matching property, building, unit, category, and action. "
                    "If a value is not present in the uploaded content, use an empty string. "
                    "Return only one valid JSON object with exactly these keys: "
                    "property, building, unit, category, action.",
                ),
                (
                    "human",
                    "Uploaded file content:\n\n{data}\n\n"
                    "Required output shape:\n"
                    '{{"property":"property_name","building":"building_name",'
                    '"unit":"unit_name","category":"category_name",'
                    '"action":"action_description"}}',
                ),
            ]
        )

        chain = prompt | self.llm
        result = chain.invoke({"data": data})
        structured_output = self._parse_structured_output(str(result.content))
        return {
            "assessment": structured_output.model_dump(),
            "raw_response": result,
        }
