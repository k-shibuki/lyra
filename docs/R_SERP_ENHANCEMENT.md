# SERP Enhancement（ブラウザ検索強化）

> **Status**: 🚧 IN PROGRESS（実装中）
>
> **Phase Mapping**: Q_ASYNC_ARCHITECTURE.md **Phase 5** として実装
> **Related ADRs**: ADR-0014（Browser SERP Resource Control）, ADR-0015（Adaptive Concurrency）

> **Scope / Assumptions**:
> - Q_ASYNC_ARCHITECTURE.md Phase 4 完了後に着手（Phase 5 で実装）
> - ADR-0014（Browser SERP Resource Control）を前提
> - 既存コード資産の拡張で実装可能
> - **実装開始**: 2025-12-25（設定ファイル追加完了）

## Executive Summary

**問題の本質:** 現在の検索機能は結果の1ページ目のみ取得可能。2ページ目以降の結果には到達できない。

**解決策:** ページネーション機能を追加し、複数ページの結果を取得可能にする
- `SearchOptions.serp_page` パラメータを実際に使用（旧 `SearchOptions.page` は削除済み / 互換なし）
- 各エンジンのページネーションURL構築対応
- 自動停止判断ロジック（飽和検知・収穫率ベース）

**前提条件:** ADR-0014 で定義された TabPool（max_tabs=1）導入により、ブラウザSERPが「Page競合なし」で実行できること

**工数見積:** 約10時間（1.5日）※ADR-0014（TabPool導入）完了後

---

## 1. 現状の問題点

### 1.1 到達できないページ

| カテゴリ | 問題 | 影響度 |
|---------|------|--------|
| ページネーション未実装 | 検索結果の2ページ目以降に到達不可 | **高** |
| 未実装エンジン | Wikipedia, Arxiv等にパーサーなし | 中 |
| 日次制限 | Google/Bing: 10回/日 | 中 |
| CAPTCHA | bot検出でブロック | 低（介入キューで対応） |

### 1.2 ページネーション未実装の詳細

**現在のコード:**
```python
# src/search/browser_search_provider.py:948
results = [r.to_search_result(engine) for r in parse_result.results[: options.limit]]
```

- `SearchOptions.serp_page` パラメータは定義済みだが**未使用**
- 最大取得件数: 1ページあたり10〜100件
- 次ページ取得手段なし

### 1.3 未実装エンジン（パーサーなし）

| エンジン | 状態 | 備考 |
|---------|------|------|
| Wikipedia | パーサーなし | ナレッジソース |
| Wikidata | パーサーなし | 構造化データ |
| Marginalia | パーサーなし | インディーWeb検索 |
| Arxiv | パーサーなし | APIは別途実装あり |
| PubMed | パーサーなし | APIは別途実装あり |
| Qwant | パーサーなし | プライバシー重視検索 |

### 1.4 日次制限（ADR-0010）

| エンジン | 日次制限 | QPS | 備考 |
|---------|---------|-----|------|
| Google | 10回/日 | 0.05 | ラストマイル |
| Bing | 10回/日 | 0.05 | ラストマイル |
| Brave | 50回/日 | 0.1 | ラストマイル |
| Mojeek | 制限なし | 0.25 | デフォルト |
| DuckDuckGo | 制限なし | 0.2 | デフォルト |

---

## 2. 解決策

### 2.1 既存資産の活用

| 要素 | 場所 | 状態 |
|------|------|------|
| `page` パラメータ | `SearchOptions` (provider.py:141) | 定義済み・未使用 |
| URL構築基盤 | `build_search_url()` | 実装済み |
| 結果パーサー | `search_parsers.py` | 7エンジン対応済み |
| 設定外部化 | `config/search_parsers.yaml` | 実装済み（URLテンプレ/selector） |
| エンジンpolicy | `config/engines.yaml` | 実装済み（QPS/利用可否/重み等） |
| **TabPool（Page競合排除）** | `BrowserSearchProvider` | **ADR-0014で実装予定** |

### 2.2 各エンジンのページネーションパラメータ

**serp_page の仕様:**
- **1始まり**（1ページ目 = `serp_page=1`）
- 実装: `src/search/provider.py` の `SearchOptions.serp_page` は `default=1, ge=1` で定義済み
- offset計算の基本式: `offset = (serp_page - 1) * results_per_page`

**エンジン選択とページネーション:**
- 1回の検索リクエストに対して**1つのエンジンが選択**される（重み付き選択）
- 選択されたエンジンで `serp_max_pages` まで取得
- **どのエンジンが選択されてもページネーションが機能**する設計

| エンジン | パラメータ形式 | 計算式（serp_page=N） | 例（2ページ目） | 結果数/ページ |
|---------|---------------|----------------------|-----------------|---------------|
| DuckDuckGo | `s={offset}` | `s = (N - 1) * 30` | `s=30` | 約30件 |
| Google | `start={offset}` | `start = (N - 1) * 10` | `start=10` | 10件 |
| Bing | `first={offset}` | `first = (N - 1) * 10 + 1` | `first=11` | 10件 |
| Mojeek | `s={offset}` | `s = (N - 1) * 10` | `s=10` | 10件 |
| Brave | `offset={offset}` | `offset = (N - 1) * 10` | `offset=10` | 10件 |
| Ecosia | `p={page}` | `p = N - 1` | `p=1` | 10件 |
| Startpage | `page={page}` | `page = N` | `page=2` | 10件 |

**注意**: offset方式とpage方式が混在。`config/search_parsers.yaml` の `pagination_type` で抽象化。

---

## 3. 停止判断ロジック

### 3.1 アプローチ比較

| 方式 | 説明 | メリット | デメリット |
|------|------|----------|------------|
| 固定ページ数 | 常にN枚取得 | 予測可能、シンプル | 非効率 |
| 飽和検知 | 新規URL率で判定 | 適応的 | ドメイン多様性無視 |
| 収穫率ベース | 関連フラグメント率で判定 | Lyra固有メトリクス活用 | 計算コスト |
| LLM判断 | クエリ性質を解析 | 高精度 | 高コスト、レイテンシ |

### 3.2 推奨: ハイブリッドアプローチ

```python
class PaginationStrategy:
    serp_max_pages: int = 10       # 絶対上限（SERPページ数）→ 100〜300件取得可能
    min_novelty_rate: float = 0.1  # 新規URL率の下限（state.py の既存閾値と整合）
    min_harvest_rate: float = 0.05 # 収穫率の下限

    def should_fetch_next(
        self,
        current_page: int,
        novelty_rate: float,
        harvest_rate: float,
    ) -> bool:
        if current_page >= self.serp_max_pages:
            return False
        if novelty_rate < self.min_novelty_rate:
            return False
        if harvest_rate < self.min_harvest_rate:
            return False
        return True
```

### 3.3 Lyra既存メトリクスの活用

| メトリクス | テーブル/フィールド | 活用方法 |
|-----------|-------------------|----------|
| 収穫率 | `queries.harvest_rate` | 閾値判定 |
| URL重複 | `serp_items.url` | 飽和検知 |
| タスク種別 | `_detect_category()` | 深度プリセット |
| エンジン状態 | `engine_health` | 取得可能性判定 |

**結論**: LLM判断は不要。機械的ルール + 既存メトリクスで十分。

---

## 4. 実装計画

### 4.1 設定ファイル変更

**ファイル**: `config/search_parsers.yaml`（ページネーションのURL/結果数）

```yaml
# 各エンジンに追加
duckduckgo:
  search_url: "https://duckduckgo.com/?q={query}&kl={region}&df={time_range}&s={offset}"
  results_per_page: 30
  pagination_type: "offset"  # offset | page

mojeek:
  search_url: "https://www.mojeek.com/search?q={query}&t={time_range}&s={offset}"
  results_per_page: 10
  pagination_type: "offset"
```

### 4.2 コード変更

| ファイル | 変更内容 | 行数目安 |
|---------|---------|---------|
| `src/search/parser_config.py` | ページネーション設定読み込み | +15行 |
| `src/search/search_parsers.py` | `build_search_url()` にoffset/page対応 | +10行 |
| `src/search/browser_search_provider.py` | `search()` でpage活用 | +20行 |
| `src/search/provider.py` | `SearchResponse` にpage情報追加（任意） | +5行 |

### 4.3 新規ファイル

**ファイル**: `src/search/pagination_strategy.py`

```python
@dataclass
class PaginationConfig:
    serp_max_pages: int = 10       # 100〜300件取得可能（エンジンにより10〜30件/ページ）
    min_novelty_rate: float = 0.1  # state.py の既存閾値（novelty_score < 0.1 で EXHAUSTED）と整合
    min_harvest_rate: float = 0.05
    strategy: Literal["fixed", "auto", "exhaustive"] = "auto"

class PaginationStrategy:
    def __init__(self, config: PaginationConfig): ...
    def should_fetch_next(self, context: PaginationContext) -> bool: ...
    def calculate_novelty_rate(self, new_urls: list[str], seen_urls: set[str]) -> float: ...
```

### 4.4 DB変更（必須）

```sql
-- serp_items に追加（監査/再現性をDB側で担保）
ALTER TABLE serp_items ADD COLUMN page_number INTEGER DEFAULT 1;
```

**設計判断:**
- `serp_items.page_number` は **必須** とする
- 監査/再現性をDB側で担保（どのSERPページから取得されたかを追跡可能）
- `jobs.output_json` への依存を避け、正規化された形でデータを保持

---

## 5. 工数見積もり

| 作業 | 難易度 | 工数 |
|------|--------|------|
| search_parsers.yaml 更新 | 低 | 0.5h |
| parser_config.py 更新 | 低 | 1h |
| browser_search_provider.py 更新 | 中 | 2h |
| pagination_strategy.py 新規作成 | 中 | 2h |
| 非同期キューとの統合 | 中 | 1.5h |
| エラーハンドリング・ロールバック | 低 | 1h |
| テスト追加（モック戦略含む） | 中 | 2h |
| **合計** | | **10h（約1.5日）** |

**Note**: ADR-0014 Phase 1（TabPool: max_tabs=1）は別工数（Phase 4で実装）。

---

## 6. ADR判断

### 結論: ADR-0014を前提として本ドキュメントで詳細設計

**構造:**
- **ADR-0014**: Browser SERP Resource Control（アーキテクチャ決定）
  - TabPool（Phase 1: max_tabs=1）
  - max_tabs>1 の段階的解放（将来）
- **本ドキュメント（R_）**: SERP Enhancement（機能詳細設計）
  - ページネーションURL構築
  - 停止判断ロジック
  - キャッシュ/マージ戦略

---

## 7. 注意事項

### 7.1 レート制限との兼ね合い

ページネーションで複数ページを取得すると:
- QPS制限にひっかかりやすい
- 日次制限を早く消費する
- CAPTCHAリスクが上昇

**対策**: ラストマイルエンジン（Google/Bing/Brave）はページネーション無効化を検討。

### 7.2 キャッシュ整合性

```python
# 現在のキャッシュキー
cache_key = f"{normalized_query}|{engines}|{time_range}"

# 変更後（serp_max_pages を追加）
cache_key = f"{normalized_query}|{engines}|{time_range}|serp_max_pages={max_pages}"
```

**キャッシュキー設計:**
- `serp_max_pages` をキャッシュキーに含める（異なるページ設定は異なるキャッシュエントリ）
- 1検索=1エンジン選択のため、結果はそのエンジンの全ページをマージしたものがキャッシュされる
- `pagination_type` / `results_per_page` は**キャッシュキーに含めない**（設定変更時はTTL経過 or 手動クリア）

### 7.2.1 ページ上限パラメータの意味の分離（重要）

本プロジェクトには「ページ上限」が複数の意味で登場するため、実装時に混線しやすい：

- **クロール予算（budget）**: 研究パイプライン側の `budget_pages`
- **SERPページネーション**: `serp_page` / `serp_max_pages`（本機能）

**方針**: **互換なし**でSERP用パラメータを `serp_page` / `serp_max_pages` に統一し、旧 `SearchOptions.page` は削除する。

### 7.3 結果のマージ

同一エンジンの複数ページ結果をマージする際:
- URL重複排除が必要（ページ間で同じURLが出現する場合あり）
- rank は取得順で決定（ページ1の結果が先、ページ2が後）
- 1検索=1エンジンのため、エンジン間混合の考慮は不要

### 7.4 非同期アーキテクチャとの統合

**現状**: `queue_searches` → `search_action` → `BrowserSearchProvider.search()` は単一ページ取得を前提。

**対応方針**:
- 1クエリ = 1ジョブ（複数ページは同一ジョブ内で逐次取得）
- `jobs.input_json` に `budget_pages` / `serp_page` / `serp_max_pages` を含める
- 進捗通知は最初のページ取得完了時点で行う
- `stop_task(mode=immediate)` 時は取得済みページの結果を保持

### 7.5 リソース制御（ADR-0014参照）

> **Note**: TabPool（max_tabs=1）および段階的な並列化の設計は [ADR-0014](adr/0014-browser-serp-resource-control.md) を参照。
> 本ドキュメントはADR-0014のリソース制御が実装済みであることを前提とする。

### 7.6 エラーハンドリング

| シナリオ | 対応方針 |
|---------|---------|
| N+1ページ目でCAPTCHA | 1〜Nページの結果は保持、介入キューへ追加 |
| N+1ページ目でタイムアウト | 部分成功として扱う（エラーはログのみ） |
| ページ間でエンジン切り替え | 禁止（同一エンジンで継続） |

### 7.7 ロールバック手順

1. **即時無効化**: `serp_max_pages: 1`（または `pagination_enabled: false`）を設定
2. **DBロールバック**: `ALTER TABLE serp_items DROP COLUMN page_number;`
3. **部分無効化**: エンジン別に `pagination_enabled: false` を設定

---

## 8. 実装タスク

### Phase 1: 基盤整備
- [x] `config/search_parsers.yaml` にページネーションパラメータ追加（pagination_type, results_per_page, offset/page テンプレート）
- [ ] `src/search/parser_config.py` でページネーション設定読み込み
- [ ] `build_search_url()` にoffset/page引数追加

### Phase 2: 検索プロバイダー対応
- [ ] `browser_search_provider.py` で `options.serp_page` を使用
- [ ] キャッシュキーにページ番号含める（`serp_page` を使用、`budget_pages` はクロール予算であり別概念）
- [ ] `SearchResponse` にページ情報追加（任意）

### Phase 3: 停止判断ロジック
- [ ] `pagination_strategy.py` 新規作成
- [ ] 飽和検知ロジック実装
- [ ] 収穫率ベース停止実装
- [ ] 設定可能なストラテジー選択

### Phase 4: 統合・テスト
- [ ] 単体テスト追加
- [ ] 結合テスト（実エンジン）
- [ ] Q_ASYNC / ADR更新

### Phase 5: DB拡張（必須）
- [ ] `serp_items.page_number` カラム追加（監査/再現性をDB側で担保）
- [ ] スキーマを更新し、DBを作り直し（開発フェーズなので破壊的にやる。マイグレーションではない）

---

## 9. 参考資料

- `src/search/browser_search_provider.py` - 検索プロバイダー実装
- `src/search/provider.py` - SearchOptions, SearchResponse定義
- `src/search/search_parsers.py` - 各エンジンのパーサー
- `config/search_parsers.yaml` - パーサー設定
- `docs/adr/0010-async-search-queue.md` - 非同期検索キューADR
- `docs/adr/0014-browser-serp-resource-control.md` - ブラウザSERPリソース制御ADR
- `docs/Q_ASYNC_ARCHITECTURE.md` - 非同期アーキテクチャ（Phase 5で本機能実装）
- `src/storage/schema.sql` - DBスキーマ

