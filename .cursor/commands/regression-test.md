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

### ポーリング例（推奨）

```bash
# テスト開始
./scripts/test.sh run tests/

# 完了までポーリング（最大5分、5秒間隔）
for i in {1..60}; do
    sleep 5
    status=$(./scripts/test.sh check 2>&1)
    echo "[$i] $status"
    # 完了判定: "DONE"が含まれるか、テスト結果キーワード（passed/failed/skipped）が含まれる
    if echo "$status" | grep -qE "(DONE|passed|failed|skipped|deselected)"; then
        break
    fi
done

# 結果取得
./scripts/test.sh get
```

**完了判定の仕組み**:
- `check`コマンドは、テスト結果に`passed`/`failed`/`skipped`/`deselected`などのキーワードが含まれていれば自動的に`DONE`を返す
- キーワードが見つからない場合は、ファイル更新時刻で判定（5秒以上更新がなければ`DONE`）

## 完了条件
- [ ] 全テストがパス
- [ ] 新規の失敗テストがない

## 出力
- テスト結果サマリ（passed / failed / skipped）
- 失敗がある場合はその詳細

