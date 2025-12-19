# parser-repair

検索エンジンのHTMLパーサーが失敗した際に、AI支援で修正を行う。

## 関連ファイル
- セレクター設定: @config/search_parsers.yaml
- パーサー実装: @src/search/search_parsers.py
- 診断モジュール: @src/search/parser_diagnostics.py

## 関連ルール
- コード実行時: @.cursor/rules/code-execution.mdc

## ワークフロー概要

```
┌─────────────────────────────────────────────────────────────┐
│  1. 失敗HTML取得    debug/search_html/ から最新を取得        │
│         ↓                                                    │
│  2. 診断レポート生成  候補セレクターを分析                    │
│         ↓                                                    │
│  3. 修正案提示      YAML形式で修正案を提示                   │
│         ↓                                                    │
│  4. 修正適用        config/search_parsers.yaml を更新        │
│         ↓                                                    │
│  5. 検証            E2Eスクリプトで動作確認                  │
└─────────────────────────────────────────────────────────────┘
```

## 使い方

### 1. 最新の失敗HTMLを分析

```bash
# コンテナ内で診断スクリプトを実行
podman exec lyra python -c "
from src.search.parser_diagnostics import get_latest_debug_html, analyze_debug_html
import json

path = get_latest_debug_html()
if path:
    report = analyze_debug_html(path)
    if report:
        print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
else:
    print('No debug HTML found')
"
```

### 2. 特定エンジンの失敗HTMLを分析

```bash
# DuckDuckGoの最新失敗を分析
podman exec lyra python -c "
from src.search.parser_diagnostics import get_latest_debug_html, analyze_debug_html
import json

path = get_latest_debug_html('duckduckgo')
if path:
    report = analyze_debug_html(path)
    if report:
        print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
"
```

### 3. 修正を適用後、検証

```bash
# 検索エンジンごとのE2E検証スクリプト
podman exec lyra python tests/scripts/verify_duckduckgo_search.py
podman exec lyra python tests/scripts/verify_ecosia_search.py
podman exec lyra python tests/scripts/verify_startpage_search.py
```

## 診断レポートの読み方

診断レポートには以下の情報が含まれる:

| フィールド | 説明 |
|-----------|------|
| `engine` | 検索エンジン名 |
| `failed_selectors` | 失敗したセレクターの詳細 |
| `candidate_elements` | HTML内で検出された候補要素 |
| `suggested_fixes` | YAML形式の修正案 |
| `html_path` | デバッグ用に保存されたHTMLのパス |

### candidate_elements の解釈

- `selector`: 候補となるCSSセレクター
- `confidence`: 信頼度（0.0〜1.0）
- `occurrence_count`: HTML内での出現回数
- `reason`: 候補として選ばれた理由

## 修正手順

1. **診断レポートを確認**: `suggested_fixes` を確認
2. **HTMLを目視確認**: `html_path` のファイルをブラウザで開いて構造を確認
3. **セレクターを修正**: `config/search_parsers.yaml` を編集
4. **ホットリロード確認**: 設定は自動で再読み込みされる（30秒間隔）
5. **E2E検証**: 修正後のパーサーが正常動作するか確認

## よくある失敗パターン

### パターン1: クラス名変更
検索エンジンがCSSクラス名を変更した場合。
- 診断: `candidate_elements` に新しいクラス名が出現
- 対応: `selector` を新しいクラス名に更新

### パターン2: HTML構造変更
検索エンジンがDOM構造を変更した場合。
- 診断: `occurrence_count` が期待と異なる
- 対応: 親子関係を確認してセレクターを調整

### パターン3: data-testid追加
モダンなフレームワーク移行でdata-testid属性が追加された場合。
- 診断: `[data-testid='...']` が候補に出現
- 対応: data-testid属性を優先使用（安定性が高い）

## 出力
- 診断レポート（JSON形式）
- 修正案（YAML形式）
- 検証結果

