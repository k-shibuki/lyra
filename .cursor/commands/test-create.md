# test-create

実装に対応するテストコードを作成する。

## 関連ルール
- テスト関連タスク: @.cursor/rules/test-strategy.mdc
- コード実行時: @.cursor/rules/code-execution.mdc

## 事前確認
必要に応じて @requirements.md の仕様とコードベースを `grep` 等のツールで確認せよ。
コード中のコメントで @IMPLEMENTATION_PLAN.md を参照させることは禁止する。

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

## 完了条件
- [ ] テスト観点表が作成済み
- [ ] テストコードが完成
- [ ] 例外・エラーの型とメッセージを検証している

## 出力
- テスト観点表
- 作成したテストファイル一覧

