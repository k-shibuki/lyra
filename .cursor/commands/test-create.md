# test-create

実装に対応するテストコードを作成する。

## 関連ルール
- テスト関連タスク: @.cursor/rules/test-strategy.mdc
- コード実行時: @.cursor/rules/code-execution.mdc

## 事前確認
必要に応じて @docs/REQUIREMENTS.md の仕様とコードベースを `grep` 等のツールで確認せよ。
コード中のコメントで @docs/IMPLEMENTATION_PLAN.md を参照させることは禁止する。

## テスト作成手順
1. テスト観点表（等価分割・境界値）を Markdown 形式で提示
2. 観点表に基づいてテストコードを実装
3. Given / When / Then コメントを付与
4. 正常系と同数以上の失敗系を含める

## テスト観点表テンプレート
| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---------|---------------------|--------------------------------------|-----------------|-------|
| TC-N-01 | Valid input A       | Equivalence – normal                 | Processing succeeds | - |
| TC-A-01 | NULL                | Boundary – NULL                      | Validation error | - |

## テスト実行方法

**scripts/test.sh を使用（推奨）**:

```bash
# 1. テスト開始（特定ファイルを指定）
./scripts/test.sh run "tests/test_xxx.py"

# 2. 完了確認（5秒以上更新がなければDONE）
./scripts/test.sh check

# 3. 結果取得
./scripts/test.sh get
```

**注意**: test.shは非同期実行。`run`後に`check`→`get`で結果を取得する。

## 完了条件
- [ ] テスト観点表が作成済み
- [ ] テストコードが完成
- [ ] 例外・エラーの型とメッセージを検証している

## 出力
- テスト観点表
- 作成したテストファイル一覧

