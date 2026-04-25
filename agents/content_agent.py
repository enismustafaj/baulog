"""Content Agent using LangChain and Google Gemini.

Reads relevancy agent output, extracts the targeted section from the
property Markdown file, asks the LLM to adjust it, and writes back.
"""

import os
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


class ContentAgent:
    """Agent that adjusts a Markdown property-file section based on an action."""

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
            temperature=0.3,
        )
        self.parser = MarkdownParser()
        self.engine = ContextEngine(repo_path=PROPERTIES_DIR)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def adjust(
        self,
        relevancy_output: dict[str, Any],
        markdown_path: str | Path | None = None,
    ) -> dict[str, Any]:
        """Adjust the section described by *relevancy_output* inside a Markdown file.

        Args:
            relevancy_output: Dict produced by RelevancyAgent with keys
                property, building, unit, category, action.
            markdown_path: Explicit path to the Markdown file.  When omitted
                the ContextEngine searches by property name under repo_path.

        Returns:
            Dict with updated, section_path, original_content, adjusted_content.
        """
        property_name = relevancy_output.get("property", "")
        building_name = relevancy_output.get("building", "")
        unit_name = relevancy_output.get("unit", "")
        category = relevancy_output.get("category", "")
        action = relevancy_output.get("action", "")

        path = self._resolve_markdown_path(markdown_path, property_name)

        sections = self.parser.parse_file(path)
        target = self._find_section(sections, property_name, building_name, unit_name, category)
        if target is None:
            raise ValueError(
                f"No section found for property={property_name!r}, "
                f"building={building_name!r}, unit={unit_name!r}, "
                f"category={category!r}"
            )

        original_body = self._extract_body(path, target)
        adjusted_body = self._call_llm(original_body, action, category)
        self._write_back(path, target, adjusted_body)

        return {
            "updated": True,
            "markdown_path": str(path),
            "section_path": " > ".join(target.path),
            "original_content": original_body,
            "adjusted_content": adjusted_body,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_markdown_path(
        self,
        explicit_path: str | Path | None,
        property_name: str,
    ) -> Path:
        if explicit_path is not None:
            path = Path(explicit_path)
            if not path.exists():
                raise FileNotFoundError(f"Markdown file not found: {path}")
            return path

        if not property_name:
            raise ValueError("Either markdown_path or a non-empty property name is required.")

        property_context = self.engine.get_property(property_name)
        if property_context is None:
            raise FileNotFoundError(
                f"No Markdown file found for property {property_name!r} "
                f"under {self.engine.repo_path}"
            )

        md_path = getattr(property_context, "markdown_path", None)
        if not md_path:
            raise FileNotFoundError(f"Property {property_name!r} has no markdown_path set.")

        return Path(md_path)

    def _find_section(
        self,
        sections: list[MarkdownSection],
        property_name: str,
        building_name: str,
        unit_name: str,
        category: str,
    ) -> MarkdownSection | None:
        """Return the first section whose path matches all provided components."""
        norm_property = self._normalize(property_name)
        norm_building = self._normalize(building_name)
        norm_unit = self._normalize(unit_name)
        norm_category = self._normalize(category)

        for section in sections:
            path_norm = [self._normalize(p) for p in section.path]

            if norm_category and path_norm[-1] != norm_category:
                continue
            if norm_unit and norm_unit not in path_norm:
                continue
            if norm_building and norm_building not in path_norm:
                continue
            if norm_property and (not path_norm or path_norm[0] != norm_property):
                continue

            return section

        return None

    def _extract_body(self, path: Path, section: MarkdownSection) -> str:
        """Return the section body (lines after the heading) from the file."""
        lines = path.read_text(encoding="utf-8").splitlines()
        # start_line is 1-based (heading); body starts at start_line (0-based next line)
        body_lines = lines[section.start_line : section.end_line]
        return "\n".join(body_lines).strip()

    def _call_llm(self, current_content: str, action: str, category: str) -> str:
        """Ask the LLM to apply *action* to *current_content* and return the result."""
        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are a property-management document editor. "
                    "You receive the current body of a Markdown section (category: {category}) "
                    "and an action description. "
                    "Apply the action to produce updated content. "
                    "Preserve the existing Markdown list format (lines starting with '- '). "
                    "Return ONLY the updated section body — no headings, no explanations.",
                ),
                (
                    "human",
                    "Current content:\n{content}\n\nAction: {action}\n\nUpdated content:",
                ),
            ]
        )

        chain = prompt | self.llm
        result = chain.invoke(
            {
                "category": category or "section",
                "content": current_content if current_content else "(empty)",
                "action": action,
            }
        )
        return str(result.content).strip()

    def _write_back(self, path: Path, section: MarkdownSection, new_body: str) -> None:
        """Replace the section body in the file, keeping the heading line intact."""
        raw = path.read_text(encoding="utf-8")
        lines = raw.splitlines(keepends=True)

        # start_line is 1-based; heading is at index start_line-1.
        # Body occupies lines[start_line : end_line] (0-based, exclusive end).
        body_start = section.start_line   # 0-based index of first body line
        body_end = section.end_line       # 0-based exclusive end of body

        new_body_lines: list[str] = []
        if new_body:
            for line in new_body.splitlines():
                new_body_lines.append(line + "\n")
            # Ensure a blank separator before the next section when one follows
            if body_end < len(lines) and new_body_lines and new_body_lines[-1].strip():
                new_body_lines.append("\n")

        updated = lines[:body_start] + new_body_lines + lines[body_end:]
        path.write_text("".join(updated), encoding="utf-8")

    def _normalize(self, value: str) -> str:
        return " ".join(str(value).casefold().strip().strip(":").split())
