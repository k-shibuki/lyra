# ADR-0009: Test Layer Strategy

## Date
2025-12-05

## Context

Lyra has multiple external dependencies (Ollama, Playwright, SQLite, external Web). Integration tests including all of these:

| Problem | Details |
|---------|---------|
| Slow | Ollama startup alone takes seconds to tens of seconds |
| Unstable | Results vary with network and GPU state |
| Heavy | GPU resource consumption |
| Hard to Debug | Difficult to identify which layer failed |

On the other hand, pure unit tests alone cannot detect component integration issues.

## Decision

**Adopt a 3-layer test strategy, progressively excluding external dependencies.**

### Test Layers

| Layer | Name | External Dependencies | Speed | Purpose |
|:-----:|------|----------------------|-------|---------|
| L1 | Unit | None (all mocked) | Fast | Logic verification |
| L2 | Integration | Real SQLite | Medium | DB integration verification |
| L3 | E2E | All real | Slow | Scenario verification |

### L1: Unit Tests

```python
# No external dependencies, all mocked
@pytest.fixture
def mock_ollama():
    return MockOllamaClient(...)

def test_nli_judgment_supports(mock_ollama):
    result = nli_filter.judge(premise, hypothesis)
    assert result.relation == "SUPPORTS"
```

**Characteristics**:
- Replace Ollama with MockOllamaClient
- Replace Playwright with MockBrowser
- Replace SQLite with in-memory DB
- Completes in hundreds of milliseconds

### L2: Integration Tests

```python
# Real SQLite, others mocked
@pytest.fixture
def real_db(tmp_path):
    db_path = tmp_path / "test.db"
    return Storage(db_path)

def test_evidence_persistence(real_db, mock_ollama):
    # DB integration verification
```

**Characteristics**:
- Actual SQLite file operations
- Schema migration verification
- Transaction behavior confirmation

### L3: E2E Tests

```python
# All real (conditional execution in CI/CD)
@pytest.mark.e2e
@pytest.mark.skipif(not gpu_available(), reason="GPU required")
def test_full_search_flow():
    # Ollama + Playwright + SQLite + real Web
```

**Characteristics**:
- GPU required (skippable)
- Network access
- Execution time: several minutes

### CI/CD Integration

```yaml
# GitHub Actions
jobs:
  test-l1-l2:
    # Run L1 (Unit) + L2 (Integration) in same job
    runs-on: ubuntu-latest
    steps:
      - run: pytest -m "not e2e and not slow"

  test-l3:
    runs-on: self-hosted  # GPU runner
    if: github.event_name == 'push' && github.ref == 'refs/heads/main'
    steps:
      - run: pytest -m "e2e"
```

### pytest Markers

```python
# conftest.py
def pytest_configure(config):
    config.addinivalue_line("markers", "integration: Uses real SQLite")
    config.addinivalue_line("markers", "e2e: Uses all external dependencies")
```

## Consequences

### Positive
- **Fast Feedback**: L1 completes in seconds
- **Stability**: L1/L2 are deterministic without external dependencies
- **Progressive Verification**: Easy to identify problem location
- **CI Efficiency**: L3 runs only when needed

### Negative
- **Mock Maintenance Cost**: MockOllama etc. need updates
- **Coverage Limits**: Some bugs undetectable with mocks
- **3-Layer Management**: Need to decide which layer tests belong in

## Alternatives Considered

| Alternative | Pros | Cons | Decision |
|-------------|------|------|----------|
| E2E Only | Realistic | Slow, unstable | Rejected |
| Unit Only | Fast | Integration issues undetected | Rejected |
| 2-Layer (Unit/E2E) | Simple | DB integration issues easily missed | Rejected |

## References
- `README.md` - Quality Control section (test execution guide)
- `tests/conftest.py` - pytest configuration, environment detection, marker definitions
- `scripts/test.sh` - Test runner (cloud agent compatible)
