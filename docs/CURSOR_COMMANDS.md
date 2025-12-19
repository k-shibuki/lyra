# Cursor カスタムコマンド一覧

Lancet開発で使用するCursorカスタムコマンドの体系。

## ワークフロー

| コマンド | 用途 |
|---------|------|
| `/wf-dev` | 新規開発（タスク選定→実装→テスト→マージ） |
| `/wf-debug` | バグ調査・修正 |
| `/wf-pr` | リモートPRのレビュー・マージ |

```
/wf-dev     開発ワークフロー
┌─────────────────────────────────────────────────────────┐
│ task-select → implement → test-create → test-review    │
│ → quality-check → regression-test → commit             │
│ → merge-complete → push                                │
└─────────────────────────────────────────────────────────┘

/wf-debug   デバッグワークフロー
┌─────────────────────────────────────────────────────────┐
│ integration-design  (モジュール間連動)                   │
│ bug-analysis        (一般的なバグ)         → quality-   │
│ parser-repair       (パーサー修正)           check →    │
│                                              regression-│
│                                              test →     │
│                                              commit →   │
│                                              merge-     │
│                                              complete → │
│                                              push       │
└─────────────────────────────────────────────────────────┘

/wf-pr      PRレビューワークフロー
┌─────────────────────────────────────────────────────────┐
│ PR取得 → コードレビュー → quality-check →              │
│ regression-test → マージ判断 → マージ実行 → push      │
└─────────────────────────────────────────────────────────┘
```

## 単機能コマンド

### 開発フェーズ（/wf-dev で使用）

| コマンド | 説明 |
|---------|------|
| `/task-select` | タスク選定・ブランチ作成 |
| `/implement` | 実装コード作成 |
| `/test-create` | テスト観点表・テストコード作成 |
| `/test-review` | テスト品質レビュー |
| `/quality-check` | lint/型チェック（ruff, mypy） |
| `/regression-test` | 全テスト実行 |
| `/commit` | コミットメッセージ作成・コミット |
| `/merge-complete` | mainマージ・完了報告 |
| `/push` | mainブランチをリモートにプッシュ |
| `/suspend` | 作業中断・WIPコミット |

### デバッグ（/wf-debug で使用）

| コマンド | 説明 |
|---------|------|
| `/integration-design` | モジュール間連動設計（vibe coding弱点解消） |
| `/bug-analysis` | バグパターン分類・原因調査・修正 |
| `/parser-repair` | 検索エンジンHTMLパーサー修正 |

### リファレンス

| コマンド | 説明 |
|---------|------|
| `/scripts-help` | 開発スクリプト（dev.sh, test.sh等）の使い方 |

## 関連ルール（.cursor/rules/）

| ルール | 説明 |
|-------|------|
| `code-execution.mdc` | コード実行前の確認事項 |
| `test-strategy.mdc` | テスト戦略・観点 |
| `refactoring.mdc` | リファクタリング時の注意事項 |
| `commit-message-format.mdc` | コミットメッセージ形式 |
| `integration-design.mdc` | モジュール間連動設計の詳細ルール |

## 使い方

```bash
# 新規開発を開始
/wf-dev

# バグを調査・修正
/wf-debug

# PRをレビュー
/wf-pr

# 個別コマンドを直接実行
/quality-check
/regression-test
```
