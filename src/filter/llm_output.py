"""LLM output parsing utilities with retry mechanism.

This module provides common utilities for extracting and validating JSON
from LLM responses. Implements the retry policy from ADR-0006:
- 2 retries with format correction prompt
- Error recording on final failure
- Process continues without stopping

Per docs/review-prompt-templates.md Phase 2.
"""

import json
import re
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import BaseModel, ValidationError

from src.utils.logging import get_logger

logger = get_logger(__name__)

# Type alias for LLM call function
LLMCallFn = Callable[[str], Awaitable[str]]


def extract_json(text: str, expect_array: bool = False) -> dict | list | None:
    """Extract JSON from LLM response text.

    Handles common LLM output patterns:
    1. Direct JSON (try first)
    2. Markdown code blocks (```json ... ```)
    3. Raw JSON with surrounding text (greedy match)

    Args:
        text: LLM response text
        expect_array: If True, expect JSON array; if False, expect object

    Returns:
        Parsed JSON dict/list, or None if extraction fails

    Examples:
        >>> extract_json('{"key": "value"}')
        {'key': 'value'}
        >>> extract_json('```json\\n[{"a": 1}]\\n```', expect_array=True)
        [{'a': 1}]
    """
    if not text:
        return None

    text = text.strip()

    # 1. Try direct parse first
    try:
        result = json.loads(text)
        if expect_array and isinstance(result, list):
            return result
        if not expect_array and isinstance(result, dict):
            return result
        # Type mismatch, continue to other strategies
    except json.JSONDecodeError:
        pass

    # 2. Extract from Markdown code block (priority)
    code_block_pattern = r"```(?:json)?\s*([\[\{].*?[\]\}])\s*```"
    match = re.search(code_block_pattern, text, re.DOTALL)
    if match:
        try:
            result = json.loads(match.group(1))
            if expect_array and isinstance(result, list):
                return result
            if not expect_array and isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass

    # 3. Greedy match for raw JSON
    pattern = r"\[.*\]" if expect_array else r"\{.*\}"
    match = re.search(pattern, text, re.DOTALL)
    if match:
        try:
            result = json.loads(match.group())
            if expect_array and isinstance(result, list):
                return result
            if not expect_array and isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass

    return None


def validate_with_schema[T: BaseModel](
    data: dict | list | None,
    schema_class: type[T],
    lenient: bool = True,
) -> T | None:
    """Validate parsed JSON against a Pydantic schema.

    Args:
        data: Parsed JSON data
        schema_class: Pydantic model class to validate against
        lenient: If True, use lenient validation (coerce types, use defaults)

    Returns:
        Validated Pydantic model instance, or None if validation fails
    """
    if data is None:
        return None

    try:
        if lenient:
            # Use model_construct for partial data, then validate
            return schema_class.model_validate(data)
        return schema_class.model_validate(data, strict=True)
    except ValidationError as e:
        logger.warning(
            "Schema validation failed",
            schema=schema_class.__name__,
            errors=str(e),
        )
        return None


def validate_list_with_schema[T: BaseModel](
    data: list | None,
    item_schema: type[T],
    lenient: bool = True,
) -> list[T]:
    """Validate a list of items against a Pydantic schema.

    Invalid items are skipped with a warning.

    Args:
        data: List of parsed JSON items
        item_schema: Pydantic model class for each item
        lenient: If True, use lenient validation

    Returns:
        List of validated items (invalid items omitted)
    """
    if not data:
        return []

    results: list[T] = []
    for i, item in enumerate(data):
        try:
            if lenient:
                validated = item_schema.model_validate(item)
            else:
                validated = item_schema.model_validate(item, strict=True)
            results.append(validated)
        except ValidationError as e:
            logger.warning(
                "Item validation failed",
                index=i,
                schema=item_schema.__name__,
                errors=str(e),
            )
            continue

    return results


async def parse_with_retry(
    response: str,
    llm_call: LLMCallFn,
    expect_array: bool = False,
    max_retries: int = 2,
    schema_hint: str | None = None,
) -> dict | list | None:
    """Parse LLM response with retry on format errors.

    Implements the retry policy:
    - Up to 2 retries with format correction prompt
    - Returns None on final failure (caller handles fallback)

    Args:
        response: Initial LLM response text
        llm_call: Async function to call LLM for retry
        expect_array: If True, expect JSON array
        max_retries: Maximum retry attempts (default: 2)
        schema_hint: Optional schema description for retry prompt

    Returns:
        Parsed JSON, or None if all attempts fail
    """
    current_response = response

    for attempt in range(max_retries + 1):
        result = extract_json(current_response, expect_array=expect_array)
        if result is not None:
            return result

        if attempt < max_retries:
            # Build retry prompt
            type_hint = "JSON array" if expect_array else "JSON object"
            retry_prompt = (
                f"Your previous response could not be parsed as valid JSON.\n"
                f"Expected: {type_hint}\n"
            )
            if schema_hint:
                retry_prompt += f"Schema: {schema_hint}\n"
            retry_prompt += (
                f"Previous response (truncated): {current_response[:500]}\n"
                f"Please output ONLY valid {type_hint}, no explanations:"
            )

            try:
                current_response = await llm_call(retry_prompt)
                logger.debug(
                    "Retry attempt",
                    attempt=attempt + 1,
                    max_retries=max_retries,
                )
            except Exception as e:
                logger.warning("Retry LLM call failed", error=str(e))
                break

    return None


def record_extraction_error(
    error_type: str,
    context: dict[str, Any],
    response_preview: str | None = None,
) -> dict[str, Any]:
    """Create an error record for failed extractions.

    This record can be stored in DB to track extraction failures.

    Args:
        error_type: Type of error (e.g., "json_parse", "schema_validation")
        context: Additional context (template name, input preview, etc.)
        response_preview: First N characters of LLM response

    Returns:
        Error record dict suitable for DB storage
    """
    import time

    record = {
        "error_type": error_type,
        "timestamp": time.time(),
        "context": context,
    }
    if response_preview:
        record["response_preview"] = response_preview[:500]

    logger.warning(
        "Extraction error recorded",
        error_type=error_type,
        context=context,
    )

    return record
