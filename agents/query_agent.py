"""Query Agent using LangChain and Google Gemini.

Answers user prompts by retrieving relevant sections from property Markdown
files (RAG) and passing them as grounded context to the LLM.
"""

import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate

from agents.config import GEMINI_MODEL
from context_engine.engine import ContextEngine
from context_engine.markdown_parser import MarkdownParser
from context_engine.models import MarkdownSection

load_dotenv()

_TOP_K = 6       # maximum sections to include in context
_MIN_SCORE = 1   # minimum term-hit score to consider a section relevant
_MIN_TERM_LEN = 3  # ignore query words shorter than this (stop-word heuristic)


class QueryAgent:
    """Answers user prompts about managed properties using RAG."""

    def __init__(
        self,
        api_key: str | None = None,
        repo_path: str | Path = ".",
    ):
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
        self.parser = MarkdownParser()
        self.engine = ContextEngine(repo_path=repo_path)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def query(self, prompt: str) -> dict[str, Any]:
        """Answer *prompt* using context retrieved from property Markdown files.

        Returns:
            Dict with 'answer' (str) and 'sources' (list of section paths).
        """
        context_text, sources = self._retrieve_context(prompt)
        answer = self._call_llm(prompt, context_text)
        return {"answer": answer, "sources": sources}

    # ------------------------------------------------------------------
    # RAG retrieval
    # ------------------------------------------------------------------

    def _retrieve_context(self, query: str) -> tuple[str, list[str]]:
        """Return (formatted_context, source_labels) for the top-K sections."""
        terms = [t for t in query.lower().split() if len(t) >= _MIN_TERM_LEN]
        scored: list[tuple[int, MarkdownSection, str]] = []

        for md_path in self.engine._iter_markdown_files():
            try:
                sections = self.parser.parse_file(md_path)
            except Exception:
                continue

            for section in sections:
                content_lower = section.content.lower()
                score = sum(content_lower.count(term) for term in terms)
                if score >= _MIN_SCORE:
                    scored.append((score, section, str(md_path)))

        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[:_TOP_K]

        if not top:
            return "(No relevant property data found for this query.)", []

        context_parts: list[str] = []
        sources: list[str] = []

        for _, section, path in top:
            heading = " > ".join(section.path)
            context_parts.append(f"[{heading}]\n{section.content}")
            sources.append(f"{Path(path).name} — {heading}")

        return "\n\n---\n\n".join(context_parts), sources

    # ------------------------------------------------------------------
    # LLM call
    # ------------------------------------------------------------------

    def _call_llm(self, prompt: str, context: str) -> str:
        template = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are a property management assistant. "
                    "Answer the user's question using ONLY the property data "
                    "provided below. "
                    "If the data does not contain enough information to answer, "
                    "say so clearly instead of guessing. "
                    "Be concise and factual.\n\n"
                    "Retrieved property data:\n{context}",
                ),
                ("human", "{prompt}"),
            ]
        )

        chain = template | self.llm
        result = chain.invoke({"context": context, "prompt": prompt})
        return str(result.content).strip()
