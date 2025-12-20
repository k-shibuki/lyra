#!/usr/bin/env python3
"""
Add type annotations to fixture arguments in test functions.

This script identifies common fixture parameter patterns and adds
appropriate type annotations.
"""

import re
import sys
from pathlib import Path

# Mapping of fixture names to their types
FIXTURE_TYPES: dict[str, str] = {
    # conftest.py fixtures
    "temp_dir": "Path",
    "temp_db_path": "Path",
    "test_database": "Database",
    "memory_database": "Database",
    "mock_settings": "Settings",
    "mock_aiohttp_session": "AsyncMock",
    "mock_ollama": "MagicMock",
    "mock_browser": "MagicMock",
    "sample_passages": "list[dict[str, str]]",
    "make_mock_response": "Callable[[dict[str, object], int], MockResponse]",
    "make_fragment": "Callable[..., dict[str, str]]",
    "make_claim": "Callable[..., dict[str, str | float]]",
    # pytest-mock
    "mocker": "MockerFixture",
    # pytest built-in
    "tmp_path": "Path",
    "tmp_path_factory": "TempPathFactory",
    "capsys": "CaptureFixture[str]",
    "capfd": "CaptureFixture[str]",
    "caplog": "LogCaptureFixture",
    "monkeypatch": "MonkeyPatch",
    "request": "FixtureRequest",
    # aiohttp
    "aiohttp_client": "AiohttpClient",
    # Common patterns
    "event_loop": "AbstractEventLoop",
}

# Import statements to add based on types used
TYPE_IMPORTS: dict[str, str] = {
    "Path": "from pathlib import Path",
    "Database": "from src.storage.database import Database",
    "Settings": "from src.utils.config import Settings",
    "AsyncMock": "from unittest.mock import AsyncMock",
    "MagicMock": "from unittest.mock import MagicMock",
    "MockerFixture": "from pytest_mock import MockerFixture",
    "TempPathFactory": "from _pytest.tmpdir import TempPathFactory",
    "CaptureFixture": "from _pytest.capture import CaptureFixture",
    "LogCaptureFixture": "from _pytest.logging import LogCaptureFixture",
    "MonkeyPatch": "from _pytest.monkeypatch import MonkeyPatch",
    "FixtureRequest": "from _pytest.fixtures import FixtureRequest",
    "AbstractEventLoop": "from asyncio import AbstractEventLoop",
    "Callable": "from collections.abc import Callable",
    "MockResponse": "from tests.conftest import MockResponse",
}


def add_fixture_arg_types(content: str, filepath: Path) -> tuple[str, set[str]]:
    """Add type annotations to fixture arguments.
    
    Returns:
        Tuple of (modified content, set of types that need imports)
    """
    types_used: set[str] = set()
    
    # Pattern for function arguments without type annotations
    # Match: param_name followed by , or )
    for fixture_name, type_hint in FIXTURE_TYPES.items():
        # Pattern: fixture_name followed by comma or closing paren, no existing type
        pattern = rf'\b({fixture_name})\s*([,\)])'
        replacement = rf'\1: {type_hint}\2'
        
        # Check if this fixture is used
        if re.search(pattern, content):
            new_content = re.sub(pattern, replacement, content)
            if new_content != content:
                content = new_content
                # Extract base type for import
                base_type = type_hint.split('[')[0]
                if base_type in TYPE_IMPORTS:
                    types_used.add(base_type)
                # Handle complex types
                if 'Callable' in type_hint:
                    types_used.add('Callable')
                if 'MockResponse' in type_hint and 'conftest' not in str(filepath):
                    types_used.add('MockResponse')
    
    return content, types_used


def ensure_imports(content: str, types_needed: set[str]) -> str:
    """Add necessary imports for types used."""
    if not types_needed:
        return content
    
    lines = content.split('\n')
    
    # Find import section
    import_section_end = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith('import ') or stripped.startswith('from '):
            import_section_end = i + 1
        elif import_section_end > 0 and stripped and not stripped.startswith('#'):
            break
    
    # Add missing imports
    imports_to_add = []
    for type_name in types_needed:
        if type_name in TYPE_IMPORTS:
            import_stmt = TYPE_IMPORTS[type_name]
            # Check if already imported
            if import_stmt not in content:
                # Check if module is imported differently
                module_name = import_stmt.split(' import ')[0].replace('from ', '')
                if module_name not in content or type_name not in content:
                    imports_to_add.append(import_stmt)
    
    if imports_to_add:
        # Insert at the end of import section
        for imp in sorted(set(imports_to_add)):
            lines.insert(import_section_end, imp)
            import_section_end += 1
    
    return '\n'.join(lines)


def process_file(filepath: Path) -> tuple[bool, int]:
    """Process a single file."""
    content = filepath.read_text()
    original = content
    
    # Add fixture argument types
    content, types_used = add_fixture_arg_types(content, filepath)
    
    # Add necessary imports
    content = ensure_imports(content, types_used)
    
    if content != original:
        filepath.write_text(content)
        # Count changes
        original_count = original.count(': ')
        new_count = content.count(': ')
        return True, new_count - original_count
    
    return False, 0


def main() -> None:
    """Main entry point."""
    tests_dir = Path(__file__).parent.parent / 'tests'
    
    if not tests_dir.exists():
        print(f"Error: tests directory not found at {tests_dir}")
        sys.exit(1)
    
    # Find all Python test files
    test_files = list(tests_dir.rglob('test_*.py'))
    
    total_modified = 0
    total_annotations = 0
    
    for filepath in sorted(test_files):
        if '__pycache__' in str(filepath):
            continue
        
        modified, count = process_file(filepath)
        if modified:
            total_modified += 1
            total_annotations += count
            print(f"  Modified: {filepath.relative_to(tests_dir)} (+{count} annotations)")
    
    print(f"\nSummary:")
    print(f"  Files modified: {total_modified}")
    print(f"  Annotations added: {total_annotations}")


if __name__ == '__main__':
    main()
