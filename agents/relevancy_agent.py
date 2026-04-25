"""Relevancy Agent using LangChain and Google Gemini.

Reads uploaded file content and maps it to the existing property structure.
When the document references an owner rather than a property name directly,
the agent calls the lookup_property_by_owner tool to resolve it.
"""

import ast
import json
import logging
import os
from typing import Any

from dotenv import load_dotenv
from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from agents.config import GEMINI_MODEL, PROPERTIES_DIR
from context_engine.engine import ContextEngine
from owner_repository import OwnerRepository

load_dotenv()

logger = logging.getLogger(__name__)

SCHEMA_CATEGORIES = ("insurance", "maintenance", "rent", "tenant")
_MAX_TOOL_ROUNDS = 3


class RelevancyOutput(BaseModel):
    """Structured output extracted from uploaded file content."""

    property: str = Field(default="")
    building: str | None = Field(default=None)
    unit: str | None = Field(default=None)
    category: str = Field(default="")
    action: str = Field(default="")


class RelevancyAgent:
    """Maps uploaded document content to the property Markdown structure."""

    def __init__(self, api_key: str | None = None):
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
        self.engine = ContextEngine(repo_path=PROPERTIES_DIR)
        self._owner_repo = OwnerRepository()
        self._lookup_tool = self._make_lookup_tool()
        self._llm_with_tools = self.llm.bind_tools([self._lookup_tool])

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate(self, data: str) -> dict[str, Any]:
        """Classify uploaded file content against the known property structure.

        The agent first tries to identify the property from the document text.
        If it detects an owner name it doesn't recognise, it calls the
        lookup_property_by_owner tool to resolve the owner to a property.

        Returns:
            Dict with 'assessment' (RelevancyOutput fields) and 'raw_response'.
        """
        property_context = self._build_property_context()
        messages = self._build_prompt().format_messages(
            data=data,
            property_context=property_context,
        )

        response = None
        for _ in range(_MAX_TOOL_ROUNDS):
            response = self._llm_with_tools.invoke(messages)
            messages.append(response)

            if not response.tool_calls:
                break

            for tc in response.tool_calls:
                result = self._lookup_tool.invoke(tc["args"])
                logger.info("Tool %s(%s) -> %s", tc["name"], tc["args"], result)
                messages.append(ToolMessage(content=str(result), tool_call_id=tc["id"]))

        structured_output = self._parse_structured_output(self._extract_text(response.content))
        return {
            "assessment": structured_output.model_dump(),
            "raw_response": response,
        }

    # ------------------------------------------------------------------
    # Tool
    # ------------------------------------------------------------------

    def _make_lookup_tool(self):
        repo = self._owner_repo

        @tool
        def lookup_property_by_owner(query: str) -> str:
            """Look up which property belongs to an owner.

            Call this whenever the document mentions a person, company name,
            email address, or IBAN that might identify a property owner but
            you cannot match the property directly from the document text.

            Args:
                query: Owner name, email address, or IBAN to search for.

            Returns:
                Matching owner → property mappings, or a not-found message.
            """
            results = repo.search(query)
            if not results:
                return f"No property found for '{query}'."
            lines = []
            for r in results:
                details = ", ".join(
                    v for v in [r.get("street"), r.get("city"), r.get("email")]
                    if v
                )
                line = f"'{r['name']}' -> property: {r['property_name']}"
                if details:
                    line += f" ({details})"
                lines.append(line)
            return "\n".join(lines)

        return lookup_property_by_owner

    # ------------------------------------------------------------------
    # Property context (names only — owners are resolved via tool)
    # ------------------------------------------------------------------

    def _build_property_context(self) -> str:
        properties = self.engine.list_properties()
        if not properties:
            return "(No property files found.)"
        return "\n".join(f"- {p.name}" for p in properties)

    # ------------------------------------------------------------------
    # Prompt
    # ------------------------------------------------------------------

    def _build_prompt(self) -> ChatPromptTemplate:
        return ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are a property management document classifier.\n\n"
                    "Known properties:\n{property_context}\n\n"
                    "Your task:\n"
                    "1. Identify which property the document belongs to. "
                    "Use the exact property name from the list above.\n"
                    "   - If the property name is not directly stated, call "
                    "lookup_property_by_owner for every name and email address "
                    "you can find — try each one until you get a match.\n"
                    "   - For emails: a PARTICIPANTS section lists every address from "
                    "every header (From, To, CC, BCC, Reply-To, Sender). "
                    "Call the tool for each entry in that list, using both the "
                    "display name and the email address as separate queries.\n"
                    "   - For invoices or letters: check all sender and recipient blocks.\n"
                    "   - Also try any IBAN found in the document.\n"
                    "2. Extract the building name directly from the document text if mentioned. "
                    "Set to null if not mentioned.\n"
                    "3. Extract the unit name directly from the document text if mentioned. "
                    "Set to null if not mentioned.\n"
                    f"4. Identify the category. Must be exactly one of: {', '.join(SCHEMA_CATEGORIES)}.\n"
                    "5. Summarise what the document says in one or two sentences as the action.\n\n"
                    "Once you have all the information, return ONLY a valid JSON object with "
                    "exactly these keys: property, building, unit, category, action.",
                ),
                (
                    "human",
                    "Document content:\n\n{data}\n\n"
                    "Required output shape:\n"
                    '{{"property":"<exact name>","building":null,"unit":null,'
                    '"category":"<insurance|maintenance|rent|tenant>","action":"<summary>"}}',
                ),
            ]
        )

    # ------------------------------------------------------------------
    # Output parsing
    # ------------------------------------------------------------------

    def _extract_text(self, content) -> str:
        """Normalise LLM response content to a plain string.

        Handles all shapes Gemini / LangChain may return:
        - plain str
        - str that is a Python repr of a list/dict (stringified by an earlier layer)
        - list of dicts  [{'type': 'text', 'text': '...'}]
        - list of Pydantic-like objects with a .text attribute
        """
        import ast as _ast

        if isinstance(content, str):
            stripped = content.strip()
            if stripped.startswith("[") or stripped.startswith("{"):
                try:
                    parsed = _ast.literal_eval(stripped)
                    return self._extract_text(parsed)
                except (ValueError, SyntaxError):
                    pass
            return content

        if isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, dict):
                    parts.append(block.get("text", str(block)))
                elif hasattr(block, "text"):
                    parts.append(str(block.text))
                else:
                    parts.append(str(block))
            return "\n".join(parts)

        if hasattr(content, "text"):
            return str(content.text)

        return str(content)

    def _parse_structured_output(self, content: str) -> RelevancyOutput:
        text = content.strip()

        # Strip markdown code fences
        if text.startswith("```"):
            text = text.removeprefix("```json").removeprefix("```").strip()
            text = text.removesuffix("```").strip()

        # Isolate the first {...} block
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end > start:
            text = text[start : end + 1]

        # Attempt 1: standard JSON
        try:
            return RelevancyOutput.model_validate(json.loads(text))
        except Exception:
            pass

        # Attempt 2: Python literal (handles single quotes, True/False/None)
        try:
            payload = ast.literal_eval(text)
            if isinstance(payload, dict):
                return RelevancyOutput.model_validate(payload)
        except (ValueError, SyntaxError):
            pass

        logger.error("Could not parse agent response as JSON:\n%s", content)
        raise ValueError(f"Agent returned unparseable output: {content[:200]!r}")
