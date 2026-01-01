"""LLM output parsing utilities with retry mechanism.

This module provides common utilities for extracting and validating JSON
from LLM responses. Implements the retry policy from ADR-0006:
- 1 retry with format correction prompt
- Error recording on final failure
- Process continues without stopping

Per docs/review-prompt-templates.md Phase 2.
"""

import json
import re
import uuid
from collections.abc import Awaitable, Callable
from typing import Any, Literal, overload

from pydantic import BaseModel, ValidationError

from src.utils.logging import get_logger

logger = get_logger(__name__)

# Type alias for LLM call function
LLMCallFn = Callable[[str], Awaitable[str]]


def extract_json(
    text: str, expect_array: bool = False, strict_array: bool = False
) -> dict | list | None:
    """Extract JSON from LLM response text.

    Handles common LLM output patterns:
    1. Direct JSON (try first)
    2. Markdown code blocks (```json ... ```)
    3. Raw JSON with surrounding text (greedy match)
    4. Single object when array expected (wrap in array, unless strict_array=True)

    Args:
        text: LLM response text
        expect_array: If True, expect JSON array; if False, expect object
        strict_array: If True and expect_array=True, do NOT wrap single objects.
                      This allows the caller to trigger a retry for format correction.

    Returns:
        Parsed JSON dict/list, or None if extraction fails

    Examples:
        >>> extract_json('{"key": "value"}')
        {'key': 'value'}
        >>> extract_json('```json\\n[{"a": 1}]\\n```', expect_array=True)
        [{'a': 1}]
        >>> extract_json('{"claim": "test"}', expect_array=True)
        [{'claim': 'test'}]  # Single object wrapped in array (lenient)
        >>> extract_json('{"claim": "test"}', expect_array=True, strict_array=True)
        None  # Strict mode: single object is rejected
    """
    if not text:
        return None

    text = text.strip()

    def _maybe_wrap_in_array(result: Any) -> list | dict | None:
        """Wrap single object in array if expect_array is True (and not strict).

        Also handles "array wrapper" pattern where LLM returns {"objects": [...]}
        or similar structures instead of a plain array.
        """
        if expect_array:
            if isinstance(result, list):
                return result
            if isinstance(result, dict):
                # Check for "array wrapper" pattern: {"objects": [...]} or {"items": [...]}
                # Common LLM mistake when asked for an array
                array_wrapper_keys = {"objects", "items", "results", "claims", "facts", "data"}
                for key in array_wrapper_keys:
                    if key in result and isinstance(result[key], list):
                        logger.warning(
                            "LLM returned array wrapped in object; extracting inner array",
                            wrapper_key=key,
                        )
                        inner_array: list[Any] = result[key]
                        return inner_array

                if strict_array:
                    # Strict mode: reject single object, allow caller to retry
                    logger.debug("Rejecting single object in strict_array mode (expect_array=True)")
                    return None
                # Lenient mode: LLM returned single object instead of array - wrap it
                logger.warning(
                    "LLM returned single object instead of array; wrapping. "
                    "Consider improving prompt or model."
                )
                return [result]
        else:
            if isinstance(result, dict):
                return result
        return None

    # 1. Try direct parse first
    try:
        result = json.loads(text)
        wrapped = _maybe_wrap_in_array(result)
        if wrapped is not None:
            return wrapped
        # Type mismatch, continue to other strategies
    except json.JSONDecodeError:
        pass

    # 2. Extract from Markdown code block (priority)
    code_block_pattern = r"```(?:json)?\s*([\[\{].*?[\]\}])\s*```"
    match = re.search(code_block_pattern, text, re.DOTALL)
    if match:
        try:
            result = json.loads(match.group(1))
            wrapped = _maybe_wrap_in_array(result)
            if wrapped is not None:
                return wrapped
        except json.JSONDecodeError:
            pass

    # 3. Greedy match for raw JSON (try both array and object patterns)
    # If expect_array, first try array pattern, then object pattern (to wrap)
    patterns = [r"\[.*\]", r"\{.*\}"] if expect_array else [r"\{.*\}", r"\[.*\]"]
    for pattern in patterns:
        match = re.search(pattern, text, re.DOTALL)
        if match:
            try:
                result = json.loads(match.group())
                wrapped = _maybe_wrap_in_array(result)
                if wrapped is not None:
                    return wrapped
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


def _schema_hint[T: BaseModel](schema: type[T], *, expect_array: bool) -> str:
    """Build a compact schema hint for retry prompts (English-only)."""
    # Keep this short to avoid inflating tokens.
    try:
        fields = []
        for name, field in schema.model_fields.items():
            # annotation may be None for computed/aliased fields; fall back to repr
            ann = field.annotation
            ann_str = getattr(ann, "__name__", None) or str(ann)
            fields.append(f"{name}: {ann_str}")
        fields_part = ", ".join(fields[:20])
        suffix = "" if len(fields) <= 20 else ", ..."
        shape = "JSON array of objects" if expect_array else "JSON object"
        return f"Expected {shape} with fields: {fields_part}{suffix}"
    except Exception:
        return "Output must be valid JSON matching the required schema."


async def record_extraction_error_to_db(
    *,
    error_type: str,
    template_name: str,
    task_id: str | None,
    retry_count: int,
    context: dict[str, Any] | None = None,
    response: str | None = None,
) -> None:
    """Persist an extraction failure record to SQLite for audit/debug.

    NOTE: This function must never raise; failures are logged and ignored.
    """
    try:
        from src.storage.database import get_database

        db = await get_database()
        record_id = str(uuid.uuid4())
        response_preview = (response or "")[:500] or None
        context_json = json.dumps(context or {}, ensure_ascii=False)

        await db.execute(
            """
            INSERT INTO llm_extraction_errors (
                id, task_id, template_name, error_type,
                response_preview, context_json, retry_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record_id,
                task_id,
                template_name,
                error_type,
                response_preview,
                context_json,
                retry_count,
            ),
        )
    except Exception as e:
        logger.warning(
            "Failed to record extraction error to DB",
            error=str(e),
            template_name=template_name,
            error_type=error_type,
        )


async def parse_with_retry(
    response: str,
    llm_call: LLMCallFn,
    expect_array: bool = False,
    max_retries: int = 1,
    schema_hint: str | None = None,
) -> dict | list | None:
    """Parse LLM response with retry on format errors.

    Implements the retry policy:
    - Up to 1 retry with format correction prompt
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


@overload
async def parse_and_validate[T: BaseModel](
    *,
    response: str,
    schema: type[T],
    template_name: str,
    expect_array: Literal[True],
    llm_call: LLMCallFn | None = None,
    max_retries: int = 1,
    task_id: str | None = None,
    context: dict[str, Any] | None = None,
    lenient: bool = True,
) -> list[T] | None: ...


@overload
async def parse_and_validate[T: BaseModel](
    *,
    response: str,
    schema: type[T],
    template_name: str,
    expect_array: Literal[False],
    llm_call: LLMCallFn | None = None,
    max_retries: int = 1,
    task_id: str | None = None,
    context: dict[str, Any] | None = None,
    lenient: bool = True,
) -> T | None: ...


async def parse_and_validate[T: BaseModel](
    *,
    response: str,
    schema: type[T],
    template_name: str,
    expect_array: bool,
    llm_call: LLMCallFn | None = None,
    max_retries: int = 1,
    task_id: str | None = None,
    context: dict[str, Any] | None = None,
    lenient: bool = True,
) -> T | list[T] | None:
    """Parse, validate, optionally retry, and persist failure to DB.

    Retry policy:
    - Retry up to `max_retries` times (default: 1)
    - Retries are triggered on:
      - JSON parse failure
      - Schema validation failure
      - Single object when array expected (first attempt only, to give LLM a chance)
    - After all retries, single objects are wrapped in arrays to ensure processing
    - Final failure is recorded to DB and returns None (caller must continue)
    """
    current_response = response
    hint = _schema_hint(schema, expect_array=expect_array)

    last_error_type: str | None = None
    retries_attempted = 0

    for attempt in range(max_retries + 1):
        # First attempt: strict mode (reject single object to trigger retry)
        # Subsequent attempts: lenient mode (wrap single object in array)
        is_final_attempt = attempt >= max_retries or llm_call is None
        strict_array = expect_array and not is_final_attempt

        parsed = extract_json(
            current_response, expect_array=expect_array, strict_array=strict_array
        )
        if parsed is None:
            last_error_type = "json_parse" if not strict_array else "format_mismatch"
        else:
            if expect_array:
                if not isinstance(parsed, list):
                    last_error_type = "schema_validation"
                else:
                    items = validate_list_with_schema(parsed, schema, lenient=lenient)
                    if items:
                        return items
                    last_error_type = "schema_validation"
            else:
                model = validate_with_schema(parsed, schema, lenient=lenient)
                if model is not None:
                    return model
                last_error_type = "schema_validation"

        if attempt < max_retries and llm_call is not None:
            type_hint = "JSON array" if expect_array else "JSON object"
            retry_prompt = (
                f"Your previous response could not be accepted.\n"
                f"Failure: {last_error_type}\n"
                f"Expected: valid {type_hint}\n"
                f"{hint}\n"
                f"Previous response (truncated): {current_response[:500]}\n"
                f"Please output ONLY valid {type_hint}, no explanations:"
            )
            try:
                retries_attempted += 1
                current_response = await llm_call(retry_prompt)
                continue
            except Exception as e:
                logger.warning(
                    "Retry LLM call failed",
                    error=str(e),
                    template_name=template_name,
                )
                break

    await record_extraction_error_to_db(
        error_type=last_error_type or "unknown",
        template_name=template_name,
        task_id=task_id,
        retry_count=retries_attempted,
        context=context,
        response=current_response,
    )
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
