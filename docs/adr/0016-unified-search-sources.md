# ADR-0016: Unified Search Sources

## Date
2025-12-26

## Status
Accepted

## Context

以前の検索パイプラインでは、クエリを「学術的」か「一般的」かで判定（`is_academic`フラグ）し、ルーティングを分岐していた：

```
学術クエリ判定  ─┬─→ 学術API優先（S2/OpenAlex）→ Abstract利用 or ブラウザfallback
                └─→ ブラウザSERP優先 → identifier検出時のみ学術API補完
```

### 問題点

| 問題 | 詳細 |
|------|------|
| 判定の不安定性 | キーワードベースの判定（"paper", "doi:", site:arxiv.org等）は偽陽性・偽陰性が発生 |
| 網羅性の低下 | 学術クエリでSERP、一般クエリで学術APIを呼ばないためカバレッジが限定的 |
| コードの複雑化 | 分岐ロジックが `_is_academic_query()`, `_expand_academic_query()` 等で分散 |
| メンテナンス負荷 | 判定条件の調整が困難、テストケースの組み合わせ爆発 |

### 実測データからの示唆

- 一般クエリでも高確率でDOI/arXiv IDを含むSERP結果が返る
- 学術クエリでもWikipedia/ブログ等の有益なソースがSERPに含まれる
- Abstract-onlyで十分な論文が多く、fetch不要でEvidenceが得られる

## Decision

**すべてのクエリでBrowser SERPと学術API（Semantic Scholar + OpenAlex）の両方を常に並列実行し、結果をマージ・重複排除する。**

### 統一検索フロー

```
┌─────────────────────────────────────────────────────────────┐
│ SearchPipeline._execute_unified_search()                    │
│                                                             │
│   ┌─────────────────┐     ┌─────────────────┐              │
│   │ search_serp()   │     │ AcademicSearch- │              │
│   │ (Browser SERP)  │     │ Provider.search │              │
│   └────────┬────────┘     └────────┬────────┘              │
│            │                       │                        │
│            └───────────┬───────────┘                        │
│                        ▼                                    │
│            ┌─────────────────────┐                          │
│            │ CanonicalPaperIndex │  重複排除（DOI/title）   │
│            └──────────┬──────────┘                          │
│                       ▼                                     │
│            ┌─────────────────────┐                          │
│            │ Abstract-only or    │  ADR-0008に従う          │
│            │ Browser fetch       │                          │
│            └──────────┬──────────┘                          │
│                       ▼                                     │
│            ┌─────────────────────┐                          │
│            │ Citation graph      │  Abstract有の論文のみ    │
│            │ (get_citation_graph)│                          │
│            └─────────────────────┘                          │
└─────────────────────────────────────────────────────────────┘
```

### 重複排除戦略

`CanonicalPaperIndex`（ADR-0008で導入）を活用：

1. **DOI一致**: 同一DOIはマージ（APIメタデータ優先）
2. **タイトル類似度**: 正規化タイトルで90%以上類似はマージ候補
3. **ソース属性保持**: `source: "both" | "api_only" | "serp_only"` で追跡

### 削除されたコード

- `SearchPipeline._is_academic_query()` - クエリ判定ロジック
- `SearchPipeline._expand_academic_query()` - 学術クエリ拡張
- `_execute_normal_search()` 内の条件分岐

### 変更されたメソッド

| メソッド | 変更内容 |
|---------|---------|
| `_execute_normal_search()` | 常に `_execute_unified_search()` を呼び出す |
| `_execute_unified_search()` | 旧 `_execute_complementary_search()` をリネーム |
| `_execute_browser_search()` | fetch/extract専用に簡素化（SERPは呼ばない） |

## Consequences

### Positive

1. **網羅性向上**: 全クエリで両ソースを検索するためカバレッジが向上
2. **コード簡素化**: 判定ロジックが不要となりメンテナンス性向上
3. **テスト容易化**: 分岐条件がなくなり、テストケースが単純化
4. **一貫した挙動**: クエリ内容に関わらず同じパスを通る

### Negative

1. **API消費増加**: 一般クエリでも学術APIを呼ぶためレート消費が増加
2. **レイテンシ増加**: 並列実行でも遅い方に引っ張られる可能性

### Mitigation

- **レート制限**: ADR-0013のグローバルレートリミッターで保護済み
- **タイムアウト**: 学術APIには適切なタイムアウトを設定
- **失敗耐性**: 片方の失敗は他方に影響しない（`try/except`で分離）

## Alternatives Considered

### A. 判定ロジックの改善

**却下理由**: 
- キーワード/パターンマッチングの限界
- 機械学習モデル導入はZero OpEx違反（ADR-0001）
- 「学術的かどうか」より「両方見る」方が確実

### B. ユーザー選択式

**却下理由**:
- UX負荷増（Cursor AIエージェントは自動判断が前提）
- 選択を忘れるとカバレッジ低下

### C. 段階的フォールバック（SERP→API or API→SERP）

**却下理由**:
- 順序による遅延増
- 並列のほうがシンプルかつ高速

## Implementation Status

**Status**: ✅ Implemented (2025-12-26)

- `src/research/pipeline.py`: 統一検索フロー実装完了
- `tests/test_research.py`: `TestUnifiedDualSourceSearch` テストクラス追加
- Debug instrumentation（agent log）を削除

## Related

- [ADR-0008: Academic Data Source Strategy](0008-academic-data-source-strategy.md) - 学術API選定とCanonicalPaperIndex
- [ADR-0013: Worker Resource Contention Control](0013-worker-resource-contention.md) - 学術APIレート制限
- [ADR-0014: Browser SERP Resource Control](0014-browser-serp-resource-control.md) - ブラウザSERPリソース制御

