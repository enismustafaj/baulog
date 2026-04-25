"""Markdown parsing for property context documents."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from context_engine.models import (
    MarkdownSection,
    PropertyBuildingContext,
    PropertyContext,
    PropertyUnitContext,
)


HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


@dataclass
class _OutlineNode:
    """Small indentation outline node used for property context Markdown."""

    key: str
    value: str = ""
    indent: int = 0
    line_number: int = 0
    children: list["_OutlineNode"] = field(default_factory=list)


@dataclass
class _HeadingNode:
    """Markdown heading node used for property context Markdown."""

    title: str
    level: int
    line_number: int = 0
    content: list[str] = field(default_factory=list)
    children: list["_HeadingNode"] = field(default_factory=list)


class MarkdownParser:
    """Parse property Markdown documents."""

    def parse_file(self, markdown_path: str | Path) -> list[MarkdownSection]:
        """Parse a Markdown file into sections."""
        path = Path(markdown_path)
        return self.parse(path.read_text(encoding="utf-8"))

    def parse_property_file(self, markdown_path: str | Path) -> PropertyContext:
        """Parse one property Markdown file into structured property context."""
        path = Path(markdown_path)
        property_context = self.parse_property(path.read_text(encoding="utf-8"))
        property_context.markdown_path = str(path)
        return property_context

    def parse_property(self, markdown: str) -> PropertyContext:
        """Parse the heading-based property Markdown format.

        Expected shape:

        # property
        ## insurance
        ## maintanance
        ## buildings:
        ### haus1
        #### maintenance
        #### rent
        #### units:
        ##### aprt1
        ###### maintenance
        ###### rent
        ###### tenant
        """
        root = self._parse_heading_tree(markdown)
        property_node = self._first_heading(root, level=1)
        if property_node is None:
            raise ValueError("Property Markdown must start with a level 1 property heading")

        property_context = PropertyContext(name=self._clean_heading(property_node.title))
        self._apply_property_heading_children(property_context, property_node.children)
        return property_context

    def parse(self, markdown: str) -> list[MarkdownSection]:
        """Parse Markdown content into heading-based sections."""
        lines = markdown.splitlines()
        sections: list[MarkdownSection] = []
        stack: list[tuple[int, str]] = []
        current_title = "Document"
        current_level = 0
        current_start = 1
        current_content: list[str] = []
        current_path: list[str] = []

        line_index = 0
        if lines and lines[0].strip() == "---":
            closing_index = self._find_front_matter_end(lines)
            if closing_index is not None:
                front_matter = "\n".join(lines[1:closing_index])
                sections.append(
                    MarkdownSection(
                        title="Front Matter",
                        level=0,
                        content=front_matter,
                        start_line=1,
                        end_line=closing_index + 1,
                        path=["Front Matter"],
                        section_type="front_matter",
                    )
                )
                line_index = closing_index + 1
                current_start = line_index + 1

        while line_index < len(lines):
            line = lines[line_index]
            heading_match = HEADING_RE.match(line)

            if heading_match:
                if current_content or current_title != "Document":
                    sections.append(
                        MarkdownSection(
                            title=current_title,
                            level=current_level,
                            content="\n".join(current_content).strip(),
                            start_line=current_start,
                            end_line=line_index,
                            path=current_path or [current_title],
                        )
                    )

                current_level = len(heading_match.group(1))
                current_title = heading_match.group(2).strip()
                stack = [item for item in stack if item[0] < current_level]
                stack.append((current_level, current_title))
                current_path = [title for _, title in stack]
                current_start = line_index + 1
                current_content = [line]
            else:
                current_content.append(line)

            line_index += 1

        if current_content or not sections:
            sections.append(
                MarkdownSection(
                    title=current_title,
                    level=current_level,
                    content="\n".join(current_content).strip(),
                    start_line=current_start,
                    end_line=len(lines),
                    path=current_path or [current_title],
                )
            )

        return [
            section
            for section in sections
            if section.content or section.section_type == "front_matter"
        ]

    def _find_front_matter_end(self, lines: list[str]) -> int | None:
        """Return the closing line index for YAML-style front matter."""
        for index in range(1, len(lines)):
            if lines[index].strip() == "---":
                return index
        return None

    def _parse_heading_tree(self, markdown: str) -> _HeadingNode:
        """Parse Markdown headings and their content into a tree."""
        root = _HeadingNode(title="Document", level=0)
        stack: list[_HeadingNode] = [root]

        for line_number, line in enumerate(markdown.splitlines(), start=1):
            heading_match = HEADING_RE.match(line)
            if heading_match:
                level = len(heading_match.group(1))
                node = _HeadingNode(
                    title=heading_match.group(2).strip(),
                    level=level,
                    line_number=line_number,
                )
                while stack and level <= stack[-1].level:
                    stack.pop()
                stack[-1].children.append(node)
                stack.append(node)
            elif stack:
                stack[-1].content.append(line)

        return root

    def _first_heading(
        self,
        root: _HeadingNode,
        level: int,
    ) -> _HeadingNode | None:
        """Return the first heading at the requested level."""
        for child in root.children:
            if child.level == level:
                return child
        return None

    def _apply_property_heading_children(
        self,
        property_context: PropertyContext,
        children: list[_HeadingNode],
    ) -> None:
        for child in children:
            normalized_key = self._normalize_key(child.title)

            if normalized_key == "insurance":
                property_context.insurance = self._section_items(child)
            elif normalized_key in {"maintenance", "maintanance"}:
                property_context.maintenance = self._section_items(child)
            elif normalized_key == "buildings":
                property_context.buildings.extend(
                    self._parse_building_heading(node) for node in child.children
                )
            else:
                property_context.attributes[child.title] = self._section_items(child)

    def _parse_building_heading(self, node: _HeadingNode) -> PropertyBuildingContext:
        building = PropertyBuildingContext(name=self._clean_heading(node.title))
        for child in node.children:
            normalized_key = self._normalize_key(child.title)

            if normalized_key in {"maintenance", "maintanance"}:
                building.maintenance = self._section_items(child)
            elif normalized_key == "rent":
                building.rent = self._section_items(child)
            elif normalized_key == "units":
                building.units.extend(
                    self._parse_unit_heading(unit) for unit in child.children
                )
            else:
                building.attributes[child.title] = self._section_items(child)

        return building

    def _parse_unit_heading(self, node: _HeadingNode) -> PropertyUnitContext:
        unit = PropertyUnitContext(name=self._clean_heading(node.title))
        for child in node.children:
            normalized_key = self._normalize_key(child.title)

            if normalized_key in {"maintenance", "maintanance"}:
                unit.maintenance = self._section_items(child)
            elif normalized_key == "rent":
                unit.rent = self._section_items(child)
            elif normalized_key == "tenant":
                unit.tenant = "\n".join(self._section_items(child)).strip()
            else:
                unit.attributes[child.title] = self._section_items(child)

        return unit

    def _section_items(self, node: _HeadingNode) -> list[str]:
        """Return cleaned non-empty lines under a heading as list items."""
        items: list[str] = []
        for line in node.content:
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("- "):
                stripped = stripped[2:].strip()
            items.append(stripped)
        return items

    def _parse_outline(self, markdown: str) -> _OutlineNode:
        """Parse indented Markdown/list lines into a shallow outline tree."""
        root = _OutlineNode(key="Document", indent=-1)
        stack: list[_OutlineNode] = [root]

        for line_number, raw_line in enumerate(markdown.splitlines(), start=1):
            if not raw_line.strip() or raw_line.strip() == "---":
                continue

            indent = len(raw_line.expandtabs(4)) - len(raw_line.expandtabs(4).lstrip())
            key, value = self._split_outline_line(raw_line.strip())
            if not key:
                continue

            node = _OutlineNode(
                key=key,
                value=value,
                indent=indent,
                line_number=line_number,
            )
            while stack and indent <= stack[-1].indent:
                stack.pop()
            stack[-1].children.append(node)
            stack.append(node)

        return root

    def _split_outline_line(self, stripped_line: str) -> tuple[str, str]:
        """Split an outline line into key/value parts."""
        line = stripped_line
        if line.startswith("- "):
            line = line[2:].strip()

        heading_match = HEADING_RE.match(line)
        if heading_match:
            line = heading_match.group(2).strip()

        if ":" not in line:
            return line.strip(), ""

        key, value = line.split(":", 1)
        return key.strip(), value.strip()

    def _first_content_node(self, root: _OutlineNode) -> _OutlineNode | None:
        """Return the first non-front-matter node."""
        for node in root.children:
            if node.key.lower() not in {"front matter", "metadata"}:
                return node
        return None

    def _apply_property_children(
        self,
        property_context: PropertyContext,
        children: list[_OutlineNode],
    ) -> None:
        for child in children:
            normalized_key = self._normalize_key(child.key)
            value = self._node_value(child)

            if normalized_key == "insurance":
                property_context.insurance = value
            elif normalized_key in {"maintenance", "maintanance"}:
                property_context.maintenance = value
            elif normalized_key == "buildings":
                property_context.buildings.extend(
                    self._parse_building_node(node) for node in child.children
                )
            else:
                property_context.attributes[child.key] = value

    def _parse_building_node(self, node: _OutlineNode) -> PropertyBuildingContext:
        building = PropertyBuildingContext(name=self._clean_heading(node.key))
        for child in node.children:
            normalized_key = self._normalize_key(child.key)
            value = self._node_value(child)

            if normalized_key in {"maintenance", "maintanance"}:
                building.maintenance = value
            elif normalized_key == "rent":
                building.rent = value
            elif normalized_key == "units":
                building.units.extend(
                    self._parse_unit_node(unit) for unit in child.children
                )
            else:
                building.attributes[child.key] = value

        return building

    def _parse_unit_node(self, node: _OutlineNode) -> PropertyUnitContext:
        unit = PropertyUnitContext(name=self._clean_heading(node.key))
        for child in node.children:
            normalized_key = self._normalize_key(child.key)
            value = self._node_value(child)

            if normalized_key in {"maintenance", "maintanance"}:
                unit.maintenance = value
            elif normalized_key == "rent":
                unit.rent = value
            elif normalized_key == "tenant":
                unit.tenant = value
            else:
                unit.attributes[child.key] = value

        return unit

    def _node_value(self, node: _OutlineNode) -> str:
        """Return a node's inline value or text represented by child leaf nodes."""
        if node.value:
            return node.value

        leaf_values = [
            child.value or child.key
            for child in node.children
            if not child.children
        ]
        return "\n".join(leaf_values).strip()

    def _normalize_key(self, key: str) -> str:
        """Normalize outline keys for matching."""
        return self._clean_heading(key).lower().replace(" ", "_")

    def _clean_heading(self, value: str) -> str:
        """Clean Markdown/list syntax from a heading-like value."""
        return value.strip().strip(":").strip()
