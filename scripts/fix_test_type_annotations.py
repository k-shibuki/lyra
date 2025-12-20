#!/usr/bin/env python3
"""
Add type annotations to test functions.

This script adds `-> None` return type annotations to test functions
and async test functions that are missing them.

Only adds to:
- Functions starting with `test_` (pytest test functions)
- Functions not containing `yield` or `return <value>` in their body
"""

import re
import sys
from pathlib import Path


def get_function_body(lines: list[str], start_idx: int, indent: str) -> list[str]:
    """Get the body of a function starting at start_idx.
    
    Returns lines that are part of the function body (same or deeper indentation).
    """
    body_lines = []
    body_indent_len = len(indent) + 4  # Assume 4-space indentation
    
    i = start_idx
    while i < len(lines):
        line = lines[i]
        # Empty lines are part of the body
        if not line.strip():
            body_lines.append(line)
            i += 1
            continue
        
        # Check indentation
        current_indent = len(line) - len(line.lstrip())
        if current_indent >= body_indent_len:
            body_lines.append(line)
            i += 1
        else:
            # Less indented = end of function
            break
    
    return body_lines


def function_has_yield_or_return_value(body_lines: list[str]) -> bool:
    """Check if function body contains yield or return with a value."""
    for line in body_lines:
        stripped = line.strip()
        # Check for yield
        if stripped.startswith('yield ') or stripped == 'yield':
            return True
        # Check for return with a value (not just `return` or `return None`)
        if stripped.startswith('return '):
            # `return None` is OK for -> None
            if stripped == 'return None':
                continue
            # Any other return with value
            return True
    return False


def add_return_type_annotation(content: str) -> str:
    """Add -> None to test function definitions that are missing return type annotations.
    
    Only handles functions starting with `test_` to be safe.
    Skips functions with yield or return statements with values.
    """
    lines = content.split('\n')
    result = []
    i = 0
    
    while i < len(lines):
        line = lines[i]
        
        # Check if this line starts a test function definition
        # Match: def/async def followed by test_ function name
        match = re.match(r'^(\s*)(async\s+)?def\s+(test_\w+)\s*\(', line)
        
        if match:
            indent = match.group(1)
            func_name = match.group(3)
            
            # Collect the full function signature (may span multiple lines)
            signature_lines = [line]
            paren_count = line.count('(') - line.count(')')
            sig_end_idx = i
            
            # Continue collecting lines until we find the closing paren and colon
            while paren_count > 0 and sig_end_idx + 1 < len(lines):
                sig_end_idx += 1
                signature_lines.append(lines[sig_end_idx])
                paren_count += lines[sig_end_idx].count('(') - lines[sig_end_idx].count(')')
            
            full_signature = '\n'.join(signature_lines)
            
            # Check if this function already has a return type annotation
            if re.search(r'\)\s*->\s*\w', full_signature):
                # Already has return type, keep as is
                result.extend(signature_lines)
                i = sig_end_idx
            else:
                # Check function body for yield/return
                body_lines = get_function_body(lines, sig_end_idx + 1, indent)
                
                if function_has_yield_or_return_value(body_lines):
                    # Skip - has yield or return value
                    result.extend(signature_lines)
                    i = sig_end_idx
                else:
                    # Add -> None
                    modified = re.sub(
                        r'\)\s*:(\s*)$',
                        r') -> None:\1',
                        full_signature
                    )
                    result.extend(modified.split('\n'))
                    i = sig_end_idx
        else:
            result.append(line)
        
        i += 1
    
    return '\n'.join(result)


def add_fixture_return_types(content: str) -> str:
    """Add return type annotations to pytest fixtures.
    
    Handles:
    - Fixtures with yield -> Generator[..., None, None]
    - Fixtures with return -> specific type based on return value
    - Fixtures without return/yield -> Generator[None, None, None]
    """
    lines = content.split('\n')
    result = []
    i = 0
    
    while i < len(lines):
        line = lines[i]
        
        # Check for @pytest.fixture or @pytest_asyncio.fixture decorator
        if '@pytest.fixture' in line or '@pytest_asyncio.fixture' in line:
            decorator_lines = [line]
            j = i + 1
            
            # Collect any additional decorator parameters on next lines
            while j < len(lines) and (lines[j].strip().startswith(')') or 
                                       (not lines[j].strip() and j - i < 3)):
                decorator_lines.append(lines[j])
                j += 1
            
            # Now find the function definition
            if j < len(lines):
                func_line = lines[j]
                match = re.match(r'^(\s*)(async\s+)?def\s+(\w+)\s*\(', func_line)
                
                if match:
                    indent = match.group(1)
                    is_async = match.group(2) is not None
                    func_name = match.group(3)
                    
                    # Collect full signature
                    signature_lines = [func_line]
                    paren_count = func_line.count('(') - func_line.count(')')
                    sig_end_idx = j
                    
                    while paren_count > 0 and sig_end_idx + 1 < len(lines):
                        sig_end_idx += 1
                        signature_lines.append(lines[sig_end_idx])
                        paren_count += lines[sig_end_idx].count('(') - lines[sig_end_idx].count(')')
                    
                    full_signature = '\n'.join(signature_lines)
                    
                    # Check if already has return type
                    if re.search(r'\)\s*->\s*\w', full_signature):
                        result.extend(decorator_lines)
                        result.extend(signature_lines)
                        i = sig_end_idx
                    else:
                        # Get function body to determine return type
                        body_lines = get_function_body(lines, sig_end_idx + 1, indent)
                        
                        has_yield = any('yield' in line for line in body_lines)
                        
                        if has_yield:
                            # Generator fixture
                            if is_async:
                                return_type = 'AsyncGenerator[None, None]'
                            else:
                                return_type = 'Generator[None, None, None]'
                        else:
                            # Return fixture - just add None type, will need manual fix
                            return_type = None
                        
                        if return_type:
                            modified = re.sub(
                                r'\)\s*:(\s*)$',
                                f') -> {return_type}:\\1',
                                full_signature
                            )
                            result.extend(decorator_lines)
                            result.extend(modified.split('\n'))
                        else:
                            result.extend(decorator_lines)
                            result.extend(signature_lines)
                        i = sig_end_idx
                else:
                    result.extend(decorator_lines)
                    i = j - 1
            else:
                result.extend(decorator_lines)
                i = j - 1
        else:
            result.append(line)
        
        i += 1
    
    return '\n'.join(result)


def process_file(filepath: Path) -> tuple[bool, int]:
    """Process a single file, adding type annotations.
    
    Returns:
        Tuple of (modified, count of changes)
    """
    content = filepath.read_text()
    original = content
    
    # Add return type annotations for test functions
    content = add_return_type_annotation(content)
    
    # Add return type annotations for fixtures
    content = add_fixture_return_types(content)
    
    if content != original:
        filepath.write_text(content)
        # Count number of annotations added
        original_count = original.count('-> ')
        new_count = content.count('-> ')
        return True, new_count - original_count
    
    return False, 0


def ensure_imports(content: str, imports_needed: set[str]) -> str:
    """Ensure required imports are present in the file.
    
    Args:
        content: File content
        imports_needed: Set of import statements to ensure
    
    Returns:
        Modified content with imports added if needed
    """
    if not imports_needed:
        return content
    
    lines = content.split('\n')
    
    # Find the first non-docstring, non-comment, non-empty line
    insert_idx = 0
    in_docstring = False
    docstring_char = None
    
    for i, line in enumerate(lines):
        stripped = line.strip()
        
        # Track docstrings
        if not in_docstring:
            if stripped.startswith('"""') or stripped.startswith("'''"):
                docstring_char = stripped[:3]
                if stripped.count(docstring_char) >= 2 and len(stripped) > 6:
                    # Single-line docstring
                    continue
                in_docstring = True
                continue
        else:
            if docstring_char and docstring_char in stripped:
                in_docstring = False
            continue
        
        # Skip empty lines and comments at the start
        if not stripped or stripped.startswith('#'):
            continue
        
        # Found content after docstrings
        insert_idx = i
        break
    
    # Check which imports are already present
    imports_to_add = []
    for imp in imports_needed:
        # Extract the module/class name being imported
        if imp not in content:
            imports_to_add.append(imp)
    
    if not imports_to_add:
        return content
    
    # Find existing import block or insert after docstring
    import_block_start = -1
    for i in range(insert_idx, len(lines)):
        stripped = lines[i].strip()
        if stripped.startswith('import ') or stripped.startswith('from '):
            if import_block_start == -1:
                import_block_start = i
        elif import_block_start != -1 and stripped and not stripped.startswith('#'):
            # End of import block
            break
    
    if import_block_start == -1:
        import_block_start = insert_idx
    
    # Insert new imports at the start of import block
    for imp in sorted(imports_to_add):
        lines.insert(import_block_start, imp)
    
    return '\n'.join(lines)


def process_file(filepath: Path) -> tuple[bool, int]:
    """Process a single file, adding type annotations.
    
    Returns:
        Tuple of (modified, count of changes)
    """
    content = filepath.read_text()
    original = content
    
    # Add return type annotations for test functions
    content = add_return_type_annotation(content)
    
    # Add return type annotations for fixtures
    content = add_fixture_return_types(content)
    
    # Check if we added Generator or AsyncGenerator and need imports
    imports_needed: set[str] = set()
    if 'Generator[' in content and 'from collections.abc import' not in content:
        if 'Generator' not in content.split('from collections.abc import')[0] if 'from collections.abc import' in content else True:
            # Check if Generator is already imported
            if not re.search(r'from collections\.abc import.*Generator', content):
                if re.search(r'from collections\.abc import', content):
                    # Has import but missing Generator - need to add it to existing import
                    content = re.sub(
                        r'(from collections\.abc import )([^\n]+)',
                        lambda m: m.group(1) + ('Generator, ' if 'Generator' not in m.group(2) else '') + m.group(2),
                        content,
                        count=1
                    )
                else:
                    imports_needed.add('from collections.abc import Generator')
    
    if 'AsyncGenerator[' in content:
        if not re.search(r'from collections\.abc import.*AsyncGenerator', content):
            if re.search(r'from collections\.abc import', content):
                # Add to existing import
                content = re.sub(
                    r'(from collections\.abc import )([^\n]+)',
                    lambda m: m.group(1) + ('AsyncGenerator, ' if 'AsyncGenerator' not in m.group(2) else '') + m.group(2),
                    content,
                    count=1
                )
            else:
                imports_needed.add('from collections.abc import AsyncGenerator, Generator')
    
    content = ensure_imports(content, imports_needed)
    
    if content != original:
        filepath.write_text(content)
        # Count number of annotations added
        original_count = original.count('-> ')
        new_count = content.count('-> ')
        return True, new_count - original_count
    
    return False, 0


def main() -> None:
    """Main entry point."""
    tests_dir = Path(__file__).parent.parent / 'tests'
    
    if not tests_dir.exists():
        print(f"Error: tests directory not found at {tests_dir}")
        sys.exit(1)
    
    # Find all Python files in tests/
    test_files = list(tests_dir.rglob('*.py'))
    
    total_modified = 0
    total_annotations = 0
    
    for filepath in sorted(test_files):
        # Skip __pycache__
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
