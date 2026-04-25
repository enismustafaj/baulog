"""Relevancy Agent using LangChain and Google Gemini.

This agent evaluates unstructured data (emails, PDFs, ERP data, etc.)
and determines whether the data is relevant based on business criteria.
"""

import os
from typing import Any
from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain.tools import Tool
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import HumanMessage

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

        self.tools = self._create_tools()
        self.agent_executor = self._create_agent()

    def _create_tools(self) -> list[Tool]:
        """Create tools for the agent.

        Returns:
            List of tools the agent can use.
        """
        tools = [
            Tool(
                name="check_business_relevance",
                func=self._check_business_relevance,
                description="Check if data is relevant to business operations based on content analysis",
            )
        ]
        return tools

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


    def _create_agent(self) -> AgentExecutor:
        """Create the agent executor.

        Returns:
            Configured agent executor.
        """
        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are a data relevancy assessment agent. Your job is to evaluate unstructured data "
                    "(emails, PDF documents, ERP system data, etc.) and determine if it's relevant to business operations. "
                    "Use available tools to analyze the data comprehensively. "
                    "Provide a final assessment: RELEVANT or NOT_RELEVANT with reasoning.",
                ),
                ("human", "{input}"),
                MessagesPlaceholder(variable_name="agent_scratchpad"),
            ]
        )

        agent = create_tool_calling_agent(self.llm, self.tools, prompt)
        executor = AgentExecutor(agent=agent, tools=self.tools, verbose=True)
        return executor

    def evaluate(self, data: str) -> dict[str, Any]:
        """Evaluate the relevancy of provided data.

        Args:
            data: Unstructured data to evaluate (email content, PDF text, ERP data, etc.)

        Returns:
            Dictionary containing assessment and details.
        """
        prompt = (
            f"Evaluate this unstructured data for business relevancy:\n\n{data}\n\n"
            "Provide a structured assessment with:\n"
            "1. Relevancy decision (RELEVANT or NOT_RELEVANT)\n"
            "2. Confidence level (HIGH, MEDIUM, LOW)\n"
            "3. Key entities found\n"
            "4. Business impact if relevant\n"
            "5. Reasoning"
        )

        result = self.agent_executor.invoke({"input": prompt})
        return {
            "assessment": result["output"],
            "raw_response": result,
        }

