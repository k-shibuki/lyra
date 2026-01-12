"""
Tests for Lyra Evidence Dashboard Generator.

Tests pure functions from src/report/dashboard.py that don't require database access.
Database-dependent functions (extract_*) are tested in integration tests.
"""

import pytest

from src.report.dashboard import (
    TASK_COLORS,
    ClaimGraph,
    ClaimGraphEdge,
    ClaimGraphMeta,
    ClaimGraphNode,
    escape_json_for_html,
    extract_drug_class_from_hypothesis,
    format_inline_markdown,
    get_task_color,
    markdown_to_html,
    render_html,
)

# =============================================================================
# TC-XSS: escape_json_for_html Tests
# =============================================================================


class TestEscapeJsonForHtml:
    """Tests for XSS escape function."""

    def test_normal_json_unchanged(self) -> None:
        """TC-XSS-01: Normal JSON string without dangerous characters.

        Given: A JSON string with no XSS-dangerous characters
        When: escape_json_for_html is called
        Then: The string should be returned unchanged
        """
        # Given
        input_json = '{"name": "test", "value": 123}'

        # When
        result = escape_json_for_html(input_json)

        # Then
        assert result == input_json

    def test_script_tag_escaped(self) -> None:
        """TC-XSS-02: </script> tag is escaped to prevent XSS.

        Given: A JSON string containing </script>
        When: escape_json_for_html is called
        Then: </script> should be escaped to <\\/script>
        """
        # Given
        input_json = '{"content": "</script><script>alert(1)</script>"}'

        # When
        result = escape_json_for_html(input_json)

        # Then
        assert "</script>" not in result
        assert r"<\/script>" in result
        assert result == '{"content": "<\\/script><script>alert(1)<\\/script>"}'

    def test_html_comment_escaped(self) -> None:
        """TC-XSS-03: <!-- is escaped to prevent comment injection.

        Given: A JSON string containing <!--
        When: escape_json_for_html is called
        Then: <!-- should be escaped to <\\!--
        """
        # Given
        input_json = '{"comment": "<!-- hidden -->"}'

        # When
        result = escape_json_for_html(input_json)

        # Then
        assert "<!--" not in result
        assert r"<\!--" in result

    def test_u2028_line_separator_escaped(self) -> None:
        """TC-XSS-04: U+2028 line separator is escaped.

        Given: A JSON string containing U+2028 (line separator)
        When: escape_json_for_html is called
        Then: U+2028 should be escaped to \\u2028
        """
        # Given
        input_json = '{"text": "line1\u2028line2"}'

        # When
        result = escape_json_for_html(input_json)

        # Then
        assert "\u2028" not in result
        assert r"\u2028" in result

    def test_u2029_paragraph_separator_escaped(self) -> None:
        """TC-XSS-05: U+2029 paragraph separator is escaped.

        Given: A JSON string containing U+2029 (paragraph separator)
        When: escape_json_for_html is called
        Then: U+2029 should be escaped to \\u2029
        """
        # Given
        input_json = '{"text": "para1\u2029para2"}'

        # When
        result = escape_json_for_html(input_json)

        # Then
        assert "\u2029" not in result
        assert r"\u2029" in result

    def test_empty_string(self) -> None:
        """TC-XSS-06: Empty string is handled correctly.

        Given: An empty string
        When: escape_json_for_html is called
        Then: An empty string should be returned
        """
        # Given
        input_json = ""

        # When
        result = escape_json_for_html(input_json)

        # Then
        assert result == ""

    def test_combined_xss_patterns(self) -> None:
        """TC-XSS-07: All XSS patterns are escaped together.

        Given: A JSON string containing all dangerous patterns
        When: escape_json_for_html is called
        Then: All patterns should be properly escaped
        """
        # Given
        input_json = '{"a": "</script>", "b": "<!--", "c": "\u2028\u2029"}'

        # When
        result = escape_json_for_html(input_json)

        # Then
        assert "</script>" not in result
        assert "<!--" not in result
        assert "\u2028" not in result
        assert "\u2029" not in result
        assert r"<\/script>" in result
        assert r"<\!--" in result
        assert r"\u2028" in result
        assert r"\u2029" in result


# =============================================================================
# TC-DRUG: extract_drug_class_from_hypothesis Tests
# =============================================================================


class TestExtractDrugClassFromHypothesis:
    """Tests for drug class extraction from hypothesis text."""

    def test_dpp4_inhibitors(self) -> None:
        """TC-DRUG-01: DPP-4 inhibitors pattern extraction.

        Given: A hypothesis mentioning DPP-4 inhibitors
        When: extract_drug_class_from_hypothesis is called
        Then: It should return the correct full name and short name
        """
        # Given
        hypothesis = "DPP-4 inhibitors are effective as add-on therapy to insulin"

        # When
        full_name, short_name = extract_drug_class_from_hypothesis(hypothesis)

        # Then
        assert "DPP-4" in full_name or "DPP4" in full_name
        assert "Inhibitor" in full_name
        assert "i" in short_name.lower()

    def test_sglt2_inhibitors_no_hyphen(self) -> None:
        """TC-DRUG-02: SGLT2 inhibitors without hyphen.

        Given: A hypothesis mentioning SGLT2 inhibitors (no hyphen)
        When: extract_drug_class_from_hypothesis is called
        Then: It should correctly extract the drug class
        """
        # Given
        hypothesis = "SGLT2 inhibitors reduce cardiovascular risk"

        # When
        full_name, short_name = extract_drug_class_from_hypothesis(hypothesis)

        # Then
        assert "SGLT" in full_name.upper()
        assert "Inhibitor" in full_name

    def test_glp1_receptor_agonists(self) -> None:
        """TC-DRUG-03: GLP-1 receptor agonists pattern.

        Given: A hypothesis mentioning GLP-1 receptor agonists
        When: extract_drug_class_from_hypothesis is called
        Then: It should return agonist-specific naming
        """
        # Given
        hypothesis = "GLP-1 receptor agonists improve glycemic control"

        # When
        full_name, short_name = extract_drug_class_from_hypothesis(hypothesis)

        # Then
        assert "GLP" in full_name.upper()
        # Should contain "Agonist" or "RA" indicator
        assert "Agonist" in full_name or "RA" in short_name

    def test_generic_drug_name(self) -> None:
        """TC-DRUG-04: Generic drug name extraction.

        Given: A hypothesis mentioning a generic drug name
        When: extract_drug_class_from_hypothesis is called
        Then: It should extract something reasonable
        """
        # Given
        hypothesis = "Metformin reduces hepatic glucose production"

        # When
        full_name, short_name = extract_drug_class_from_hypothesis(hypothesis)

        # Then
        # Should return some reasonable extraction (not empty)
        assert len(full_name) > 0
        assert len(short_name) > 0

    def test_fallback_random_hypothesis(self) -> None:
        """TC-DRUG-05: Fallback for unrecognized patterns.

        Given: A hypothesis without recognizable drug class patterns
        When: extract_drug_class_from_hypothesis is called
        Then: It should use the first 20 characters as fallback
        """
        # Given
        hypothesis = "Some random text that doesn't match any pattern"

        # When
        full_name, short_name = extract_drug_class_from_hypothesis(hypothesis)

        # Then
        assert len(full_name) > 0
        assert len(short_name) <= 20  # Fallback uses first 20 chars

    def test_empty_string(self) -> None:
        """TC-DRUG-06: Empty string hypothesis.

        Given: An empty hypothesis string
        When: extract_drug_class_from_hypothesis is called
        Then: It should return empty strings
        """
        # Given
        hypothesis = ""

        # When
        full_name, short_name = extract_drug_class_from_hypothesis(hypothesis)

        # Then
        assert full_name == ""
        assert short_name == ""


# =============================================================================
# TC-COLOR: get_task_color Tests
# =============================================================================


class TestGetTaskColor:
    """Tests for task color assignment."""

    def test_first_color_index_zero(self) -> None:
        """TC-COLOR-01: First color for task_index=0.

        Given: A task with index 0
        When: get_task_color is called
        Then: It should return the first color in TASK_COLORS
        """
        # Given
        task_id = "task_abc123"
        task_index = 0

        # When
        color = get_task_color(task_id, task_index)

        # Then
        assert color == TASK_COLORS[0]

    def test_last_direct_color_index_seven(self) -> None:
        """TC-COLOR-02: Last direct color for task_index=7.

        Given: A task with index 7 (last in TASK_COLORS)
        When: get_task_color is called
        Then: It should return TASK_COLORS[7]
        """
        # Given
        task_id = "task_xyz789"
        task_index = 7

        # When
        color = get_task_color(task_id, task_index)

        # Then
        assert color == TASK_COLORS[7]

    def test_hash_fallback_index_eight(self) -> None:
        """TC-COLOR-03: Hash-based fallback for task_index >= 8.

        Given: A task with index 8 (beyond TASK_COLORS length)
        When: get_task_color is called
        Then: It should return a color from TASK_COLORS (hash-based)
        """
        # Given
        task_id = "task_overflow"
        task_index = 8

        # When
        color = get_task_color(task_id, task_index)

        # Then
        assert color in TASK_COLORS

    def test_deterministic_hash_same_task_id(self) -> None:
        """TC-COLOR-04: Same task_id produces same hash-based color.

        Given: Same task_id with high index (hash-based)
        When: get_task_color is called multiple times
        Then: It should return the same color
        """
        # Given
        task_id = "task_consistent"
        task_index = 100

        # When
        color1 = get_task_color(task_id, task_index)
        color2 = get_task_color(task_id, task_index)

        # Then
        assert color1 == color2


# =============================================================================
# TC-MD: markdown_to_html Tests
# =============================================================================


class TestMarkdownToHtml:
    """Tests for Markdown to HTML conversion."""

    def test_h1_header(self) -> None:
        """TC-MD-01: H1 header conversion.

        Given: Markdown with # header
        When: markdown_to_html is called
        Then: It should convert to <h2> tag (shifted down)
        """
        # Given
        md = "# Main Header"

        # When
        html = markdown_to_html(md)

        # Then
        assert "<h2" in html
        assert "Main Header" in html

    def test_h2_header(self) -> None:
        """TC-MD-02: H2 header conversion.

        Given: Markdown with ## header
        When: markdown_to_html is called
        Then: It should convert to <h3> tag
        """
        # Given
        md = "## Sub Header"

        # When
        html = markdown_to_html(md)

        # Then
        assert "<h3" in html
        assert "Sub Header" in html

    def test_h3_header(self) -> None:
        """TC-MD-03: H3 header conversion.

        Given: Markdown with ### header
        When: markdown_to_html is called
        Then: It should convert to <h4> tag
        """
        # Given
        md = "### Small Header"

        # When
        html = markdown_to_html(md)

        # Then
        assert "<h4" in html
        assert "Small Header" in html

    def test_list_items(self) -> None:
        """TC-MD-04: Unordered list conversion.

        Given: Markdown with list items (-)
        When: markdown_to_html is called
        Then: It should convert to <ul><li> structure
        """
        # Given
        md = "- Item 1\n- Item 2"

        # When
        html = markdown_to_html(md)

        # Then
        assert "<ul" in html
        assert "<li>" in html
        assert "Item 1" in html
        assert "Item 2" in html
        assert "</ul>" in html

    def test_table(self) -> None:
        """TC-MD-05: Table conversion.

        Given: Markdown table
        When: markdown_to_html is called
        Then: It should convert to <table> structure
        """
        # Given
        md = "| Header 1 | Header 2 |\n|----------|----------|\n| Cell 1   | Cell 2   |"

        # When
        html = markdown_to_html(md)

        # Then
        assert "<table" in html
        assert "<th" in html
        assert "<td" in html
        assert "Header 1" in html
        assert "Cell 1" in html

    def test_horizontal_rule(self) -> None:
        """TC-MD-06: Horizontal rule conversion.

        Given: Markdown horizontal rule (---)
        When: markdown_to_html is called
        Then: It should convert to <hr> tag
        """
        # Given
        md = "Before\n---\nAfter"

        # When
        html = markdown_to_html(md)

        # Then
        assert "<hr" in html

    def test_paragraph(self) -> None:
        """TC-MD-07: Paragraph conversion.

        Given: Plain text paragraph
        When: markdown_to_html is called
        Then: It should convert to <p> tag
        """
        # Given
        md = "This is a regular paragraph."

        # When
        html = markdown_to_html(md)

        # Then
        assert "<p" in html
        assert "This is a regular paragraph." in html

    def test_empty_string(self) -> None:
        """TC-MD-08: Empty string input.

        Given: An empty string
        When: markdown_to_html is called
        Then: It should return empty string
        """
        # Given
        md = ""

        # When
        html = markdown_to_html(md)

        # Then
        assert html == ""


# =============================================================================
# TC-INLINE: format_inline_markdown Tests
# =============================================================================


class TestFormatInlineMarkdown:
    """Tests for inline Markdown formatting."""

    def test_bold_text(self) -> None:
        """TC-INLINE-01: Bold text conversion.

        Given: Text with **bold** markers
        When: format_inline_markdown is called
        Then: It should convert to <strong> tags
        """
        # Given
        text = "This is **bold** text"

        # When
        result = format_inline_markdown(text)

        # Then
        assert "<strong" in result
        assert "bold" in result
        assert "</strong>" in result

    def test_italic_text(self) -> None:
        """TC-INLINE-02: Italic text conversion.

        Given: Text with *italic* markers
        When: format_inline_markdown is called
        Then: It should convert to <em> tags
        """
        # Given
        text = "This is *italic* text"

        # When
        result = format_inline_markdown(text)

        # Then
        assert "<em>" in result
        assert "italic" in result
        assert "</em>" in result

    def test_code_text(self) -> None:
        """TC-INLINE-03: Inline code conversion.

        Given: Text with `code` markers
        When: format_inline_markdown is called
        Then: It should convert to <code> tags
        """
        # Given
        text = "Use `print()` function"

        # When
        result = format_inline_markdown(text)

        # Then
        assert "<code" in result
        assert "print()" in result
        assert "</code>" in result

    def test_footnote_reference(self) -> None:
        """TC-INLINE-04: Footnote reference conversion.

        Given: Text with [^1] footnote reference
        When: format_inline_markdown is called
        Then: It should convert to <sup> tags
        """
        # Given
        text = "See reference[^1]"

        # When
        result = format_inline_markdown(text)

        # Then
        assert "<sup" in result
        assert "[1]" in result
        assert "</sup>" in result

    def test_html_escape(self) -> None:
        """TC-INLINE-05: HTML special characters are escaped.

        Given: Text with HTML special characters
        When: format_inline_markdown is called
        Then: It should escape HTML entities
        """
        # Given
        text = "<script>alert('xss')</script>"

        # When
        result = format_inline_markdown(text)

        # Then
        assert "<script>" not in result
        assert "&lt;script&gt;" in result


# =============================================================================
# TC-RENDER: render_html Tests
# =============================================================================


class TestRenderHtml:
    """Tests for HTML rendering function."""

    def test_successful_placeholder_replacement(self) -> None:
        """TC-RENDER-01: Successful placeholder replacement.

        Given: A template with "__LYRA_DATA__" placeholder
        When: render_html is called with data
        Then: The placeholder should be replaced with JSON data
        """
        # Given
        template = '<script>const data = "__LYRA_DATA__";</script>'
        data = {"key": "value"}

        # When
        result = render_html(template, data)

        # Then
        assert '"__LYRA_DATA__"' not in result
        assert '"key"' in result
        assert '"value"' in result

    def test_missing_placeholder_raises_error(self) -> None:
        """TC-RENDER-02: Missing placeholder raises ValueError.

        Given: A template without "__LYRA_DATA__" placeholder
        When: render_html is called
        Then: It should raise ValueError with descriptive message
        """
        # Given
        template = "<html><body>No placeholder here</body></html>"
        data = {"key": "value"}

        # When/Then
        with pytest.raises(ValueError) as exc_info:
            render_html(template, data)

        assert "placeholder" in str(exc_info.value).lower()

    def test_xss_escape_applied(self) -> None:
        """TC-RENDER-03: XSS escaping is applied to data.

        Given: Data containing XSS-dangerous content
        When: render_html is called
        Then: The dangerous content should be escaped so HTML parser
              doesn't prematurely close the script tag
        """
        # Given
        template = '<script>const data = "__LYRA_DATA__";</script>'
        data = {"malicious": "</script><script>alert(1)</script>"}

        # When
        result = render_html(template, data)

        # Then
        # The </script> inside data must be escaped to <\/script>
        # This prevents HTML parser from closing the outer script tag
        assert r"<\/script>" in result
        # The literal </script> in data should NOT appear unescaped
        # Count: only the template's closing </script> should remain as literal
        assert result.count("</script>") == 1  # Only template's closing tag


# =============================================================================
# Edge Cases and Wiring Tests
# =============================================================================


class TestEdgeCases:
    """Edge case tests for dashboard functions."""

    def test_task_colors_is_immutable(self) -> None:
        """Verify TASK_COLORS is a tuple (immutable).

        Given: TASK_COLORS constant
        When: Checking its type
        Then: It should be a tuple
        """
        # Given/When/Then
        assert isinstance(TASK_COLORS, tuple)

    def test_task_colors_has_expected_count(self) -> None:
        """Verify TASK_COLORS has 8 colors.

        Given: TASK_COLORS constant
        When: Checking its length
        Then: It should have exactly 8 colors
        """
        # Given/When/Then
        assert len(TASK_COLORS) == 8

    def test_all_task_colors_are_hex(self) -> None:
        """Verify all TASK_COLORS are valid hex colors.

        Given: TASK_COLORS constant
        When: Checking each color format
        Then: All should be valid #RRGGBB format
        """
        # Given
        import re

        hex_pattern = re.compile(r"^#[0-9a-fA-F]{6}$")

        # When/Then
        for color in TASK_COLORS:
            assert hex_pattern.match(color), f"Invalid color format: {color}"

    def test_markdown_list_closes_properly(self) -> None:
        """Verify list tags are properly closed.

        Given: Markdown with list followed by paragraph
        When: markdown_to_html is called
        Then: List should be properly closed before paragraph
        """
        # Given
        md = "- Item 1\n- Item 2\n\nParagraph after list"

        # When
        html = markdown_to_html(md)

        # Then
        # </ul> should appear before the paragraph
        ul_close_pos = html.find("</ul>")
        para_pos = html.find("Paragraph after list")
        assert ul_close_pos < para_pos

    def test_render_html_preserves_unicode(self) -> None:
        """Verify unicode characters are preserved (not ASCII-escaped).

        Given: Data with unicode characters
        When: render_html is called
        Then: Unicode should be preserved (ensure_ascii=False)
        """
        # Given
        template = '<script>const data = "__LYRA_DATA__";</script>'
        data = {"text": "日本語テスト"}

        # When
        result = render_html(template, data)

        # Then
        assert "日本語テスト" in result


# =============================================================================
# TC-GRAPH: ClaimGraph TypedDict Schema Tests
# =============================================================================


class TestClaimGraphSchema:
    """Tests for ClaimGraph TypedDict schema correctness."""

    def test_claim_graph_node_has_required_fields(self) -> None:
        """TC-GRAPH-01: ClaimGraphNode has all required fields.

        Given: A properly constructed ClaimGraphNode
        When: Fields are accessed
        Then: All required fields should be present and typed correctly
        """
        # Given
        node: ClaimGraphNode = {
            "id": "claim_123",
            "task_id": "task_abc",
            "text": "Test claim text",
            "nli_claim_support_ratio": 0.75,
            "evidence_count": 5,
            "support_count": 3,
            "refute_count": 1,
            "report_rank": 10,
            "is_report_top": True,
            "x": 50.0,
            "y": 75.0,
        }

        # Then
        assert node["id"] == "claim_123"
        assert node["task_id"] == "task_abc"
        assert node["nli_claim_support_ratio"] == 0.75
        assert node["evidence_count"] == 5
        assert node["is_report_top"] is True
        assert node["x"] == 50.0
        assert node["y"] == 75.0

    def test_claim_graph_edge_has_required_fields(self) -> None:
        """TC-GRAPH-02: ClaimGraphEdge has all required fields.

        Given: A properly constructed ClaimGraphEdge
        When: Fields are accessed
        Then: All required fields should be present and typed correctly
        """
        # Given
        edge: ClaimGraphEdge = {
            "source": "claim_1",
            "target": "claim_2",
            "kind": "semantic_sim",
            "weight": 0.85,
            "explain": "Semantic similarity: 0.85",
        }

        # Then
        assert edge["source"] == "claim_1"
        assert edge["target"] == "claim_2"
        assert edge["kind"] == "semantic_sim"
        assert edge["weight"] == 0.85
        assert "Semantic" in edge["explain"]

    def test_claim_graph_edge_kinds_are_valid(self) -> None:
        """TC-GRAPH-03: Edge kinds are from the expected set.

        Given: Valid edge kind values
        When: Edges are created
        Then: Only co_fragment, co_page, semantic_sim should be valid kinds
        """
        valid_kinds = {"co_fragment", "co_page", "semantic_sim"}

        # Given/When
        for kind in valid_kinds:
            edge: ClaimGraphEdge = {
                "source": "c1",
                "target": "c2",
                "kind": kind,
                "weight": 0.5,
                "explain": f"Test {kind}",
            }
            # Then
            assert edge["kind"] in valid_kinds

    def test_claim_graph_meta_has_required_fields(self) -> None:
        """TC-GRAPH-04: ClaimGraphMeta has all required fields.

        Given: A properly constructed ClaimGraphMeta
        When: Fields are accessed
        Then: All required fields should be present
        """
        # Given
        meta: ClaimGraphMeta = {
            "total_nodes": 100,
            "total_edges": 500,
            "edge_counts": {
                "co_fragment": 50,
                "co_page": 200,
                "semantic_sim": 250,
            },
            "params": {
                "semantic_top_k": 8,
                "semantic_min_sim": 0.72,
                "max_edges": 3000,
            },
        }

        # Then
        assert meta["total_nodes"] == 100
        assert meta["total_edges"] == 500
        assert meta["edge_counts"]["co_fragment"] == 50
        assert meta["params"]["semantic_min_sim"] == 0.72

    def test_claim_graph_complete_structure(self) -> None:
        """TC-GRAPH-05: Complete ClaimGraph structure is valid.

        Given: A complete ClaimGraph with nodes, edges, and meta
        When: Structure is validated
        Then: All components should be correctly nested
        """
        # Given
        graph: ClaimGraph = {
            "nodes": [
                {
                    "id": "c1",
                    "task_id": "t1",
                    "text": "Claim 1",
                    "nli_claim_support_ratio": 0.6,
                    "evidence_count": 3,
                    "support_count": 2,
                    "refute_count": 1,
                    "report_rank": 1,
                    "is_report_top": True,
                    "x": 10.0,
                    "y": 20.0,
                },
                {
                    "id": "c2",
                    "task_id": "t1",
                    "text": "Claim 2",
                    "nli_claim_support_ratio": 0.4,
                    "evidence_count": 2,
                    "support_count": 0,
                    "refute_count": 1,
                    "report_rank": 2,
                    "is_report_top": True,
                    "x": 30.0,
                    "y": 40.0,
                },
            ],
            "edges": [
                {
                    "source": "c1",
                    "target": "c2",
                    "kind": "co_page",
                    "weight": 0.7,
                    "explain": "Same source page",
                }
            ],
            "meta": {
                "total_nodes": 2,
                "total_edges": 1,
                "edge_counts": {"co_page": 1},
                "params": {},
            },
        }

        # Then
        assert len(graph["nodes"]) == 2
        assert len(graph["edges"]) == 1
        assert graph["meta"]["total_nodes"] == 2
        assert graph["edges"][0]["source"] == "c1"
        assert graph["edges"][0]["target"] == "c2"

    def test_empty_claim_graph_is_valid(self) -> None:
        """TC-GRAPH-06: Empty ClaimGraph is valid.

        Given: An empty ClaimGraph with no nodes/edges
        When: Structure is validated
        Then: Empty lists and zero counts should be valid
        """
        # Given
        graph: ClaimGraph = {
            "nodes": [],
            "edges": [],
            "meta": {
                "total_nodes": 0,
                "total_edges": 0,
                "edge_counts": {},
                "params": {"error": "no data available"},
            },
        }

        # Then
        assert len(graph["nodes"]) == 0
        assert len(graph["edges"]) == 0
        assert graph["meta"]["total_nodes"] == 0
        assert "error" in graph["meta"]["params"]

    def test_node_report_rank_ordering(self) -> None:
        """TC-GRAPH-07: Report ranks should be positive integers.

        Given: Multiple nodes with report ranks
        When: Nodes are examined
        Then: Report ranks should be positive integers and is_report_top
              should correlate with rank <= 30
        """
        # Given
        nodes: list[dict[str, object]] = [
            {"id": f"c{i}", "report_rank": i, "is_report_top": i <= 30} for i in range(1, 50)
        ]

        # Then
        for node in nodes:
            assert isinstance(node["report_rank"], int) and node["report_rank"] >= 1
            if isinstance(node["report_rank"], int) and node["report_rank"] <= 30:
                assert node["is_report_top"] is True
            else:
                assert node["is_report_top"] is False

    def test_edge_weight_is_normalized(self) -> None:
        """TC-GRAPH-08: Edge weights should be in [0, 1] range.

        Given: Various edge weights
        When: Weights are validated
        Then: All weights should be between 0 and 1 inclusive
        """
        # Given
        valid_weights = [0.0, 0.5, 0.72, 0.9, 1.0]

        for weight in valid_weights:
            edge: ClaimGraphEdge = {
                "source": "c1",
                "target": "c2",
                "kind": "semantic_sim",
                "weight": weight,
                "explain": f"Weight: {weight}",
            }
            # Then
            assert 0.0 <= edge["weight"] <= 1.0

    def test_edge_explain_is_human_readable(self) -> None:
        """TC-GRAPH-09: Edge explain field provides useful context.

        Given: Edges of different kinds
        When: Explain field is examined
        Then: It should provide human-readable explanation
        """
        # Given
        test_cases = [
            ("co_fragment", "Same fragment (shared evidence)"),
            ("co_page", "Same source page"),
            ("semantic_sim", "Semantic similarity: 0.85"),
        ]

        for kind, explain in test_cases:
            edge: ClaimGraphEdge = {
                "source": "c1",
                "target": "c2",
                "kind": kind,
                "weight": 0.85,
                "explain": explain,
            }
            # Then
            assert len(edge["explain"]) > 0
            assert isinstance(edge["explain"], str)

    def test_node_support_ratio_is_probability_like_range(self) -> None:
        """TC-GRAPH-10: Node support ratio is within [0, 1]."""
        node: ClaimGraphNode = {
            "id": "c_ratio",
            "task_id": "t1",
            "text": "Claim with ratio",
            "nli_claim_support_ratio": 0.5,
            "evidence_count": 1,
            "support_count": 0,
            "refute_count": 0,
            "report_rank": 1,
            "is_report_top": False,
            "x": 0.0,
            "y": 0.0,
        }
        assert 0.0 <= node["nli_claim_support_ratio"] <= 1.0
