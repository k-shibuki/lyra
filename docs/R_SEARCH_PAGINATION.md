# 検索ページネーション機能

> **Status**: 🔜 PLANNED（実装待ち）

> **Scope / Assumptions**:
> - Q_ASYNC_ARCHITECTURE.md Phase 3 完了後に着手
> - ADR-0013 への追記で対応（ブラウザリソース制御の拡張として）
> - 既存コード資産の拡張で実装可能

## Executive Summary

**問題の本質:** 現在の検索機能は結果の1ページ目のみ取得可能。2ページ目以降の結果には到達できない。

**解決策:** ページネーション機能を追加し、複数ページの結果を取得可能にする
- `SearchOptions.page` パラメータを実際に使用
- 各エンジンのページネーションURL構築対応
- 自動停止判断ロジック（飽和検知・収穫率ベース）

**工数見積:** 約14時間（2日）

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

- `SearchOptions.page` パラメータは定義済みだが**未使用**
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
| 設定外部化 | `config/search_parsers.yaml` | 実装済み |

### 2.2 各エンジンのページネーションパラメータ

| エンジン | パラメータ形式 | 例（2ページ目） | 結果数/ページ |
|---------|---------------|-----------------|---------------|
| DuckDuckGo | `s={offset}` | `s=30` | 約30件 |
| Google | `start={offset}` | `start=10` | 10件 |
| Bing | `first={offset}` | `first=11` | 10件 |
| Mojeek | `s={offset}` | `s=10` | 10件 |
| Brave | `offset={offset}` | `offset=10` | 10件 |
| Ecosia | `p={page}` | `p=1` | 10件 |
| Startpage | `page={page}` | `page=2` | 10件 |

**注意**: offset方式とpage方式が混在。抽象化レイヤーが必要。

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
    max_pages: int = 5           # 絶対上限
    min_novelty_rate: float = 0.2  # 新規URL率の下限
    min_harvest_rate: float = 0.05 # 収穫率の下限

    def should_fetch_next(
        self,
        current_page: int,
        novelty_rate: float,
        harvest_rate: float,
    ) -> bool:
        if current_page >= self.max_pages:
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

**ファイル**: `config/search_parsers.yaml`

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
    max_pages: int = 5
    min_novelty_rate: float = 0.2
    min_harvest_rate: float = 0.05
    strategy: Literal["fixed", "auto", "exhaustive"] = "auto"

class PaginationStrategy:
    def __init__(self, config: PaginationConfig): ...
    def should_fetch_next(self, context: PaginationContext) -> bool: ...
    def calculate_novelty_rate(self, new_urls: list[str], seen_urls: set[str]) -> float: ...
```

### 4.4 DB変更（任意）

```sql
-- serp_items に追加（推奨）
ALTER TABLE serp_items ADD COLUMN page_number INTEGER DEFAULT 1;
```

---

## 5. 工数見積もり

| 作業 | 難易度 | 工数 |
|------|--------|------|
| search_parsers.yaml 更新 | 低 | 0.5h |
| parser_config.py 更新 | 低 | 1h |
| browser_search_provider.py 更新（エンジン別Semaphore含む） | 中 | 3h |
| pagination_strategy.py 新規作成 | 中 | 2h |
| 非同期キューとの統合 | 中 | 1.5h |
| エラーハンドリング・ロールバック | 低 | 1h |
| テスト追加（モック戦略含む） | 中 | 3h |
| 結合テスト・デバッグ | 中 | 2h |
| **合計** | | **14h（約2日）** |

---

## 6. ADR判断

### 結論: ADR-0013への追記で対応

**理由:**
- ページネーションはブラウザリソース制御（ADR-0013）の拡張
- `Semaphore(1)` の制約をエンジン別に細分化する提案と関連
- 既存の `BrowserSearchProvider` 内で閉じた変更

### ADR-0013への追記案

```markdown
### Pagination Strategy

検索結果のページネーション制御:

| パラメータ | デフォルト | 説明 |
|-----------|-----------|------|
| max_pages | 3 | 取得する最大ページ数 |
| stop_strategy | "auto" | 停止戦略 (fixed/auto/exhaustive) |

**自動停止条件** (strategy="auto"):
- 新規URL率 < 20%
- 収穫率 < 5%
- max_pages到達
```

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

# 変更後（page追加）
cache_key = f"{normalized_query}|{engines}|{time_range}|page={page}"
```

### 7.3 結果のマージ

複数ページの結果をマージする際:
- URL重複排除が必要
- rank の再計算が必要
- エンジン間の結果混合に注意

### 7.4 非同期アーキテクチャとの統合

**現状**: `queue_searches` → `search_action` → `BrowserSearchProvider.search()` は単一ページ取得を前提。

**対応方針**:
- 1クエリ = 1ジョブ（複数ページは同一ジョブ内で逐次取得）
- `jobs.input_json` に `max_pages` を含める
- 進捗通知は最初のページ取得完了時点で行う
- `stop_task(mode=immediate)` 時は取得済みページの結果を保持

### 7.5 ワーカーリソース制約

**現状の制約**: `BrowserSearchProvider` は `Semaphore(1)` で保護（同時1リクエスト）

```python
# browser_search_provider.py:159
self._rate_limiter = asyncio.Semaphore(1)  # グローバル1並列
```

**問題**: 複数ページ取得時、他タスクのSERP取得がブロックされる時間が増大。

**改善提案**: エンジン別 Semaphore + タブプール

```python
class BrowserSearchProvider:
    def __init__(self, ...):
        # エンジン別 Semaphore（同一エンジンへの同時リクエストは1つ）
        self._engine_locks: dict[str, asyncio.Semaphore] = {}

    def _get_engine_lock(self, engine: str) -> asyncio.Semaphore:
        if engine not in self._engine_locks:
            self._engine_locks[engine] = asyncio.Semaphore(1)
        return self._engine_locks[engine]
```

**効果**: DuckDuckGo と Mojeek への同時リクエストが可能になり、ブロックリスクを増やさずに並列度が向上。

### 7.6 エラーハンドリング

| シナリオ | 対応方針 |
|---------|---------|
| N+1ページ目でCAPTCHA | 1〜Nページの結果は保持、介入キューへ追加 |
| N+1ページ目でタイムアウト | 部分成功として扱う（エラーはログのみ） |
| ページ間でエンジン切り替え | 禁止（同一エンジンで継続） |

### 7.7 ロールバック手順

1. **即時無効化**: `config/search_parsers.yaml` で `max_pages: 1` を設定
2. **DBロールバック**: `ALTER TABLE serp_items DROP COLUMN page_number;`
3. **部分無効化**: エンジン別に `pagination_enabled: false` を設定

---

## 8. 実装タスク

### Phase 1: 基盤整備
- [ ] `config/search_parsers.yaml` にページネーションパラメータ追加
- [ ] `src/search/parser_config.py` でページネーション設定読み込み
- [ ] `build_search_url()` にoffset/page引数追加

### Phase 2: 検索プロバイダー対応
- [ ] `browser_search_provider.py` で `options.page` を使用
- [ ] キャッシュキーにページ番号含める
- [ ] `SearchResponse` にページ情報追加（任意）

### Phase 3: 停止判断ロジック
- [ ] `pagination_strategy.py` 新規作成
- [ ] 飽和検知ロジック実装
- [ ] 収穫率ベース停止実装
- [ ] 設定可能なストラテジー選択

### Phase 4: 統合・テスト
- [ ] 単体テスト追加
- [ ] 結合テスト（実エンジン）
- [ ] ADR-0010への追記

### Phase 5: DB拡張（任意）
- [ ] `serp_items.page_number` カラム追加
- [ ] マイグレーションスクリプト作成

---

## 9. 参考資料

- `src/search/browser_search_provider.py` - 検索プロバイダー実装
- `src/search/provider.py` - SearchOptions, SearchResponse定義
- `src/search/search_parsers.py` - 各エンジンのパーサー
- `config/search_parsers.yaml` - パーサー設定
- `docs/adr/0010-async-search-queue.md` - 非同期検索キューADR
- `docs/adr/0013-worker-resource-contention.md` - ワーカーリソース競合制御ADR
- `src/storage/schema.sql` - DBスキーマ
