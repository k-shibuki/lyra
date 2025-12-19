# quality-check

コード品質を確認する（lint、型チェック）。

## 関連ルール
- コード実行時: @.cursor/rules/code-execution.mdc

## 確認項目
1. Lintエラーの確認と根本的な修正
2. 型エラーの確認と根本的な修正
3. any型の不適切な使用がないか
4. セキュリティ上の問題がないか（認証/認可、データ保持等）

## 実行方法

### Lintエラー確認（ruff）

```bash
podman exec lancet ruff check src/ tests/
```

自動修正可能なエラーがある場合:
```bash
podman exec lancet ruff check --fix src/ tests/
```

### フォーマット確認（ruff format）

```bash
podman exec lancet ruff format --check src/ tests/
```

自動修正:
```bash
podman exec lancet ruff format src/ tests/
```

### 型チェック（mypy）

```bash
podman exec lancet mypy src/
```

## ワークフロー

### 1. エラーの分類と確認

各エラーについて以下を確認する：

1. **自動修正可能なエラー**: `ruff check --fix`で修正
2. **構文エラー**: 即座に修正（パースエラーはコードが実行できない）
3. **意図的なエラー**: 
   - E402（モジュールレベルのインポートがファイル先頭にない）: `pytestmark`の後にインポートするテストファイルなど
   - その他の意図的なエラー: docstringまたはコメントで理由を明記
4. **型エラー**: 根本原因を確認してから、型アノテーションを追加または修正

### 2. 意図的なエラーの文書化

意図的なエラーについては、該当箇所にdocstringまたはコメントで理由を明記する：

```python
# E402: Intentionally import after pytestmark for test configuration
pytestmark = pytest.mark.unit
from src.module import Something
```

または、モジュールレベルのdocstringに記載：

```python
"""
Module description.

Note: Imports are intentionally placed after pytestmark configuration
to avoid circular dependencies. This triggers E402 but is intentional.
"""
```

### 3. エラー統計の確認

```bash
# エラーの種類と数を確認
podman exec lancet ruff check src/ tests/ 2>&1 | grep -E "^[A-Z][0-9]+" | sort | uniq -c | sort -rn

# 特定のエラーコードの詳細を確認
podman exec lancet ruff check src/ tests/ 2>&1 | grep "E402" | head -20
```

### 4. 修正の優先順位

1. **最優先**: 構文エラー（コードが実行できない）
2. **高優先度**: 未定義名（F821）、型エラー（実行時エラーの原因）
3. **中優先度**: スタイルエラー（E402など、意図的でないもの）
4. **低優先度**: 警告レベルのエラー（Bシリーズなど）

## 完了条件
- [ ] 構文エラーが解消済み
- [ ] 未定義名エラーが解消済み
- [ ] 意図的なエラーにはdocstringまたはコメントで理由が明記されている
- [ ] フォーマットが整っている
- [ ] 型エラーが解消済み（または意図的なものとして文書化されている）
- [ ] any型でエラーを隠していない

## 次のステップ
品質確認後、`/regression-test` でテストを実行する。

## 出力
- 検出した問題一覧（エラーコード別に分類）
- 修正内容
- 意図的なエラーとその理由の一覧