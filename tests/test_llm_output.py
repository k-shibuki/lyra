"""Tests for LLM output parsing utilities.

Test Perspectives Table:
| Case ID | Input / Precondition | Perspective | Expected Result | Notes |
|---------|----------------------|-------------|-----------------|-------|
| TC-N-01 | Valid JSON object | Equivalence - normal | Returns parsed dict | - |
| TC-N-02 | Valid JSON array | Equivalence - normal | Returns parsed list | - |
| TC-N-03 | JSON in code block | Equivalence - normal | Extracts from block | - |
| TC-N-04 | JSON with surrounding text | Equivalence - normal | Extracts JSON | - |
| TC-B-01 | Empty string | Boundary - empty | Returns None | - |
| TC-B-02 | Whitespace only | Boundary - minimal | Returns None | - |
| TC-B-03 | Very large JSON | Boundary - max | Parses successfully | - |
| TC-A-01 | Invalid JSON | Error case | Returns None | - |
| TC-A-02 | No JSON in text | Error case | Returns None | - |
| TC-A-03 | Type mismatch (expect array, get object) | Error case | Returns None | - |
| TC-S-01 | Schema validation valid | Schema validation | Returns model | - |
| TC-S-02 | Schema validation with defaults | Schema validation | Uses defaults | - |
| TC-S-03 | Schema validation invalid | Schema validation | Returns None | - |
| TC-L-01 | List validation valid items | List validation | Returns valid items | - |
| TC-L-02 | List validation mixed items | List validation | Skips invalid | - |
"""

from src.filter.llm_output import (
    extract_json,
    record_extraction_error,
    validate_list_with_schema,
    validate_with_schema,
)
from src.filter.llm_schemas import (
    DecomposedClaim,
    ExtractedClaim,
    ExtractedFact,
    QualityAssessmentOutput,
)


class TestExtractJson:
    """Tests for extract_json function."""

    # -------------------------------------------------------------------------
    # TC-N-01 to TC-N-04: Normal cases
    # -------------------------------------------------------------------------

    def test_valid_json_object(self) -> None:
        """TC-N-01: Test extraction of valid JSON object."""
        # Given: Valid JSON object string
        text = '{"key": "value", "number": 42}'

        # When: Extracting JSON
        result = extract_json(text, expect_array=False)

        # Then: Returns parsed dict
        assert result == {"key": "value", "number": 42}

    def test_valid_json_array(self) -> None:
        """TC-N-02: Test extraction of valid JSON array."""
        # Given: Valid JSON array string
        text = '[{"a": 1}, {"b": 2}]'

        # When: Extracting JSON with expect_array=True
        result = extract_json(text, expect_array=True)

        # Then: Returns parsed list
        assert result == [{"a": 1}, {"b": 2}]

    def test_json_in_markdown_code_block(self) -> None:
        """TC-N-03: Test extraction from Markdown code block."""
        # Given: JSON wrapped in code block
        text = """Here is the result:
```json
{"fact": "test", "confidence": 0.9}
```
That's the output."""

        # When: Extracting JSON
        result = extract_json(text, expect_array=False)

        # Then: Extracts from code block
        assert result == {"fact": "test", "confidence": 0.9}

    def test_json_in_plain_code_block(self) -> None:
        """TC-N-03b: Test extraction from code block without json tag."""
        # Given: JSON in code block without language tag
        text = """```
[{"claim": "A"}, {"claim": "B"}]
```"""

        # When: Extracting JSON array
        result = extract_json(text, expect_array=True)

        # Then: Extracts successfully
        assert result == [{"claim": "A"}, {"claim": "B"}]

    def test_json_with_surrounding_text(self) -> None:
        """TC-N-04: Test extraction of JSON with surrounding text."""
        # Given: JSON embedded in text
        text = 'The extracted facts are: [{"fact": "A"}, {"fact": "B"}] as shown above.'

        # When: Extracting JSON array
        result = extract_json(text, expect_array=True)

        # Then: Extracts JSON correctly
        assert result == [{"fact": "A"}, {"fact": "B"}]

    # -------------------------------------------------------------------------
    # TC-B-01 to TC-B-03: Boundary cases
    # -------------------------------------------------------------------------

    def test_empty_string(self) -> None:
        """TC-B-01: Test with empty string input."""
        # Given: Empty string
        text = ""

        # When: Extracting JSON
        result = extract_json(text)

        # Then: Returns None
        assert result is None

    def test_whitespace_only(self) -> None:
        """TC-B-02: Test with whitespace only."""
        # Given: Whitespace string
        text = "   \n\t  "

        # When: Extracting JSON
        result = extract_json(text)

        # Then: Returns None
        assert result is None

    def test_large_json(self) -> None:
        """TC-B-03: Test with large JSON."""
        # Given: Large JSON array
        items = [{"fact": f"fact_{i}", "confidence": 0.9} for i in range(100)]
        import json

        text = json.dumps(items)

        # When: Extracting JSON
        result = extract_json(text, expect_array=True)

        # Then: Parses successfully
        assert result is not None
        assert len(result) == 100

    # -------------------------------------------------------------------------
    # TC-A-01 to TC-A-03: Error cases
    # -------------------------------------------------------------------------

    def test_invalid_json(self) -> None:
        """TC-A-01: Test with invalid JSON."""
        # Given: Malformed JSON
        text = '{"key": value}'  # Missing quotes around value

        # When: Extracting JSON
        result = extract_json(text, expect_array=False)

        # Then: Returns None
        assert result is None

    def test_no_json_in_text(self) -> None:
        """TC-A-02: Test with plain text, no JSON."""
        # Given: Plain text without JSON
        text = "This is just regular text without any JSON content."

        # When: Extracting JSON
        result = extract_json(text)

        # Then: Returns None
        assert result is None

    def test_type_mismatch_expect_array_get_object(self) -> None:
        """TC-A-03: Test type mismatch - expect array, get object."""
        # Given: JSON object
        text = '{"key": "value"}'

        # When: Extracting with expect_array=True
        result = extract_json(text, expect_array=True)

        # Then: Returns None (type mismatch)
        assert result is None

    def test_type_mismatch_expect_object_get_array(self) -> None:
        """TC-A-03b: Test type mismatch - expect object, get array."""
        # Given: JSON array
        text = "[1, 2, 3]"

        # When: Extracting with expect_array=False
        result = extract_json(text, expect_array=False)

        # Then: Returns None (type mismatch)
        assert result is None


class TestValidateWithSchema:
    """Tests for validate_with_schema function."""

    # -------------------------------------------------------------------------
    # TC-S-01 to TC-S-03: Schema validation cases
    # -------------------------------------------------------------------------

    def test_valid_data(self) -> None:
        """TC-S-01: Test validation with valid data."""
        # Given: Valid data matching ExtractedFact schema
        data = {"fact": "Test fact", "confidence": 0.9, "evidence_type": "statistic"}

        # When: Validating
        result = validate_with_schema(data, ExtractedFact)

        # Then: Returns validated model
        assert result is not None
        assert result.fact == "Test fact"
        assert result.confidence == 0.9
        assert result.evidence_type == "statistic"

    def test_validation_with_defaults(self) -> None:
        """TC-S-02: Test validation fills in defaults."""
        # Given: Minimal data (missing optional fields)
        data = {"fact": "Test fact"}

        # When: Validating with lenient mode
        result = validate_with_schema(data, ExtractedFact, lenient=True)

        # Then: Uses default values
        assert result is not None
        assert result.fact == "Test fact"
        assert result.confidence == 0.5  # Default
        assert result.evidence_type == "observation"  # Default

    def test_validation_invalid_data(self) -> None:
        """TC-S-03: Test validation with invalid data."""
        # Given: Missing required field
        data = {"confidence": 0.9}  # Missing 'fact'

        # When: Validating
        result = validate_with_schema(data, ExtractedFact)

        # Then: Returns None
        assert result is None

    def test_validation_none_input(self) -> None:
        """TC-S-03b: Test validation with None input."""
        # Given: None input
        data = None

        # When: Validating
        result = validate_with_schema(data, ExtractedFact)

        # Then: Returns None
        assert result is None

    def test_validation_type_coercion(self) -> None:
        """TC-S-04: Test validation coerces types."""
        # Given: Data with string confidence (should be float)
        data = {"fact": "Test", "confidence": "0.8"}

        # When: Validating with lenient mode
        result = validate_with_schema(data, ExtractedFact, lenient=True)

        # Then: Coerces to float
        assert result is not None
        assert result.confidence == 0.8

    def test_validation_clamps_scores(self) -> None:
        """TC-S-05: Test validation clamps out-of-range scores."""
        # Given: Data with out-of-range confidence
        data = {"fact": "Test", "confidence": 1.5}

        # When: Validating
        result = validate_with_schema(data, ExtractedFact)

        # Then: Clamps to valid range
        assert result is not None
        assert result.confidence == 1.0


class TestValidateListWithSchema:
    """Tests for validate_list_with_schema function."""

    # -------------------------------------------------------------------------
    # TC-L-01 to TC-L-02: List validation cases
    # -------------------------------------------------------------------------

    def test_all_valid_items(self) -> None:
        """TC-L-01: Test list validation with all valid items."""
        # Given: List of valid items
        data = [
            {"fact": "Fact 1", "confidence": 0.9},
            {"fact": "Fact 2", "confidence": 0.8},
        ]

        # When: Validating list
        results = validate_list_with_schema(data, ExtractedFact)

        # Then: Returns all items validated
        assert len(results) == 2
        assert results[0].fact == "Fact 1"
        assert results[1].fact == "Fact 2"

    def test_mixed_valid_invalid_items(self) -> None:
        """TC-L-02: Test list validation skips invalid items."""
        # Given: Mix of valid and invalid items
        data = [
            {"fact": "Valid fact", "confidence": 0.9},
            {"confidence": 0.8},  # Invalid: missing 'fact'
            {"fact": "Another valid", "confidence": 0.7},
        ]

        # When: Validating list
        results = validate_list_with_schema(data, ExtractedFact)

        # Then: Returns only valid items
        assert len(results) == 2
        assert results[0].fact == "Valid fact"
        assert results[1].fact == "Another valid"

    def test_empty_list(self) -> None:
        """TC-L-03: Test list validation with empty list."""
        # Given: Empty list
        data: list = []

        # When: Validating list
        results = validate_list_with_schema(data, ExtractedFact)

        # Then: Returns empty list
        assert results == []

    def test_none_input(self) -> None:
        """TC-L-04: Test list validation with None input."""
        # Given: None input
        data = None

        # When: Validating list
        results = validate_list_with_schema(data, ExtractedFact)

        # Then: Returns empty list
        assert results == []


class TestRecordExtractionError:
    """Tests for record_extraction_error function."""

    def test_creates_error_record(self) -> None:
        """TC-E-01: Test error record creation."""
        # Given: Error details
        error_type = "json_parse"
        context = {"template": "extract_facts", "input_length": 100}
        response = "Invalid response text here"

        # When: Recording error
        record = record_extraction_error(error_type, context, response)

        # Then: Creates proper record
        assert record["error_type"] == "json_parse"
        assert record["context"]["template"] == "extract_facts"
        assert "timestamp" in record
        assert record["response_preview"] == response

    def test_response_preview_truncation(self) -> None:
        """TC-E-02: Test response preview truncates to 500 chars."""
        # Given: Very long response
        long_response = "A" * 1000

        # When: Recording error
        record = record_extraction_error("test", {}, long_response)

        # Then: Truncates to 500 characters
        assert len(record["response_preview"]) == 500

    def test_no_response_preview(self) -> None:
        """TC-E-03: Test error record without response."""
        # Given: No response provided
        # When: Recording error
        record = record_extraction_error("test", {"key": "value"})

        # Then: response_preview key not present
        assert "response_preview" not in record


class TestSchemaValidators:
    """Tests for schema field validators."""

    def test_extracted_fact_evidence_type_normalization(self) -> None:
        """Test evidence_type normalizes to allowed values."""
        # Given: Unknown evidence type
        data = {"fact": "Test", "evidence_type": "UNKNOWN"}

        # When: Validating
        result = validate_with_schema(data, ExtractedFact)

        # Then: Falls back to 'observation'
        assert result is not None
        assert result.evidence_type == "observation"

    def test_extracted_claim_type_normalization(self) -> None:
        """Test claim type normalizes to allowed values."""
        # Given: Unknown claim type
        data = {"claim": "Test claim", "type": "hypothesis"}

        # When: Validating
        result = validate_with_schema(data, ExtractedClaim)

        # Then: Falls back to 'fact'
        assert result is not None
        assert result.type == "fact"

    def test_quality_assessment_bool_coercion(self) -> None:
        """Test boolean coercion in QualityAssessmentOutput."""
        # Given: Data with string booleans
        data = {
            "quality_score": 0.8,
            "is_ai_generated": "true",
            "is_spam": "no",
            "is_aggregator": "1",
        }

        # When: Validating
        result = validate_with_schema(data, QualityAssessmentOutput)

        # Then: Coerces to proper booleans
        assert result is not None
        assert result.is_ai_generated is True
        assert result.is_spam is False
        assert result.is_aggregator is True

    def test_decomposed_claim_normalization(self) -> None:
        """Test DecomposedClaim field normalization."""
        # Given: Data with mixed case values
        data = {
            "text": "Test claim",
            "polarity": "POSITIVE",
            "granularity": "Atomic",
            "type": "CAUSAL",
        }

        # When: Validating
        result = validate_with_schema(data, DecomposedClaim)

        # Then: Normalizes to lowercase
        assert result is not None
        assert result.polarity == "positive"
        assert result.granularity == "atomic"
        assert result.type == "causal"
