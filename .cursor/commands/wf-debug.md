# wf-debug

バグ調査・修正の統合ワークフロー。

**注意**: これは `/wf-dev` とは独立したワークフローです。

## ワークフロー概要

```
┌─────────────────────────────────────────────────────────────┐
│  問題の種類を特定                                            │
│         ↓                                                    │
│  ┌─────────────────┬─────────────────┬─────────────────┐    │
│  │ モジュール間連動 │ 一般的なバグ     │ パーサー失敗     │    │
│  │ /integration-   │ /bug-analysis   │ /parser-repair  │    │
│  │    design       │                 │                 │    │
│  └─────────────────┴─────────────────┴─────────────────┘    │
│         ↓                                                    │
│  修正・検証                                                  │
│         ↓                                                    │
│  /quality-check → /regression-test → /commit               │
└─────────────────────────────────────────────────────────────┘
```

## 問題の種類と対応コマンド

| 問題の種類 | コマンド | 説明 |
|-----------|---------|------|
| モジュール間連動 | `/integration-design` | vibe codingの弱点解消。シーケンス図・型定義・デバッグスクリプト作成 |
| 一般的なバグ | `/bug-analysis` | バグパターン分類・原因調査・修正 |
| HTMLパーサー失敗 | `/parser-repair` | 検索エンジンのセレクター診断・修正 |

## 問題の種類を判断する基準

### モジュール間連動の問題 → `/integration-design`
- 複数モジュールにまたがるデータフローの問題
- 型の不整合（モジュールAの出力がモジュールBの入力と合わない）
- 非同期処理の連携問題
- 「個別には動くが、組み合わせると動かない」

### 一般的なバグ → `/bug-analysis`
- 単一モジュール内のバグ
- 例外処理の問題
- リソースリーク
- 競合状態
- Null参照

### パーサー失敗 → `/parser-repair`
- 検索エンジンのHTML構造変更
- CSSセレクターの不一致
- スクレイピング結果が空

## 使い方

### 1. 問題の種類を特定

症状を確認し、上記の基準で問題の種類を判断。

### 2. 該当コマンドを実行

```
/integration-design  # モジュール間連動の問題
/bug-analysis        # 一般的なバグ
/parser-repair       # パーサー失敗
```

### 3. 修正後の検証

```
/quality-check      # lint/型チェック
/regression-test    # 全テスト実行（非同期実行→ポーリングで完了確認）
/commit             # コミット
```

**回帰テストの実行例**:
```bash
# テスト開始
./scripts/test.sh run tests/

# 完了までポーリング（最大5分、5秒間隔）
for i in {1..60}; do
    sleep 5
    status=$(./scripts/test.sh check 2>&1)
    echo "[$i] $status"
    # 完了判定: "DONE"またはテスト結果キーワード（passed/failed/skipped）が含まれる
    if echo "$status" | grep -qE "(DONE|passed|failed|skipped|deselected)"; then
        break
    fi
done

# 結果取得
./scripts/test.sh get
```

## 関連ルール
- コード実行時: @.cursor/rules/code-execution.mdc
- 連動設計: @.cursor/rules/integration-design.mdc
- リファクタ関連: @.cursor/rules/refactoring.mdc

## 完了条件チェックリスト
- [ ] 問題の原因が特定できた
- [ ] 修正を実装した
- [ ] 品質確認済み（lint/型エラーなし）
- [ ] 回帰テストパス
- [ ] コミット完了
