"""Relevancy Agent using LangChain and Google Gemini.

This agent evaluates unstructured data (emails, PDFs, ERP data, etc.)
and determines whether the data is relevant based on business criteria.
"""

import os
from typing import Any
from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate

load_dotenv()


class RelevancyAgent:
    """Agent for evaluating data relevancy using Gemini."""

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
            model="gemini-1.5-flash",
            google_api_key=api_key,
            temperature=0.3,  # Lower temperature for more consistent relevancy decisions
        )

    def _check_business_relevance(self, data: str) -> str:
        """Check if data is relevant to business operations.

        Args:
            data: The unstructured data to evaluate.

        Returns:
            Relevancy assessment.
        """
        relevance_prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are a business analyst. Evaluate if the provided data is relevant to business operations. "
                    "Consider: business transactions, customer interactions, financial data, operational updates. "
                    "Respond with RELEVANT or NOT_RELEVANT followed by a brief explanation.",
                ),
                ("human", "Data to evaluate:\n{data}"),
            ]
        )

        chain = relevance_prompt | self.llm
        result = chain.invoke({"data": data})
        return result.content

    def evaluate(self, data: str) -> dict[str, Any]:
        """Evaluate the relevancy of provided data.

        Args:
            data: Unstructured data to evaluate (email content, PDF text, ERP data, etc.)

        Returns:
            Dictionary containing assessment and details.
        """
        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are a data relevancy assessment agent. Evaluate unstructured data "
                    "such as emails, PDF documents, ERP records, and messages. "
                    "Determine whether the data is relevant to business operations.",
                ),
                (
                    "human",
                    "Evaluate this unstructured data for business relevancy:\n\n{data}\n\n"
                    "Provide a structured assessment with:\n"
                    "1. Relevancy decision (RELEVANT or NOT_RELEVANT)\n"
                    "2. Confidence level (HIGH, MEDIUM, LOW)\n"
                    "3. Key entities found\n"
                    "4. Business impact if relevant\n"
                    "5. Reasoning",
                ),
            ]
        )

        chain = prompt | self.llm
        result = chain.invoke({"data": data})
        return {
            "assessment": result.content,
            "raw_response": result,
        }
