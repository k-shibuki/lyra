"""Tests for get_materials Tool outputSchema integrity.

Validates that the MCP Tool schema matches the actual implementation output,
preventing schema validation failures and client-side issues.

Per Sb_CITATION_NETWORK.md 10.4.1: Schema alignment for get_materials.

## Test Perspectives Table

| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---------|----------------------|--------------------------------------|-----------------|-------|
| TC-SCHEMA-N-01 | Tool(get_materials).outputSchema | Equivalence – normal | citation_network property exists and is optional | Wiring (contract) |
| TC-SCHEMA-N-02 | evidence_graph.edges[].relation | Equivalence – normal | enum contains evidence_source | Regression guard |
| TC-SCHEMA-N-03 | evidence_graph.nodes/items | Equivalence – normal | node_type and obj_id properties exist | nodes structure |
| TC-SCHEMA-N-04 | evidence_graph.stats | Equivalence – normal | stats property exists | Stats structure |
| TC-SCHEMA-A-01 | relation enum values | Negative – coverage | enum contains exactly 5 values | No unknown values |
| TC-SCHEMA-A-02 | citation_count/year types | Boundary – NULL | types include null for fault tolerance | User-selected policy |
| TC-SCHEMA-B-01 | evidence_graph in outputSchema | Boundary – optional | type includes null (not required) | Omission allowed |
| TC-SCHEMA-B-02 | citation_network in outputSchema | Boundary – optional | type includes null (not required) | Omission allowed |
"""

from typing import TYPE_CHECKING, Any

import pytest

pytestmark = pytest.mark.unit

if TYPE_CHECKING:
    pass


def _get_get_materials_tool() -> Any:
    """Get the get_materials Tool definition from server.py.

    Returns:
        Tool object with inputSchema and outputSchema.
    """
    from src.mcp.server import TOOLS

    for tool in TOOLS:
        if tool.name == "get_materials":
            return tool
    raise AssertionError("get_materials tool not found in TOOLS list")


def _get_output_schema() -> dict[str, Any]:
    """Get the outputSchema dict from get_materials Tool."""
    tool = _get_get_materials_tool()
    schema = tool.outputSchema
    assert isinstance(schema, dict), "outputSchema must be a dict"
    return schema


class TestCitationNetworkSchema:
    """Tests for citation_network presence in outputSchema."""

    def test_citation_network_property_exists(self) -> None:
        """TC-SCHEMA-N-01: citation_network property exists in outputSchema.

        // Given: get_materials Tool definition
        // When: Inspecting outputSchema.properties
        // Then: citation_network key exists
        """
        # Given
        schema = _get_output_schema()

        # When
        properties = schema.get("properties", {})

        # Then
        assert "citation_network" in properties, (
            "citation_network property missing from outputSchema. "
            "This will cause schema validation failures for include_citations=true responses."
        )

    def test_citation_network_is_optional(self) -> None:
        """TC-SCHEMA-B-02: citation_network is optional (nullable, not required).

        // Given: get_materials Tool outputSchema
        // When: Checking citation_network type
        // Then: type includes null or is not in required
        """
        # Given
        schema = _get_output_schema()

        # When
        cn_schema = schema.get("properties", {}).get("citation_network", {})
        cn_type = cn_schema.get("type", "object")
        required = schema.get("required", [])

        # Then
        is_nullable = isinstance(cn_type, list) and "null" in cn_type
        not_required = "citation_network" not in required
        assert is_nullable or not_required, (
            "citation_network must be optional (nullable or not required) "
            "since include_citations=false should not return it."
        )

    def test_source_pages_nullable_fields(self) -> None:
        """TC-SCHEMA-A-02: citation_count and year allow null for fault tolerance.

        // Given: citation_network.source_pages schema
        // When: Checking citation_count and year types
        // Then: Both types include null (["integer", "null"])
        """
        # Given
        schema = _get_output_schema()

        # When
        cn_schema = schema.get("properties", {}).get("citation_network", {})
        source_pages = cn_schema.get("properties", {}).get("source_pages", {})
        items = source_pages.get("items", {})
        item_props = items.get("properties", {})

        citation_count_type = item_props.get("citation_count", {}).get("type")
        year_type = item_props.get("year", {}).get("type")

        # Then
        assert isinstance(citation_count_type, list) and "null" in citation_count_type, (
            "citation_count must allow null for fault tolerance when paper_metadata is missing"
        )
        assert isinstance(year_type, list) and "null" in year_type, (
            "year must allow null for fault tolerance when paper_metadata is missing"
        )


class TestEvidenceGraphSchema:
    """Tests for evidence_graph schema structure."""

    def test_evidence_graph_is_optional(self) -> None:
        """TC-SCHEMA-B-01: evidence_graph is optional (nullable, not required).

        // Given: get_materials Tool outputSchema
        // When: Checking evidence_graph type
        // Then: type includes null or is not in required
        """
        # Given
        schema = _get_output_schema()

        # When
        eg_schema = schema.get("properties", {}).get("evidence_graph", {})
        eg_type = eg_schema.get("type", "object")
        required = schema.get("required", [])

        # Then
        is_nullable = isinstance(eg_type, list) and "null" in eg_type
        not_required = "evidence_graph" not in required
        assert is_nullable or not_required, (
            "evidence_graph must be optional (nullable or not required) "
            "since include_graph=false should not return it."
        )

    def test_relation_enum_includes_evidence_source(self) -> None:
        """TC-SCHEMA-N-02: relation enum includes evidence_source.

        // Given: evidence_graph.edges schema
        // When: Checking relation enum values
        // Then: evidence_source is in the enum
        """
        # Given
        schema = _get_output_schema()

        # When
        eg_schema = schema.get("properties", {}).get("evidence_graph", {})
        edges = eg_schema.get("properties", {}).get("edges", {})
        items = edges.get("items", {})
        relation = items.get("properties", {}).get("relation", {})
        enum_values = relation.get("enum", [])

        # Then
        assert "evidence_source" in enum_values, (
            "evidence_source missing from relation enum. "
            "Phase 2 derived Claim->Page edges will fail schema validation."
        )

    def test_relation_enum_has_all_expected_values(self) -> None:
        """TC-SCHEMA-A-01: relation enum contains exactly the expected values.

        // Given: evidence_graph.edges schema
        // When: Checking relation enum values
        // Then: enum contains exactly supports, refutes, neutral, cites, evidence_source
        """
        # Given
        schema = _get_output_schema()

        # When
        eg_schema = schema.get("properties", {}).get("evidence_graph", {})
        edges = eg_schema.get("properties", {}).get("edges", {})
        items = edges.get("items", {})
        relation = items.get("properties", {}).get("relation", {})
        enum_values = set(relation.get("enum", []))

        # Then
        expected = {"supports", "refutes", "neutral", "cites", "evidence_source"}
        assert enum_values == expected, (
            f"relation enum mismatch. Expected {expected}, got {enum_values}. "
            "Unknown values may cause validation errors."
        )

    def test_nodes_schema_has_node_type_and_obj_id(self) -> None:
        """TC-SCHEMA-N-03: nodes schema includes node_type and obj_id properties.

        // Given: evidence_graph.nodes schema
        // When: Checking node item properties
        // Then: node_type and obj_id exist (matching EvidenceGraph.to_dict())
        """
        # Given
        schema = _get_output_schema()

        # When
        eg_schema = schema.get("properties", {}).get("evidence_graph", {})
        nodes = eg_schema.get("properties", {}).get("nodes", {})
        items = nodes.get("items", {})
        item_props = items.get("properties", {})

        # Then
        assert "node_type" in item_props, (
            "node_type property missing from nodes schema. "
            "EvidenceGraph.to_dict() uses node_type, not type."
        )
        assert "obj_id" in item_props, (
            "obj_id property missing from nodes schema. "
            "EvidenceGraph.to_dict() includes obj_id for each node."
        )

    def test_stats_property_exists(self) -> None:
        """TC-SCHEMA-N-04: evidence_graph includes stats property.

        // Given: evidence_graph schema
        // When: Checking for stats property
        // Then: stats exists with expected nested properties
        """
        # Given
        schema = _get_output_schema()

        # When
        eg_schema = schema.get("properties", {}).get("evidence_graph", {})
        eg_props = eg_schema.get("properties", {})
        stats = eg_props.get("stats", {})
        stats_props = stats.get("properties", {})

        # Then
        assert "stats" in eg_props, (
            "stats property missing from evidence_graph. "
            "EvidenceGraph.to_dict() always includes stats."
        )
        assert "total_nodes" in stats_props, "total_nodes missing from stats"
        assert "total_edges" in stats_props, "total_edges missing from stats"
        assert "node_counts" in stats_props, "node_counts missing from stats"
        assert "edge_counts" in stats_props, "edge_counts missing from stats"


class TestEdgePropertiesSchema:
    """Tests for edge optional properties in schema."""

    def test_edge_id_property_exists_and_nullable(self) -> None:
        """Edge schema includes edge_id for feedback(edge_correct).

        // Given: evidence_graph.edges schema
        // When: Checking edge_id property
        // Then: edge_id exists and allows null
        """
        # Given
        schema = _get_output_schema()

        # When
        eg_schema = schema.get("properties", {}).get("evidence_graph", {})
        edges = eg_schema.get("properties", {}).get("edges", {})
        items = edges.get("items", {})
        edge_props = items.get("properties", {})
        edge_id = edge_props.get("edge_id", {})

        # Then
        assert "edge_id" in edge_props, "edge_id missing from edge properties"
        edge_id_type = edge_id.get("type")
        assert isinstance(edge_id_type, list) and "null" in edge_id_type, (
            "edge_id should be nullable for derived edges without DB IDs"
        )

    def test_citation_source_property_exists(self) -> None:
        """Edge schema includes citation_source for cites edges.

        // Given: evidence_graph.edges schema
        // When: Checking citation_source property
        // Then: citation_source exists
        """
        # Given
        schema = _get_output_schema()

        # When
        eg_schema = schema.get("properties", {}).get("evidence_graph", {})
        edges = eg_schema.get("properties", {}).get("edges", {})
        items = edges.get("items", {})
        edge_props = items.get("properties", {})

        # Then
        assert "citation_source" in edge_props, (
            "citation_source missing from edge properties. "
            "cites edges from academic APIs include this field."
        )


class TestLoadSchemaHelper:
    """Tests for _load_schema helper function (10.4.2c).

    ## Test Perspectives Table

    | Case ID | Input / Precondition | Perspective | Expected Result | Notes |
    |---------|----------------------|-------------|-----------------|-------|
    | TC-SCH-N-01 | _load_schema("get_materials") | Normal | JSON dict returned | Wiring |
    | TC-SCH-N-02 | get_materials Tool.outputSchema | Normal | Matches JSON file | Contract |
    | TC-SCH-A-01 | _load_schema("nonexistent") | Negative | FileNotFoundError | Error handling |
    """

    def test_load_schema_returns_dict(self) -> None:
        """TC-SCH-N-01: _load_schema returns parsed JSON dict.

        // Given: A valid schema name
        // When: _load_schema is called
        // Then: Returns a dict with expected structure
        """
        from src.mcp.server import _load_schema

        # Given
        schema_name = "get_materials"

        # When
        schema = _load_schema(schema_name)

        # Then
        assert isinstance(schema, dict)
        assert "type" in schema, "Schema should have 'type' key"
        assert "properties" in schema, "Schema should have 'properties' key"

    def test_loaded_schema_matches_tool_output_schema(self) -> None:
        """TC-SCH-N-02: get_materials Tool outputSchema matches JSON file.

        // Given: get_materials Tool definition
        // When: Comparing Tool.outputSchema to _load_schema result
        // Then: They are identical (single source of truth)
        """
        import json
        from pathlib import Path

        from src.mcp.server import TOOLS

        # Given
        tool = None
        for t in TOOLS:
            if t.name == "get_materials":
                tool = t
                break
        assert tool is not None

        # When: Load schema from JSON file directly
        schema_path = (
            Path(__file__).parent.parent / "src" / "mcp" / "schemas" / "get_materials.json"
        )
        with open(schema_path) as f:
            json_schema = json.load(f)

        # Then: Tool.outputSchema matches JSON file
        assert tool.outputSchema == json_schema, (
            "Tool.outputSchema diverged from JSON file. "
            "This indicates _load_schema is not being used correctly."
        )

    def test_load_schema_file_not_found(self) -> None:
        """TC-SCH-A-01: _load_schema raises FileNotFoundError for missing schema.

        // Given: A nonexistent schema name
        // When: _load_schema is called
        // Then: FileNotFoundError is raised
        """
        from src.mcp.server import _load_schema

        # Given
        nonexistent = "nonexistent_schema_xyz123"

        # When/Then
        with pytest.raises(FileNotFoundError):
            _load_schema(nonexistent)

    def test_load_schema_for_all_existing_schemas(self) -> None:
        """Verify _load_schema works for all existing schema files.

        // Given: All JSON files in schemas directory
        // When: Loading each schema
        // Then: All parse successfully as dicts
        """
        from pathlib import Path

        from src.mcp.server import _load_schema

        # Given: List all schema files
        schemas_dir = Path(__file__).parent.parent / "src" / "mcp" / "schemas"
        schema_files = list(schemas_dir.glob("*.json"))

        # Then: All should load successfully
        for schema_file in schema_files:
            schema_name = schema_file.stem
            schema = _load_schema(schema_name)
            assert isinstance(schema, dict), f"Schema {schema_name} should be a dict"
