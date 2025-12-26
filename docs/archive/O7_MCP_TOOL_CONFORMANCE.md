> **⚠️ ARCHIVED DOCUMENT**
>
> This document is an archived snapshot of the project's development history and is no longer maintained.
> Content reflects the state at the time of writing and may be inconsistent with the current codebase.
>
> **Archived**: 2025-12-20

# O.7 MCPツール仕様適合性検証

## 調査日: 2025-12-15

Phase O.6完了後、MCPツール（11個）が仕様書（REQUIREMENTS.md §3.2.1）通りに機能するか検証した結果。

---

## 概要

### 背景

O.6ではモジュール間連動の「基盤部分」（認証/セッション管理、レート制御、経路最適化）を修正した。
しかし、MCPツールが**仕様書通りのレスポンスを返すか**は別の問題として残っている。

### 目的

1. 各MCPツールの出力が§3.2.1の仕様スキーマに準拠しているか検証
2. パイプライン連動（search→抽出→claims構築→DB永続化）の動作確認
3. 問題を特定し修正

### 検証対象

| ツール | 検証優先度 | O.6ステータス | 検証結果 |
|--------|------------|---------------|----------|
| `create_task` | 低 | - | ✅ 検証済 |
| `get_status` | 高 | - | ✅ 修正完了 |
| `search` | 最高 | - | ✅ 修正完了 |
| `stop_task` | 中 | - | ✅ 検証済 |
| `get_materials` | 高 | - | ✅ 修正完了 |
| `calibrate` | 中 | - | ✅ 検証済 |
| `calibrate_rollback` | 低 | - | ⏳ 未検証（同一実装） |
| `get_auth_queue` | - | ✅ O.6検証済 | - |
| `resolve_auth` | - | ✅ O.6検証済 | - |
| `notify_user` | 低 | - | ✅ 検証済 |
| `wait_for_user` | 低 | - | ✅ スキーマ検証済 |

---

## 問題1: searchパイプラインの連動不備 ✅ 修正完了

**検証日**: 2025-12-15  
**検証スクリプト**: `tests/scripts/debug_search_pipeline_flow.py`

### 発見された問題

1. **ExplorationState lacks original_query** - `executor.py:475`で`self.state.original_query`を参照しているが、`ExplorationState`クラスにこの属性がない → AttributeError発生
2. **claims are not persisted to DB** - `_fetch_and_extract()`でclaimsをメモリに保持するが、`claims`テーブルへのINSERTがない
3. **fragments are not persisted to DB** - 同様に`fragments`テーブルへのINSERTがない
4. **edges are not persisted to DB** - claims↔fragmentsの関連付けが永続化されていない
5. **record_claim() only updates counter** - DB書き込みなしでカウンタ更新のみ

### 影響範囲

**影響箇所**:
- `src/mcp/server.py:810-871` - `_handle_search()`
- `src/research/pipeline.py:440-472` - `search_action()`
- `src/research/pipeline.py:126-188` - `SearchPipeline.execute()`
- `src/research/executor.py:135-256` - `SearchExecutor.execute()`
- `src/research/executor.py:433-499` - `_extract_claims_from_text()`
- `src/research/state.py:255-286` - `ExplorationState.__init__()`

### 仕様要件（§3.2.1）

`search`ツールの出力スキーマ:
```json
{
  "ok": true,
  "search_id": "s_001",
  "query": "検索クエリ",
  "status": "satisfied|partial|exhausted",
  "pages_fetched": 15,
  "useful_fragments": 8,
  "harvest_rate": 0.53,
  "claims_found": [
    {
      "id": "c_001",
      "text": "主張テキスト",
      "confidence": 0.85,
      "source_url": "https://...",
      "is_primary_source": true
    }
  ],
  "satisfaction_score": 0.85,
  "novelty_score": 0.42,
  "budget_remaining": {"pages": 45, "percent": 37}
}
```

### 現状の実装

```python
# src/research/pipeline.py:221-233
# claims_foundへの変換
for claim in exec_result.new_claims:
    result.claims_found.append({
        "id": f"c_{uuid.uuid4().hex[:8]}",
        "text": claim.get("claim", claim.get("snippet", ""))[:200],
        "confidence": claim.get("confidence", 0.5),
        "source_url": claim.get("source_url", ""),
        "is_primary_source": self._is_primary_source(claim.get("source_url", "")),
    })
```

### 懸念点

1. **LLM抽出が一次資料のみ**: `_extract_claims_from_text()`は`is_primary=True`の場合のみLLM抽出を実行
2. **二次資料はsnippetのみ**: 二次資料の場合、`claim`フィールドがなく`snippet`のみが返される
3. **DB永続化の欠如**: `state.record_claim()`はカウンタ更新のみで、`claims`テーブルへの書き込みがない可能性

### 検証スクリプト

`tests/scripts/debug_search_pipeline_flow.py`

### 修正内容

**修正日**: 2025-12-15

1. **ExplorationState.original_query追加** (`src/research/state.py`)
   - `__init__`に`original_query`属性を追加
   - `load_state()`でDBからクエリを読み込み

2. **DB永続化メソッド追加** (`src/research/executor.py`)
   - `_persist_fragment()`: fragmentsテーブルへの書き込み
   - `_persist_claim()`: claimsテーブルへの書き込み + edgesテーブルへの関連付け
   - `_fetch_and_extract()`から上記メソッドを呼び出し

### 修正ステータス

✅ 修正完了・テスト通過（57 tests passed in 1.11s）

---

## 問題2: get_statusのメトリクス計算 ✅ 修正完了

### 影響範囲

**影響箇所**:
- `src/mcp/server.py:523-659` - `_handle_get_status()`
- `src/research/state.py` - `ExplorationState.get_status()`
- `src/research/state.py:57-180` - `SearchState`

### 仕様要件（§3.2.1）

`get_status`ツールの出力スキーマ:
```json
{
  "ok": true,
  "task_id": "task_abc123",
  "status": "exploring|paused|completed|failed",
  "query": "元の問い",
  "searches": [
    {
      "id": "s_001",
      "query": "検索クエリ",
      "status": "satisfied|partial|exhausted|running",
      "pages_fetched": 15,
      "useful_fragments": 8,
      "harvest_rate": 0.53,
      "satisfaction_score": 0.85,
      "has_primary_source": true
    }
  ],
  "metrics": {
    "total_searches": 5,
    "satisfied_count": 3,
    "total_pages": 78,
    "total_fragments": 124,
    "total_claims": 15,
    "elapsed_seconds": 480
  },
  "budget": {
    "budget_pages_used": 78,
    "budget_pages_limit": 120,
    "time_used_seconds": 480,
    "time_limit_seconds": 1200,
    "remaining_percent": 35
  },
  "auth_queue": {
    "pending_count": 2,
    "domains": ["protected.go.jp"]
  },
  "warnings": ["予算残り35%", "認証待ち2件"]
}
```

### 現状の実装

```python
# src/mcp/server.py:571-584
# subqueries → searches のマッピング
searches = []
for sq in exploration_status.get("subqueries", []):
    searches.append({
        "id": sq.get("id"),
        "query": sq.get("text"),
        "status": sq.get("status"),
        "pages_fetched": sq.get("pages_fetched", 0),
        "useful_fragments": sq.get("useful_fragments", 0),
        "harvest_rate": sq.get("harvest_rate", 0.0),
        "satisfaction_score": sq.get("satisfaction_score", 0.0),
        "has_primary_source": sq.get("has_primary_source", False),
    })
```

### 懸念点

1. **subqueriesキーの使用**: Phase M.3で`subquery`→`search`にリネームしたが、`get_status()`はまだ`subqueries`キーを参照
2. **metrics.total_claimsの計算**: `state.get_status()`がtotal_claimsを正しく計算しているか未確認
3. **satisfied_countの計算**: 各検索の`status`が正しく`satisfied`になるか未確認

### 検証スクリプト

`tests/scripts/debug_get_status_flow.py`

### 発見された問題

**問題**: `_handle_get_status()`が`exploration_status.get("subqueries", [])`を参照していたが、
`ExplorationState.get_status()`は`"searches"`キーを返していた → 空配列が返される

### 修正内容

**修正日**: 2025-12-15

`src/mcp/server.py:574`のキー参照を修正:
```python
# Before
for sq in exploration_status.get("subqueries", []):

# After  
for sq in exploration_status.get("searches", []):
```

### 修正ステータス

✅ 修正完了・テスト通過

---

## 問題3: get_materialsのエビデンスグラフ構築 ✅ 修正完了

### 影響範囲

**影響箇所**:
- `src/mcp/server.py:930-968` - `_handle_get_materials()`
- `src/research/materials.py:18-89` - `get_materials_action()`
- `src/research/materials.py:92-142` - `_collect_claims()`
- `src/research/materials.py:145-173` - `_collect_fragments()`
- `src/research/materials.py:176-239` - `_build_evidence_graph()`

### 仕様要件（§3.2.1）

`get_materials`ツールの出力スキーマ:
```json
{
  "ok": true,
  "task_id": "task_abc123",
  "query": "元の問い",
  "claims": [
    {
      "id": "c_001",
      "text": "主張テキスト",
      "confidence": 0.92,
      "evidence_count": 3,
      "has_refutation": false,
      "sources": [
        {"url": "https://...", "title": "...", "is_primary": true}
      ]
    }
  ],
  "fragments": [
    {
      "id": "f_001",
      "text": "引用可能なテキスト断片",
      "source_url": "https://...",
      "context": "見出し > サブ見出し"
    }
  ],
  "evidence_graph": {
    "nodes": [...],
    "edges": [...]
  },
  "summary": {
    "total_claims": 18,
    "verified_claims": 12,
    "refuted_claims": 2,
    "primary_source_ratio": 0.65
  }
}
```

### 現状の実装

```python
# src/research/materials.py:92-142
async def _collect_claims(db, task_id: str) -> list[dict[str, Any]]:
    rows = await db.fetch_all(
        """
        SELECT c.id, c.claim_text, c.confidence_score, c.source_url,
               COUNT(DISTINCT e.id) as evidence_count,
               MAX(CASE WHEN e.relation = 'refutes' THEN 1 ELSE 0 END) as has_refutation
        FROM claims c
        LEFT JOIN edges e ON e.target_id = c.id AND e.target_type = 'claim'
        WHERE c.task_id = ?
        GROUP BY c.id
        """,
        (task_id,),
    )
```

### 懸念点

1. **claimsテーブルへの書き込みがない**: `SearchExecutor._extract_claims_from_text()`でclaimsを生成するが、DBへの永続化がない可能性
2. **fragmentsテーブルへの書き込みがない**: 同様に`fragments`テーブルへの書き込みがない可能性
3. **edgesテーブルへの書き込みがない**: claims↔fragmentsの関連付けが永続化されていない可能性
4. **空のレスポンス**: 上記が原因で、`claims`/`fragments`/`evidence_graph`が空になる可能性

### 検証スクリプト

`tests/scripts/debug_get_materials_flow.py`

### 発見された問題

1. **_collect_claims SQLエラー**: `c.source_url`カラムが存在しない（`verification_notes`に格納）
2. **_collect_fragments SQLエラー**: `text`→`text_content`、`task_id`カラムが存在しない
3. **_build_evidence_graph SQLエラー**: `fragments WHERE task_id = ?`が失敗

### 修正内容

**修正日**: 2025-12-15

1. `src/research/materials.py:_collect_claims`: verification_notesからsource_url抽出
2. `src/research/materials.py:_collect_fragments`: claims→edges経由でfragments取得
3. `src/research/materials.py:_build_evidence_graph`: fallbackクエリをclaims→edges経由に変更

### 修正ステータス

✅ 修正完了・テスト通過

---

## 問題4: calibrateツールの動作検証 ✅ 検証完了

### 影響範囲

**影響箇所**:
- `src/mcp/server.py:975-997` - `_handle_calibrate()`
- `src/utils/calibration.py` - `calibrate_action()`

### 仕様要件（§3.2.1）

`calibrate`ツールのアクション:
- `add_sample`: サンプル追加
- `get_stats`: 統計取得
- `evaluate`: バッチ評価
- `get_evaluations`: 履歴取得
- `get_diagram_data`: 信頼度-精度曲線用データ

### 検証スクリプト

`tests/scripts/debug_other_tools_flow.py`

### 検証結果

- `get_stats`: ✅ ok=True
- `add_sample`: ⚠ サンプルデータ不足時はok=False（想定動作）
- `get_diagram_data`: ⚠ サンプル不足時はbins=[]（想定動作）
- `notify_user`: ✅ ok=True
- `stop_task`: ✅ ok=True

### 修正ステータス

✅ 検証完了（基本動作確認済み）

---

## DB永続化フローの確認

### 現状のデータフロー

```
SearchExecutor.execute()
  → _fetch_and_extract()
    → extract_content()        // テキスト抽出
    → _extract_claims_from_text()  // LLM抽出（一次資料のみ）
    → state.record_fragment()  // カウンタ更新のみ？
    → state.record_claim()     // カウンタ更新のみ？
    → result.new_claims.append()  // メモリに保持
```

### 期待されるデータフロー

```
SearchExecutor.execute()
  → _fetch_and_extract()
    → extract_content()
    → _extract_claims_from_text()
    → db.insert("fragments", ...)  // ★ DB永続化
    → db.insert("claims", ...)     // ★ DB永続化
    → db.insert("edges", ...)      // ★ DB永続化
    → state.record_fragment()
    → state.record_claim()
    → result.new_claims.append()
```

### 確認項目

1. `fragments`テーブルへの書き込み箇所
2. `claims`テーブルへの書き込み箇所
3. `edges`テーブルへの書き込み箇所
4. 書き込みが行われるタイミング（パイプライン内 or 後処理）

---

## 検証計画

### Phase 1: searchパイプライン（O.7.2）

1. デバッグスクリプト作成: `tests/scripts/debug_search_pipeline_flow.py`
2. 実行・問題特定
3. 修正実装

### Phase 2: get_status（O.7.3）

1. デバッグスクリプト作成: `tests/scripts/debug_get_status_flow.py`
2. 実行・問題特定
3. 修正実装

### Phase 3: get_materials（O.7.4）

1. デバッグスクリプト作成: `tests/scripts/debug_get_materials_flow.py`
2. 実行・問題特定
3. 修正実装

### Phase 4: その他ツール（O.7.5）

1. calibrateの検証
2. notify_user/wait_for_userの検証

### Phase 5: E2E統合検証（O.7.6）

1. N.6ケーススタディ（リラグルチド調査）実施
2. 成功基準の確認

---

## 成功基準

| 基準 | 閾値 | 測定方法 |
|------|------|----------|
| `search`のclaims_found | ≥1件（一次資料から） | デバッグスクリプト |
| `get_status`のmetrics.total_claims | DB値と一致 | デバッグスクリプト |
| `get_materials`のclaims | ≥1件 | デバッグスクリプト |
| `get_materials`のevidence_graph | nodes≥1, edges≥0 | デバッグスクリプト |
| E2Eケーススタディ | パイプライン完走 | N.6実施 |

---

## 関連ファイル

| ファイル | 役割 |
|----------|------|
| `src/mcp/server.py` | MCPハンドラ |
| `src/research/pipeline.py` | searchパイプライン |
| `src/research/executor.py` | 検索実行 |
| `src/research/state.py` | 探索状態管理 |
| `src/research/materials.py` | 成果物収集 |
| `src/filter/llm.py` | LLM抽出 |
| `src/utils/calibration.py` | 校正機能 |
| `src/storage/schema.sql` | DBスキーマ |
| `src/storage/database.py` | DB接続・マイグレーション |
| `scripts/migrate.py` | マイグレーションランナー |
| `migrations/` | マイグレーションファイル |

---

## 後続フェーズ: O.8 実MCP統合検証

O.7で発見・修正した問題の実環境での検証、およびDBスキーマの改善を実施。

### 追加対応（2025-12-15）

| 問題 | 対処 | ファイル |
|------|------|----------|
| wayback_success_countカラム不存在 | マイグレーションシステム導入 + 001_add_wayback_columns.sql | `scripts/migrate.py`, `migrations/001_*.sql` |
| fragments永続化が失敗 | FetchResultにpage_id追加（FK制約対応） | `src/crawler/fetcher.py` |
| get_statusのsearchesキー不一致 | `subqueries` → `searches` キー修正 | `tests/test_mcp_get_status.py` |

### マイグレーションシステム

スキーマ変更をバージョン管理するため、軽量マイグレーションシステムを導入:

```bash
python scripts/migrate.py up       # 全pending migrations適用
python scripts/migrate.py status   # 適用状況確認
python scripts/migrate.py create NAME  # 新規マイグレーション作成
```

詳細は `docs/IMPLEMENTATION_PLAN.md` の「O.8 実MCP統合検証」セクションを参照。
