#!/usr/bin/env python3
"""Debug script to investigate LLM template/output structure mismatch.

This script tests each Jinja2 template against the actual LLM output
and validates against Pydantic schemas.
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.filter.llm_output import extract_json, validate_list_with_schema, validate_with_schema
from src.filter.llm_schemas import (
    DecomposedClaim,
    DenseSummaryOutput,
    ExtractedClaim,
    ExtractedFact,
    InitialSummaryOutput,
    QualityAssessmentOutput,
)
from src.filter.ollama_provider import create_ollama_provider
from src.filter.provider import LLMOptions
from src.utils.prompt_manager import render_prompt


async def test_template(
    template_name: str,
    template_vars: dict,
    schema_class: type,
    expect_array: bool,
) -> dict:
    """Test a single template against actual LLM output."""
    print(f"\n{'='*60}")
    print(f"Testing template: {template_name}")
    print(f"Schema: {schema_class.__name__}")
    print(f"Expect array: {expect_array}")
    print("="*60)

    # Step 1: Render prompt
    try:
        prompt = render_prompt(template_name, **template_vars)
        print(f"\n[1] Rendered prompt ({len(prompt)} chars):")
        print("-" * 40)
        print(prompt[:500] + ("..." if len(prompt) > 500 else ""))
        print("-" * 40)
    except Exception as e:
        print(f"[1] ERROR: Failed to render prompt: {e}")
        return {"template": template_name, "error": f"render_prompt: {e}"}

    # Step 2: Call LLM
    provider = create_ollama_provider()
    try:
        options = LLMOptions(response_format="json")
        response = await provider.generate(prompt, options)
        
        if not response.ok:
            print(f"[2] ERROR: LLM call failed: {response.error}")
            return {"template": template_name, "error": f"llm_call: {response.error}"}
        
        raw_text = response.text
        print(f"\n[2] Raw LLM output ({len(raw_text)} chars):")
        print("-" * 40)
        print(raw_text[:800] + ("..." if len(raw_text) > 800 else ""))
        print("-" * 40)
    except Exception as e:
        print(f"[2] ERROR: LLM call exception: {e}")
        return {"template": template_name, "error": f"llm_exception: {e}"}
    finally:
        await provider.close()

    # Step 3: Parse JSON
    parsed = extract_json(raw_text, expect_array=expect_array, strict_array=False)
    print(f"\n[3] Parsed JSON (expect_array={expect_array}):")
    print("-" * 40)
    if parsed is None:
        print("  Result: None (parse failed)")
        # Try to understand why
        try:
            direct_parse = json.loads(raw_text.strip())
            print(f"  Direct json.loads type: {type(direct_parse).__name__}")
            print(f"  Direct json.loads content: {json.dumps(direct_parse, indent=2)[:500]}")
        except json.JSONDecodeError as e:
            print(f"  json.loads error: {e}")
    else:
        print(f"  Type: {type(parsed).__name__}")
        print(f"  Content: {json.dumps(parsed, indent=2)[:500]}")
    print("-" * 40)

    # Step 4: Validate against schema
    print(f"\n[4] Schema validation ({schema_class.__name__}):")
    print("-" * 40)
    if expect_array:
        if isinstance(parsed, list):
            validated = validate_list_with_schema(parsed, schema_class)
            print(f"  Validated items: {len(validated)} / {len(parsed)}")
            for i, item in enumerate(validated[:3]):
                print(f"  [{i}] {item.model_dump()}")
            if len(validated) < len(parsed):
                print(f"  WARNING: {len(parsed) - len(validated)} items failed validation")
        else:
            print(f"  ERROR: Expected list, got {type(parsed).__name__}")
            validated = []
    else:
        if isinstance(parsed, dict):
            validated = validate_with_schema(parsed, schema_class)
            if validated:
                print(f"  Validated: {validated.model_dump()}")
            else:
                print("  Validation failed")
        else:
            print(f"  ERROR: Expected dict, got {type(parsed).__name__}")
            validated = None
    print("-" * 40)

    return {
        "template": template_name,
        "raw_text": raw_text,
        "parsed": parsed,
        "validated": validated,
        "success": validated is not None and (not expect_array or len(validated) > 0),
    }


async def main():
    """Run template tests."""
    print("=" * 60)
    print("LLM Template/Output Structure Debug")
    print("=" * 60)

    # Test data
    test_text = """Climate change poses a significant threat to coral reef ecosystems worldwide. 
    Rising ocean temperatures have caused mass bleaching events, with the Great Barrier Reef 
    experiencing severe bleaching in 2016 and 2017. Ocean acidification, resulting from 
    increased CO2 absorption, reduces the ability of corals to build calcium carbonate 
    skeletons. Studies indicate that coral cover has declined by 50% since the 1950s.
    The IPCC projects that 70-90% of coral reefs will be lost if global warming reaches 1.5°C."""

    test_cases = [
        # (template_name, template_vars, schema_class, expect_array)
        (
            "extract_claims",
            {"text": test_text, "context": "Climate change impacts on coral reefs"},
            ExtractedClaim,
            True,
        ),
        (
            "extract_facts",
            {"text": test_text},
            ExtractedFact,
            True,
        ),
        (
            "decompose",
            {"question": "What is the impact of climate change on coral reefs?"},
            DecomposedClaim,
            True,
        ),
        (
            "initial_summary",
            {
                "content": json.dumps([
                    {"index": 0, "text": "Coral bleaching increased 50% since 1950s"},
                    {"index": 1, "text": "Ocean acidification reduces coral growth"},
                ]),
                "query_context": "Climate change impacts",
            },
            InitialSummaryOutput,
            False,  # This expects a single object
        ),
    ]

    results = []
    for template_name, template_vars, schema_class, expect_array in test_cases:
        try:
            result = await test_template(template_name, template_vars, schema_class, expect_array)
            results.append(result)
        except Exception as e:
            print(f"\nERROR testing {template_name}: {e}")
            results.append({"template": template_name, "error": str(e)})

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    for r in results:
        status = "✅" if r.get("success") else "❌"
        error = r.get("error", "")
        print(f"{status} {r['template']}: {error if error else 'OK'}")


if __name__ == "__main__":
    asyncio.run(main())
