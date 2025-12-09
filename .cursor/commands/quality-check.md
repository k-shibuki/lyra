# quality-check

コード品質を確認する（lint、型チェック等）。

## 関連ルール
- コード実行時: @.cursor/rules/code-execution.mdc

## 確認項目
1. Lintエラーの確認と修正
2. 型エラーの確認と修正
3. any型の不適切な使用がないか
4. セキュリティ上の問題がないか（認証/認可、データ保持等）

## 実行方法
```bash
# Lintエラー確認
podman exec lancet ruff check src/ tests/

# 型チェック（必要に応じて）
podman exec lancet mypy src/
```

## 完了条件
- [ ] Lintエラーが解消済み
- [ ] 型エラーが解消済み
- [ ] any型でエラーを隠していない

## 出力
- 検出した問題一覧
- 修正内容

