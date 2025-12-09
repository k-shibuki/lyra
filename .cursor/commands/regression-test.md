# regression-test

全テストを実行し、回帰がないことを確認する。

## 関連ルール
- コード実行時: @.cursor/rules/code-execution.mdc

## 実行コマンド

**scripts/test.sh を使用（推奨）**:

```bash
# 1. テスト開始（バックグラウンド実行）
./scripts/test.sh run tests/

# 2. 完了確認（5秒以上更新がなければDONE）
./scripts/test.sh check

# 3. 結果取得
./scripts/test.sh get

# 4. 強制終了（必要な場合）
./scripts/test.sh kill
```

**注意**: test.shは非同期実行のため、`run`後に`check`で完了を確認し、`get`で結果を取得する。
`check`が"RUNNING"を返す場合は再度実行して完了を待つ。

## 完了条件
- [ ] 全テストがパス
- [ ] 新規の失敗テストがない

## 出力
- テスト結果サマリ（passed / failed / skipped）
- 失敗がある場合はその詳細

