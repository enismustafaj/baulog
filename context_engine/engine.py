"""File-system backed context engine for property Markdown files."""

from __future__ import annotations

from pathlib import Path

from context_engine.markdown_parser import MarkdownParser
from context_engine.models import (
    PropertyBuildingContext,
    PropertyContext,
    PropertyUnitContext,
)


class ContextEngine:
    """Load property context directly from Markdown files in a repo."""

    def __init__(
        self,
        repo_path: str | Path = ".",
        property_glob: str = "**/*.md",
    ):
        """Initialize the context engine.

        Args:
            repo_path: Git repo or filesystem root that contains property files.
            property_glob: Glob used to discover property Markdown files.
        """
        self.repo_path = Path(repo_path)
        self.property_glob = property_glob
        self.parser = MarkdownParser()

    def list_properties(self) -> list[PropertyContext]:
        """Load all parseable property Markdown files under the repo path."""
        properties: list[PropertyContext] = []
        for markdown_path in self._iter_markdown_files():
            try:
                properties.append(self.parser.parse_property_file(markdown_path))
            except ValueError:
                continue

        return properties

    def get_property(self, property_name: str) -> PropertyContext | None:
        """Find a property by name."""
        normalized_name = self._normalize(property_name)
        for property_context in self.list_properties():
            if self._normalize(property_context.name) == normalized_name:
                return property_context

        return None

    def find_properties(self, query: str, limit: int = 20) -> list[PropertyContext]:
        """Find properties by property, building, unit, or attribute text."""
        normalized_query = self._normalize(query)
        matches = [
            property_context
            for property_context in self.list_properties()
            if normalized_query
            in self._normalize(self._property_search_text(property_context))
        ]
        return matches[:limit]

    def find_buildings(
        self,
        query: str,
        property_name: str | None = None,
        limit: int = 20,
    ) -> list[PropertyBuildingContext]:
        """Find buildings by name or content."""
        normalized_query = self._normalize(query)
        matches: list[PropertyBuildingContext] = []

        for property_context in self._properties_for_scope(property_name):
            for building in property_context.buildings:
                if normalized_query in self._normalize(
                    self._building_search_text(building)
                ):
                    matches.append(building)
                    if len(matches) >= limit:
                        return matches

        return matches

    def get_building_units(
        self,
        property_name: str,
        building_name: str,
    ) -> list[PropertyUnitContext]:
        """Get units for a building in a property."""
        building = self.get_building(property_name, building_name)
        return building.units if building else []

    def get_building(
        self,
        property_name: str,
        building_name: str,
    ) -> PropertyBuildingContext | None:
        """Get a building by property and building name."""
        property_context = self.get_property(property_name)
        if property_context is None:
            return None

        normalized_name = self._normalize(building_name)
        for building in property_context.buildings:
            if self._normalize(building.name) == normalized_name:
                return building

        return None

    def find_building_units(
        self,
        query: str,
        property_name: str | None = None,
        building_name: str | None = None,
        limit: int = 20,
    ) -> list[PropertyUnitContext]:
        """Find units by name, tenant, rent, maintenance, or custom attributes."""
        normalized_query = self._normalize(query)
        matches: list[PropertyUnitContext] = []

        for property_context in self._properties_for_scope(property_name):
            for building in property_context.buildings:
                if (
                    building_name
                    and self._normalize(building.name) != self._normalize(building_name)
                ):
                    continue

                for unit in building.units:
                    if normalized_query in self._normalize(
                        self._unit_search_text(unit)
                    ):
                        matches.append(unit)
                        if len(matches) >= limit:
                            return matches

        return matches

    def _properties_for_scope(self, property_name: str | None) -> list[PropertyContext]:
        """Return either one named property or all properties."""
        if property_name:
            property_context = self.get_property(property_name)
            return [property_context] if property_context else []

        return self.list_properties()

    def _iter_markdown_files(self) -> list[Path]:
        """Return Markdown files from the repo path, skipping hidden/vendor dirs."""
        ignored_dirs = {".git", ".venv", "__pycache__", "node_modules"}
        paths: list[Path] = []

        for path in self.repo_path.glob(self.property_glob):
            if not path.is_file():
                continue
            if any(part in ignored_dirs or part.startswith(".") for part in path.parts):
                continue
            paths.append(path)

        return sorted(paths)

    def _property_search_text(self, property_context: PropertyContext) -> str:
        parts = [
            property_context.name,
            self._join_items(property_context.insurance),
            self._join_items(property_context.maintenance),
            str(property_context.attributes),
        ]
        for building in property_context.buildings:
            parts.append(self._building_search_text(building))
        return "\n".join(parts)

    def _building_search_text(self, building: PropertyBuildingContext) -> str:
        parts = [
            building.name,
            self._join_items(building.maintenance),
            self._join_items(building.rent),
            str(building.attributes),
        ]
        parts.extend(self._unit_search_text(unit) for unit in building.units)
        return "\n".join(parts)

    def _unit_search_text(self, unit: PropertyUnitContext) -> str:
        return "\n".join(
            [
                unit.name,
                self._join_items(unit.maintenance),
                self._join_items(unit.rent),
                unit.tenant,
                str(unit.attributes),
            ]
        )

    def _join_items(self, items: list[str]) -> str:
        """Flatten repeated context items for search."""
        return "\n".join(items)

    def _normalize(self, value: str) -> str:
        """Normalize text for simple filesystem-backed matching."""
        return " ".join(str(value).casefold().split())


context_engine = ContextEngine()
