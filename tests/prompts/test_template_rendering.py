"""Template rendering tests with sample inputs.

Test Perspectives Table:
| Case ID | Input / Precondition | Perspective | Expected Result | Notes |
|---------|----------------------|-------------|-----------------|-------|
| TC-REN-01 | Valid inputs | Equivalence - normal | Renders successfully | - |
| TC-REN-02 | JSON templates | JSON structure | Valid JSON example | - |
| TC-REN-03 | Variables injection | Variable handling | Variables appear in output | - |
| TC-REN-04 | Empty inputs | Boundary - empty | Handles gracefully | - |
| TC-REN-05 | Special characters | Boundary - special | Preserves special chars | - |
"""

from src.utils.prompt_manager import PromptManager


class TestTemplateRendering:
    """Tests for template rendering with sample inputs."""

    def test_all_templates_render_with_sample_inputs(
        self,
        prompt_manager: PromptManager,
        sample_inputs: dict[str, dict],
    ) -> None:
        """TC-REN-01: All templates render successfully with sample inputs."""
        # Given: Sample inputs for each template
        for template_name, inputs in sample_inputs.items():
            # When: Rendering template
            result = prompt_manager.render(template_name, **inputs)

            # Then: Should produce non-empty output
            assert result is not None, f"Template '{template_name}' returned None"
            assert len(result) > 0, f"Template '{template_name}' returned empty string"

    def test_json_templates_contain_valid_json_structure(
        self,
        prompt_manager: PromptManager,
        sample_inputs: dict[str, dict],
        json_output_templates: list[str],
    ) -> None:
        """TC-REN-02: JSON output templates contain valid JSON examples."""
        # Given: Templates that should produce JSON
        for template_name in json_output_templates:
            inputs = sample_inputs.get(template_name, {})

            # When: Rendering template
            result = prompt_manager.render(template_name, **inputs)

            # Then: Should contain JSON-like structure (braces)
            # Note: We're checking the prompt contains JSON example, not that output is JSON
            has_object = "{" in result and "}" in result
            has_array = "[" in result and "]" in result

            assert (
                has_object or has_array
            ), f"Template '{template_name}' should contain JSON example"

    def test_variables_appear_in_rendered_output(
        self,
        prompt_manager: PromptManager,
        sample_inputs: dict[str, dict],
    ) -> None:
        """TC-REN-03: Template variables are injected into output."""
        # Given: Sample inputs for each template
        for template_name, inputs in sample_inputs.items():
            # When: Rendering template
            result = prompt_manager.render(template_name, **inputs)

            # Then: At least one input value should appear in output
            found_any = False
            for value in inputs.values():
                if isinstance(value, str) and value in result:
                    found_any = True
                    break
                elif isinstance(value, int) and str(value) in result:
                    found_any = True
                    break

            assert found_any, f"Template '{template_name}': no input variables found in output"


class TestEdgeCases:
    """Tests for edge cases in template rendering."""

    def test_empty_string_inputs(
        self,
        prompt_manager: PromptManager,
    ) -> None:
        """TC-REN-04: Templates handle empty string inputs gracefully."""
        # Given: Templates with empty string inputs
        test_cases = [
            ("extract_facts", {"text": ""}),
            ("summarize", {"text": ""}),
        ]

        # When/Then: Should not raise exception
        for template_name, inputs in test_cases:
            result = prompt_manager.render(template_name, **inputs)
            assert result is not None

    def test_special_characters_preserved(
        self,
        prompt_manager: PromptManager,
    ) -> None:
        """TC-REN-05: Special characters are preserved in output."""
        # Given: Input with special characters
        special_text = '{"key": "value"} and {braces} and <tags>'

        # When: Rendering template
        result = prompt_manager.render("extract_facts", text=special_text)

        # Then: Special characters should be preserved
        assert special_text in result

    def test_unicode_characters_preserved(
        self,
        prompt_manager: PromptManager,
    ) -> None:
        """TC-REN-05b: Unicode characters are preserved in output."""
        # Given: Input with unicode characters
        unicode_text = "日本語テスト émojis 🎉 кириллица"

        # When: Rendering template
        result = prompt_manager.render("extract_facts", text=unicode_text)

        # Then: Unicode characters should be preserved
        assert unicode_text in result

    def test_very_long_input(
        self,
        prompt_manager: PromptManager,
    ) -> None:
        """TC-REN-06: Templates handle very long inputs."""
        # Given: Very long text input
        long_text = "A" * 10000

        # When: Rendering template
        result = prompt_manager.render("extract_facts", text=long_text)

        # Then: Should render without error and contain the text
        assert long_text in result


class TestJsonOutputFormat:
    """Tests for JSON output format in templates."""

    def test_extract_facts_json_format(
        self,
        prompt_manager: PromptManager,
        sample_inputs: dict[str, dict],
    ) -> None:
        """Test extract_facts JSON example format."""
        # Given: extract_facts template
        result = prompt_manager.render("extract_facts", **sample_inputs["extract_facts"])

        # Then: Should contain expected JSON keys
        assert '"fact"' in result
        assert '"confidence"' in result
        assert '"evidence_type"' in result

    def test_extract_claims_json_format(
        self,
        prompt_manager: PromptManager,
        sample_inputs: dict[str, dict],
    ) -> None:
        """Test extract_claims JSON example format."""
        # Given: extract_claims template
        result = prompt_manager.render("extract_claims", **sample_inputs["extract_claims"])

        # Then: Should contain expected JSON keys
        assert '"claim"' in result
        assert '"type"' in result
        assert '"confidence"' in result

    def test_decompose_json_format(
        self,
        prompt_manager: PromptManager,
        sample_inputs: dict[str, dict],
    ) -> None:
        """Test decompose JSON example format."""
        # Given: decompose template
        result = prompt_manager.render("decompose", **sample_inputs["decompose"])

        # Then: Should contain expected JSON keys
        assert '"text"' in result
        assert '"polarity"' in result
        assert '"keywords"' in result

    def test_quality_assessment_json_format(
        self,
        prompt_manager: PromptManager,
        sample_inputs: dict[str, dict],
    ) -> None:
        """Test quality_assessment JSON example format."""
        # Given: quality_assessment template
        result = prompt_manager.render("quality_assessment", **sample_inputs["quality_assessment"])

        # Then: Should contain expected JSON keys
        assert '"quality_score"' in result
        assert '"is_ai_generated"' in result
