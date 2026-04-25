"""Content Agent using LangChain and Google Gemini.

Reads relevancy agent output, extracts the targeted section from the
property Markdown file, asks the LLM to adjust it, and writes back.
"""

import json
import os
import sqlite3
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate

from agents.config import ADJUSTMENTS_DB, GEMINI_MODEL, PROPERTIES_DIR, SESSIONS_DIR
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
        self._sessions_dir = SESSIONS_DIR
        self._db_path = ADJUSTMENTS_DB
        self._init_db()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def history(self, limit: int = 20) -> list[dict[str, Any]]:
        """Return the most recent adjustment summaries from the database."""
        if not self._db_path.exists():
            return []
        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM adjustments ORDER BY timestamp DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(row) for row in rows]

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
        property_name = relevancy_output.get("property") or ""
        building_name = relevancy_output.get("building") or ""
        unit_name = relevancy_output.get("unit") or ""
        category = relevancy_output.get("category") or ""
        action = relevancy_output.get("action") or ""

        session_id = str(uuid.uuid4())
        self._sessions_dir.mkdir(parents=True, exist_ok=True)
        session_ref = str(self._sessions_dir / f"{session_id}.jsonl")

        self._fire_hook("session-start", session_id, session_ref, action)

        path = self._resolve_markdown_path(markdown_path, property_name)

        sections = self.parser.parse_file(path)
        target = self._find_section(sections, property_name, building_name, unit_name, category)
        if target is None:
            self._fire_hook("session-end", session_id, session_ref, action)
            raise ValueError(
                f"No section found for property={property_name!r}, "
                f"building={building_name!r}, unit={unit_name!r}, "
                f"category={category!r}"
            )

        original_body = self._extract_body(path, target)
        adjusted_body = self._call_llm(original_body, action, category)
        self._write_back(path, target, adjusted_body)

        result = {
            "updated": True,
            "markdown_path": str(path),
            "section_path": " > ".join(target.path),
            "original_content": original_body,
            "adjusted_content": adjusted_body,
        }

        # Append result to session transcript so the stop hook can read it
        with open(session_ref, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(result) + "\n")

        self._save_summary(session_id, session_ref, relevancy_output)

        # Fire stop in background — checkpoint creation can take several seconds
        self._fire_hook("stop", session_id, session_ref, action, background=True)
        return result

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
        """Return the most specific section matching the given components.

        Unit and building names are matched as substrings of the path elements
        so that e.g. 'WE 49' matches the heading 'unit WE 49' and '16' matches
        'building 16'.  Property must match the first path element exactly.
        Category must match the last path element exactly.

        When building/unit are absent (property-level document) the shallowest
        matching section is preferred.
        """
        norm_property = self._normalize(property_name)
        norm_building = self._normalize(building_name)
        norm_unit = self._normalize(unit_name)
        norm_category = self._normalize(category)

        candidates: list[MarkdownSection] = []

        for section in sections:
            path_norm = [self._normalize(p) for p in section.path]

            if norm_category and path_norm[-1] != norm_category:
                continue
            if norm_unit and not any(norm_unit in p for p in path_norm):
                continue
            if norm_building and not any(norm_building in p for p in path_norm):
                continue
            if norm_property and (not path_norm or path_norm[0] != norm_property):
                continue

            candidates.append(section)

        if not candidates:
            return None

        # Prefer shallowest match when building/unit are not specified
        if not norm_building and not norm_unit:
            candidates.sort(key=lambda s: len(s.path))

        return candidates[0]

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
        return self._extract_text(result.content).strip()

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

    def _init_db(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS adjustments (
                    id            TEXT PRIMARY KEY,
                    timestamp     TEXT,
                    property      TEXT,
                    building      TEXT,
                    unit          TEXT,
                    category      TEXT,
                    action        TEXT,
                    section_path  TEXT,
                    markdown_path TEXT,
                    summary       TEXT
                )
            """)

    def _save_summary(
        self,
        session_id: str,
        session_ref: str,
        relevancy_output: dict[str, Any],
    ) -> None:
        try:
            entry = json.loads(Path(session_ref).read_text(encoding="utf-8").splitlines()[0])
        except (OSError, json.JSONDecodeError, IndexError):
            return
        property_ = relevancy_output.get("property", "")
        building  = relevancy_output.get("building", "")
        unit      = relevancy_output.get("unit", "")
        category  = relevancy_output.get("category", "")
        action    = relevancy_output.get("action", "")
        summary   = f"{property_} · {building} · {unit} · {category}: {action}"

        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """INSERT OR REPLACE INTO adjustments
                   (id, timestamp, property, building, unit, category, action, section_path, markdown_path, summary)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    session_id,
                    datetime.now(timezone.utc).isoformat(),
                    property_, building, unit, category, action,
                    entry.get("section_path", ""),
                    entry.get("markdown_path", ""),
                    summary,
                ),
            )

    def _normalize(self, value: str) -> str:
        return " ".join(str(value).casefold().strip().strip(":").split())

    def _fire_hook(
        self,
        hook_name: str,
        session_id: str,
        session_ref: str,
        prompt: str,
        background: bool = False,
    ) -> None:
        payload = json.dumps({
            "hook_type": hook_name,
            "session_id": session_id,
            "session_ref": session_ref,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "user_prompt": prompt,
        }).encode()
        # Augment PATH so `entire` is found even when invoked from restricted shells
        env = os.environ.copy()
        extra = os.path.expanduser("~/.local/bin")
        if extra not in env.get("PATH", ""):
            env["PATH"] = extra + ":" + env.get("PATH", "")
        try:
            proc = subprocess.Popen(
                ["entire", "hooks", "baulog", hook_name],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=env,
            )
            if background:
                proc.stdin.write(payload)
                proc.stdin.close()
                # Entire creates the checkpoint; let it finish in the background
            else:
                proc.communicate(input=payload, timeout=30)
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            pass
