# ADR-0009: Test Layer Strategy

## Date
2025-12-05

## Context

Lyraは複数の外部依存（Ollama、Playwright、SQLite、外部Web）を持つ。これらすべてを含む統合テストは：

| 問題 | 詳細 |
|------|------|
| 遅い | Ollama起動だけで数秒〜数十秒 |
| 不安定 | ネットワーク・GPU状態で結果変動 |
| 重い | GPUリソース消費 |
| デバッグ困難 | どの層で失敗したか特定しにくい |

一方、純粋なユニットテストだけでは、コンポーネント間の統合問題を検出できない。

## Decision

**3層のテスト戦略を採用し、外部依存を段階的に除外する。**

### テスト層

| 層 | 名称 | 外部依存 | 速度 | 目的 |
|:--:|------|----------|------|------|
| L1 | Unit | なし（全モック） | 高速 | ロジック検証 |
| L2 | Integration | SQLite実物 | 中速 | DB統合検証 |
| L3 | E2E | 全実物 | 低速 | シナリオ検証 |

### L1: Unitテスト

```python
# 外部依存なし、すべてモック
@pytest.fixture
def mock_ollama():
    return MockOllamaClient(...)

def test_nli_judgment_supports(mock_ollama):
    result = nli_filter.judge(premise, hypothesis)
    assert result.relation == "SUPPORTS"
```

**特徴**:
- OllamaをMockOllamaClientで置換
- PlaywrightをMockBrowserで置換
- SQLiteをインメモリDBで置換
- 数百msで完了

### L2: Integrationテスト

```python
# SQLite実物、他はモック
@pytest.fixture
def real_db(tmp_path):
    db_path = tmp_path / "test.db"
    return Storage(db_path)

def test_evidence_persistence(real_db, mock_ollama):
    # DB統合の検証
```

**特徴**:
- 実際のSQLiteファイル操作
- スキーママイグレーション検証
- トランザクション動作確認

### L3: E2Eテスト

```python
# 全実物（CI/CDでは条件付き実行）
@pytest.mark.e2e
@pytest.mark.skipif(not gpu_available(), reason="GPU required")
def test_full_search_flow():
    # Ollama + Playwright + SQLite + 実Web
```

**特徴**:
- GPU必須（スキップ可能）
- ネットワークアクセスあり
- 実行時間: 数分

### CI/CD統合

```yaml
# GitHub Actions
jobs:
  test-l1:
    runs-on: ubuntu-latest
    steps:
      - run: pytest -m "not integration and not e2e"

  test-l2:
    runs-on: ubuntu-latest
    steps:
      - run: pytest -m "integration"

  test-l3:
    runs-on: self-hosted  # GPU runner
    if: github.event_name == 'push' && github.ref == 'refs/heads/main'
    steps:
      - run: pytest -m "e2e"
```

### pytestマーカー

```python
# conftest.py
def pytest_configure(config):
    config.addinivalue_line("markers", "integration: SQLite実物使用")
    config.addinivalue_line("markers", "e2e: 全外部依存使用")
```

## Consequences

### Positive
- **高速フィードバック**: L1は数秒で完了
- **安定性**: L1/L2は外部依存なく決定的
- **段階的検証**: 問題箇所の特定が容易
- **CI効率化**: L3は必要時のみ実行

### Negative
- **モック維持コスト**: MockOllama等の更新が必要
- **網羅性の限界**: モックでは検出できないバグ
- **3層の管理**: どの層でテストすべきか判断が必要

## Alternatives Considered

| Alternative | Pros | Cons | 判定 |
|-------------|------|------|------|
| 全E2Eのみ | 現実的 | 遅い、不安定 | 却下 |
| 全Unitのみ | 高速 | 統合問題未検出 | 却下 |
| 2層（Unit/E2E） | シンプル | DB統合問題が見落とされやすい | 却下 |

## References
- `docs/TEST_LAYERS.md`（アーカイブ）
- `tests/conftest.py` - pytest設定
- `tests/mocks/` - モック実装
- `.github/workflows/test.yml` - CI設定
