# 検索ページネーション機能 調査メモ

> 作成日: 2025-12-24
>
> 目的: WEB検索で到達できないページの問題を調査し、ページネーション実装の可否を検討

---

## 1. 現状の制限: 到達できないページ

### 1.1 ページネーション未実装（最重要）

現在の実装では検索結果の**1ページ目のみ**取得可能。

```python
# src/search/browser_search_provider.py:948
results = [r.to_search_result(engine) for r in parse_result.results[: options.limit]]
```

- `SearchOptions.page` パラメータは定義されているが**未使用**
- 次ページボタンのクリック: 未実装
- URLパラメータでのページ指定 (`&start=10` 等): 未実装
- 最大取得件数: 1ページあたり10〜100件

### 1.2 未実装エンジン（パーサーなし）

以下のエンジンは `engines.yaml` に定義されているが、パーサーが存在しない:

| エンジン | 状態 | 備考 |
|---------|------|------|
| Wikipedia | パーサーなし | ナレッジソース |
| Wikidata | パーサーなし | 構造化データ |
| Marginalia | パーサーなし | インディーWeb検索 |
| Arxiv | パーサーなし | 学術論文（APIは別途実装あり） |
| PubMed | パーサーなし | 医学論文（APIは別途実装あり） |
| Qwant | パーサーなし | プライバシー重視検索 |

指定すると `No parser available for engine: {engine}` エラー。

### 1.3 日次制限

ラストマイルエンジンには厳格な日次制限がある（ADR-0010）:

| エンジン | 日次制限 | QPS |
|---------|---------|-----|
| Google | 10回/日 | 0.05 |
| Bing | 10回/日 | 0.05 |
| Brave | 50回/日 | 0.1 |
| Mojeek | 制限なし | 0.25 |
| DuckDuckGo | 制限なし | 0.2 |

### 1.4 その他の到達不可パターン

| パターン | 原因 | 対応 |
|---------|------|------|
| CAPTCHA | bot検出 | 手動介入キュー (ADR-0007) |
| サーキットブレーカー | 2回連続失敗 | 30〜120分クールダウン |
| タイムアウト | 30秒超過 | リトライなし |
| セレクタ破損 | HTML構造変更 | YAML修正で対応可 |

---

## 2. ページネーション実装の可能性

### 2.1 結論: 実装は現実的

既存コード資産の拡張で対応可能。モジュール新設は不要。

### 2.2 既に揃っている要素

| 要素 | 場所 | 状態 |
|------|------|------|
| `page` パラメータ | `SearchOptions` (provider.py:141) | 定義済み・未使用 |
| URL構築基盤 | `build_search_url()` | 実装済み |
| 結果パーサー | `search_parsers.py` | 7エンジン対応済み |
| 設定外部化 | `config/search_parsers.yaml` | 実装済み |

### 2.3 各エンジンのページネーションパラメータ

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

**LLM判断は不要**: 機械的ルール + 既存メトリクスで十分。

---

## 4. 必要な変更

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

google:
  search_url: "https://www.google.com/search?q={query}&hl={language}&tbs={time_range}&start={offset}"
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

### 4.3 DB変更（任意）

```sql
-- serp_items に追加（推奨）
ALTER TABLE serp_items ADD COLUMN page_number INTEGER DEFAULT 1;

-- cache_serp のキー計算にpage含める
-- (コード側の変更のみ、スキーマ変更なし)
```

### 4.4 停止判断ロジック追加

**新規ファイル**: `src/search/pagination_strategy.py`

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

---

## 5. 工数見積もり

| 作業 | 難易度 | 工数 |
|------|--------|------|
| search_parsers.yaml 更新 | 低 | 0.5h |
| parser_config.py 更新 | 低 | 1h |
| browser_search_provider.py 更新 | 中 | 2h |
| pagination_strategy.py 新規作成 | 中 | 2h |
| テスト追加 | 中 | 2h |
| 結合テスト・デバッグ | 中 | 1.5h |
| **合計** | | **9h（約1.5日）** |

---

## 6. ADR判断

### 結論: 新規ADR不要、ADR-0010への追記で対応

**理由**:
- ページネーション実装は既存アーキテクチャの拡張
- `queue_searches` の仕様拡張として自然に収まる
- 重大なトレードオフ決定は含まれない

### ADR-0010への追記案

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

### 新規ADRが必要になるケース

- 停止判断にLLMを使う決定
- マルチエンジン並列ページネーション導入
- 優先度付きページ取得

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

---

## 8. 実装タスク一覧

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
- `src/storage/schema.sql` - DBスキーマ
