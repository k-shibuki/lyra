# merge-complete

mainブランチにマージし、完了報告を行う。

## マージ手順
1. mainブランチに切り替え
2. 作業ブランチをマージ
3. mainにチェックアウト（作業ブランチは削除不要）

```bash
git checkout main
git merge --no-edit <branch-name>
```

**注意**: gitコマンドは必ず非対話型オプションを使用すること（`--no-edit`, `--no-pager` など）。対話待ちになるとタイムアウトする。

## 実装計画書の更新
@docs/IMPLEMENTATION_PLAN.md の該当タスクのステータスを更新:
- `[ ]` → `[x]` に変更
- 完了日を記載（必要に応じて）

## 完了報告
以下を出力:
- 変更ファイル一覧
- テスト結果サマリ
- 実装計画書の更新差分

## 出力例
```
## 完了報告

### 変更ファイル
- src/xxx.py（新規作成）
- src/yyy.py（修正）
- tests/test_xxx.py（新規作成）

### テスト結果
- 全 XX テストパス
- カバレッジ: XX%

### 実装計画書の更新
- Phase X.Y: タスク名 → 完了
```

