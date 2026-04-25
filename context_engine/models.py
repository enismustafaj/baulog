"""Data models for the building context engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class MarkdownSection:
    """A parsed Markdown section.

    Section definitions can become stricter later. For now, sections are based
    on Markdown headings, with front matter captured as its own section when
    present.
    """

    title: str
    level: int
    content: str
    start_line: int
    end_line: int
    path: list[str] = field(default_factory=list)
    section_type: str = "heading"


@dataclass
class PropertyUnitContext:
    """Unit context parsed from a property Markdown file."""

    name: str
    maintenance: list[str] = field(default_factory=list)
    rent: list[str] = field(default_factory=list)
    tenant: str = ""
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass
class PropertyBuildingContext:
    """Building context parsed from a property Markdown file."""

    name: str
    maintenance: list[str] = field(default_factory=list)
    rent: list[str] = field(default_factory=list)
    units: list[PropertyUnitContext] = field(default_factory=list)
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass
class PropertyContext:
    """Property context parsed from a single Markdown file."""

    name: str
    insurance: list[str] = field(default_factory=list)
    maintenance: list[str] = field(default_factory=list)
    buildings: list[PropertyBuildingContext] = field(default_factory=list)
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass
class BuildingMetadata:
    """Metadata index row for a building Markdown document."""

    building_id: str
    name: str
    markdown_path: str
    external_id: str | None = None
    address: str | None = None
    building_type: str | None = None
    tags: list[str] = field(default_factory=list)
    attributes: dict[str, Any] = field(default_factory=dict)
    content_hash: str | None = None
    created_at: str | None = None


@dataclass
class BuildingUnitMetadata:
    """Static metadata index row for a unit within a building."""

    unit_id: str
    building_id: str
    name: str
    unit_number: str | None = None
    floor: str | None = None
    unit_type: str | None = None
    area_sqm: float | None = None
    tags: list[str] = field(default_factory=list)
    attributes: dict[str, Any] = field(default_factory=dict)
    created_at: str | None = None
