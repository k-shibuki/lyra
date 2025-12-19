# quality-check

コード品質を確認する（lint、型チェック）。

## 関連ルール
- コード実行時: @.cursor/rules/code-execution.mdc

## 重要な原則

**警告・エラーは必ず根本から解消する。回避策は使わない。**

以下の回避策は禁止：
- `# type: ignore` コメント
- `# noqa` コメント（正当な理由がある場合を除く）
- `cast(Any, ...)` による型の隠蔽
- 過度に広い型（`Any`、`object`）での型エラー回避

正しい修正方法：
- 適切な型アノテーションの追加
- 型ガード（`isinstance`、`assert`）による型の絞り込み
- `cast()` は具体的な型への変換のみ（`cast(str, ...)`, `cast(dict[str, Any], ...)`）
- ライブラリの型スタブ追加（`types-*` パッケージ）

## 確認項目
1. Lintエラー・警告の確認と根本的な修正
2. 型エラー・警告の確認と根本的な修正
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
podman exec lancet mypy src --config-file pyproject.toml
```

**注意**: `--config-file pyproject.toml` を指定することで、`[tool.mypy]` の設定（`warn_return_any = true` など）が適用される。

## ワークフロー

### 1. エラーの分類と確認

各エラーについて以下を確認する：

1. **自動修正可能なエラー**: `ruff check --fix`で修正
2. **構文エラー**: 即座に修正（パースエラーはコードが実行できない）
3. **意図的なエラー**: 
   - E402（モジュールレベルのインポートがファイル先頭にない）: `pytestmark`の後にインポートするテストファイルなど
   - その他の意図的なエラー: docstringまたはコメントで理由を明記
4. **型エラー**: 根本原因を確認してから、型アノテーションを追加または修正

### 2. 警告の根本解消

**警告は無視せず、必ず根本から解消する。**

| 警告の種類 | 正しい修正方法 | ❌ 禁止される回避策 |
|-----------|--------------|-------------------|
| `no-any-return` | 戻り値に適切な型を指定、または`cast(具体型, ...)`を使用 | `# type: ignore` |
| `arg-type` | 引数の型を修正、または型ガードを追加 | `cast(Any, ...)` |
| `assignment` | 変数に正しい型アノテーションを追加 | `# noqa` |
| `import-untyped` | `types-*` パッケージをインストール | `# type: ignore[import-untyped]` |
| `var-annotated` | 明示的な型アノテーションを追加 | 無視 |

### 3. 意図的なエラーの文書化

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

### 4. エラー統計の確認

```bash
# エラーの種類と数を確認
podman exec lancet ruff check src/ tests/ 2>&1 | grep -E "^[A-Z][0-9]+" | sort | uniq -c | sort -rn

# 特定のエラーコードの詳細を確認
podman exec lancet ruff check src/ tests/ 2>&1 | grep "E402" | head -20
```

### 5. 修正の優先順位

1. **最優先**: 構文エラー（コードが実行できない）
2. **高優先度**: 未定義名（F821）、型エラー（実行時エラーの原因）
3. **中優先度**: 型警告（`no-any-return`、`arg-type`など）
4. **通常優先度**: スタイルエラー（E402など、意図的でないもの）

## 完了条件
- [ ] ruff check でエラー・警告がゼロ
- [ ] ruff format --check でフォーマット差分がゼロ
- [ ] mypy でエラー・警告がゼロ（`Success: no issues found`）
- [ ] 意図的なエラーにはdocstringまたはコメントで理由が明記されている
- [ ] `# type: ignore` や `# noqa` を新規追加していない
- [ ] any型でエラーを隠していない

## 次のステップ
品質確認後、`/regression-test` でテストを実行する。

## 出力
- 検出した問題一覧（エラーコード別に分類）
- 修正内容
- 意図的なエラーとその理由の一覧
