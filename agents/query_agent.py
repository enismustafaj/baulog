"""Query Agent using LangChain and Google Gemini.

Answers user prompts by retrieving relevant sections from property Markdown
files (RAG) and passing them as grounded context to the LLM.
"""

import os
import re
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate

from agents.config import GEMINI_MODEL, PROPERTIES_DIR
from context_engine.engine import ContextEngine
from context_engine.markdown_parser import MarkdownParser
from context_engine.models import MarkdownSection

load_dotenv()

_TOP_K = 8          # maximum sections forwarded to the LLM
_MIN_SCORE = 1      # sections scoring below this are discarded
_MIN_TERM_LEN = 3   # query words shorter than this are ignored (stop-word heuristic)
_PATH_WEIGHT = 3    # heading-path hits count this many times more than body hits

# Matches unit refs like "W33", "WE33", "WE 33", "W 33" → canonical "WE 33"
_UNIT_REF_RE = re.compile(r'\bwe?\s*(\d+)\b', re.IGNORECASE)
# Matches building refs like "building 16", "building 12a"
_BUILDING_REF_RE = re.compile(r'\bbuilding\s+(\S+)\b', re.IGNORECASE)


class QueryAgent:
    """Answers user prompts about managed properties using RAG."""

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
        self.parser = MarkdownParser()
        self.engine = ContextEngine(repo_path=PROPERTIES_DIR)

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

    def _extract_path_filters(self, query: str) -> dict[str, str | None]:
        """Return building/unit path fragments to pre-filter sections."""
        building_m = _BUILDING_REF_RE.search(query)
        unit_m = _UNIT_REF_RE.search(query)
        return {
            "building": f"building {building_m.group(1).lower()}" if building_m else None,
            "unit": f"unit we {unit_m.group(1)}" if unit_m else None,
        }

    def _matches_filters(self, section: MarkdownSection, filters: dict[str, str | None]) -> bool:
        path_lower = " ".join(section.path).lower()
        if filters["building"] and filters["building"] not in path_lower:
            return False
        if filters["unit"] and filters["unit"] not in path_lower:
            return False
        return True

    def _retrieve_context(self, query: str) -> tuple[str, list[str]]:
        """Parse every property file as a section tree, score each leaf section
        against the query, and return the top-K most relevant sections in
        document order.

        Scoring weights heading-path hits (_PATH_WEIGHT × body hits) so that
        structural matches (e.g. a section literally named 'maintenance' when
        the user asks about maintenance) rank above incidental mentions in body
        text.  Sections whose body is empty (pure structural headings) are
        skipped entirely.

        When the query mentions a specific building and/or unit, sections are
        pre-filtered to that scope before scoring so that a structural match
        elsewhere cannot push the target unit out of the top-K window.
        """
        # Normalise unit refs (e.g. "W33" → "WE 33") before term extraction
        normalised_query = _UNIT_REF_RE.sub(lambda m: f"WE {m.group(1)}", query)
        terms = [t for t in normalised_query.lower().split() if len(t) >= _MIN_TERM_LEN]
        if not terms:
            return "(Query is too short to search effectively.)", []

        filters = self._extract_path_filters(query)

        # (score, document_line, section, file_path)
        candidates: list[tuple[int, int, MarkdownSection, Path]] = []

        for md_path in self.engine._iter_markdown_files():
            try:
                sections = self.parser.parse_file(md_path)
            except Exception:
                continue

            for section in sections:
                if not self._matches_filters(section, filters):
                    continue

                body = self._body(section)
                if not body:
                    continue  # skip pure structural headings with no content

                path_text = " ".join(section.path).lower()
                path_score = sum(path_text.count(t) for t in terms) * _PATH_WEIGHT
                body_score = sum(body.lower().count(t) for t in terms)
                score = path_score + body_score

                if score >= _MIN_SCORE:
                    candidates.append((score, section.start_line, section, md_path))

        if not candidates:
            return "(No relevant property data found for this query.)", []

        # Select best K by relevance score
        candidates.sort(key=lambda x: x[0], reverse=True)
        top = candidates[:_TOP_K]

        # Re-sort into document order so the context reads coherently
        top.sort(key=lambda x: (str(x[3]), x[1]))

        context_parts: list[str] = []
        sources: list[str] = []

        for _, _, section, md_path in top:
            heading = " > ".join(section.path)
            context_parts.append(f"[{heading}]\n{self._body(section)}")
            sources.append(f"{md_path.name} — {heading}")

        return "\n\n---\n\n".join(context_parts), sources

    def _body(self, section: MarkdownSection) -> str:
        """Return section content with the heading line stripped."""
        lines = section.content.splitlines()
        body_lines = lines[1:] if lines and lines[0].startswith("#") else lines
        return "\n".join(body_lines).strip()

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
        return self._extract_text(result.content).strip()

    def _extract_text(self, content) -> str:
        if isinstance(content, str):
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
