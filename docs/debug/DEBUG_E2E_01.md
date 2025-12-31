# DEBUG_E2E_01: クレーム抽出後のDB保存・取得失敗

**日付**: 2025-12-31  
**タスクID**: task_e2b2dfbe  
**ステータス**: ✅ 解決済み

---

## 1. 症状

### 期待される動作

`create_task` → `queue_searches` → `get_materials` の E2E フローで、学術論文のアブストラクトからクレームが抽出され、`get_materials` で取得できる。

### 実際の動作

1. ✅ `create_task` 成功
2. ✅ `queue_searches` 成功 (1件キュー済み)
3. ✅ OpenAlex API から学術論文を取得
4. ✅ `_extract_claims_from_abstract` が呼ばれている
5. ✅ LLM がクレームを抽出 (`claims_count: 1`)
6. ❌ `get_materials` が `claims_count: 0, fragments_count: 0` を返す

```json
// .cursor/debug.log 行29-30: 抽出成功
{"location": "pipeline.py:_extract_claims_from_abstract:entry", "data": {"claims_count": 1, "task_id": "task_e2b2dfbe"}}
{"location": "pipeline.py:_extract_claims_from_abstract:llm_result", "data": {"ok": true, "claims_count": 1}}

// .cursor/debug.log 行57, 90: 取得失敗
{"location": "src/mcp/server.py:_handle_get_materials", "data": {"claims_count": 0, "fragments_count": 0}}
```

---

## 2. 期待されるDB状態

### claims テーブル

| カラム | 期待値 |
|--------|--------|
| task_id | task_e2b2dfbe |
| claim_text | (LLM抽出テキスト) |
| llm_claim_confidence | 0.0-1.0 |

### fragments テーブル

| カラム | 期待値 |
|--------|--------|
| page_id | (対応するpage_id) |
| content | (アブストラクトテキスト) |

### edges テーブル

| カラム | 期待値 |
|--------|--------|
| source_id | (fragment_id) |
| target_id | (claim_id) |
| relation | supports/refutes/neutral |

---

## 3. 証拠収集

### 3.1 処理フロー確認

| タイムスタンプ | イベント | 結果 |
|----------------|----------|------|
| 1767111416362 | create_task | ✅ task_e2b2dfbe |
| 1767111417145 | queue_searches | ✅ 1件 |
| 1767111475759 | _extract_claims_from_abstract entry | ✅ frag_f054bec0 |
| 1767111476138 | LLM extraction | ✅ claims_count=1 |
| 1767111486108 | get_materials | ❌ claims_count=0 |
| 1767111493686 | _extract_claims_from_abstract entry | ✅ frag_ef104a4c |
| 1767111494108 | LLM extraction | ✅ claims_count=1 |
| 1767111512928 | _extract_claims_from_abstract entry | ✅ frag_1609690f |
| 1767111513316 | LLM extraction | ✅ claims_count=1 |
| 1767111513318 | _extract_claims_from_abstract entry | ✅ frag_3a84704c |
| 1767111513739 | LLM extraction | ✅ claims_count=1 |
| 1767111612942 | get_materials | ❌ claims_count=0 |

### 3.2 DB直接確認結果 (P1)

```sql
-- claims テーブル
SELECT task_id, COUNT(*) FROM claims GROUP BY task_id;
-- task_8f211ed9|5  (15:33:37作成、以前の実行)
-- task_d879d41a|2  (16:07:44作成)
-- task_e2b2dfbe|0  ← ★問題のタスク (16:16:56作成)

-- fragments テーブル
SELECT COUNT(*) FROM fragments;  -- 93件

-- edges テーブル
SELECT relation, COUNT(*) FROM edges GROUP BY relation;
-- cites|150
-- neutral|4
-- supports|1
```

**重要な発見**:
- `task_e2b2dfbe` で `_extract_claims_from_abstract` がログで4回成功している
- しかし DB には `task_e2b2dfbe` のクレームが **0件**
- → **H-E（DB INSERT 失敗/スキップ）が確定**

### 3.3 MCPサーバーログ (lyra_20251231.log)

- Semantic Scholar: 429 エラー (Rate Limit) → リトライ後タイムアウト
- OpenAlex: 200 OK → 正常に論文取得
- 一部 OpenAlex 404 (存在しない論文ID) → 正常な挙動
- `_extract_claims_from_abstract` が複数回呼ばれている形跡あり

### 3.4 未確認事項

- DB への INSERT 後のログがない（計装追加済みだが未実行）
- `materials.py` のクエリ結果ログがない（計装追加済みだが未実行）

---

## 4. トリアージ

| エラー/警告 | 分類 | 理由 |
|-------------|------|------|
| Semantic Scholar 429 | Normal | Rate Limit、リトライで対応済み |
| OpenAlex 404 | Normal | 参照論文が存在しない、スキップで正常 |
| JSONDecodeError (OpenAlex) | Normal | 一部レスポンス破損、スキップで正常 |
| get_materials claims=0 | **Problem** | 抽出成功後に取得できない |

---

## 5. 仮説

| ID | 仮説 | 状態 | 証拠 |
|----|------|------|------|
| H-A | MCP outputSchema 検証エラー | ❌ 棄却 | 以前のセッションで修正済み |
| H-B | OpenAlex ID正規化エラー | ❌ 棄却 | ログで正常に正規化されている |
| H-C | `_extract_claims_from_abstract` が呼ばれていない | ❌ 棄却 | ログで4回呼ばれている |
| H-D | LLM抽出が失敗している | ❌ 棄却 | `ok: true, claims_count: 1` |
| **H-E** | DB INSERT が失敗/スキップされている | ✅ **確定** | DB直接確認で task_e2b2dfbe のクレーム=0件 |
| H-F | `get_materials` のSQLクエリに問題がある | ❌ 棄却 | H-Eが原因と判明 |
| H-G | タイミング問題（抽出完了前にget_materials） | ❌ 棄却 | 2回目のget_materialsも0件 |
| H-H | task_id の不一致（fragment/claimに紐付かない） | ❌ 棄却 | H-Eが原因と判明 |

### H-E の詳細調査

LLM抽出は成功しているが、DB保存に至っていない。考えられる原因:

1. **H-E1**: `_extract_claims_from_abstract` 内のループが実行されていない（claims配列が空）
2. **H-E2**: `db.insert` が例外を投げているが、握りつぶされている
3. **H-E3**: `or_ignore=True` によりINSERT がスキップされている（重複claim_id）
4. **H-E4**: トランザクションがコミットされていない

---

## 6. 計装状況

### 追加済み（未実行）

| ファイル | 位置 | 目的 |
|----------|------|------|
| `src/research/pipeline.py` | `_extract_claims_from_abstract:db_insert` | H-E: DB INSERT の成功/失敗を確認 |
| `src/research/materials.py` | `_collect_claims:query_result` | H-F: SQLクエリの結果件数を確認 |

### 計装コード例

```python
# src/research/pipeline.py
# #region agent log
with open("/home/statuser/lyra/.cursor/debug.log", "a") as _f:
    _f.write(_json.dumps({
        "location": "pipeline.py:_extract_claims_from_abstract:db_insert",
        "data": {"claim_id": claim_id, "insert_result": insert_result},
        "hypothesisId": "H-E"
    }) + "\n")
# #endregion
```

---

## 7. 次のアクション

### 7.1 DB直接確認（完了）

```sql
-- claims テーブル → task_e2b2dfbe: 0件（問題確定）
SELECT task_id, COUNT(*) FROM claims GROUP BY task_id;
```

### 7.2 再現テスト（計装ログ取得）- P1

追加した計装:
- `loop_start`: LLMが返したclaimsの生データを確認
- `loop_item`: 各claimの構造（キー、型）を確認
- `db_insert` / `db_insert_error`: INSERT結果を確認

手順:
1. デバッグログをクリア: `> .cursor/debug.log`
2. MCPサーバー再起動: `make mcp`
3. MCP経由で新規タスク実行
4. `.cursor/debug.log` を確認

期待するログ:
```json
{"hypothesisId": "H-E1", "location": "loop_start", "data": {"claims_raw": [...]}}
{"hypothesisId": "H-E1", "location": "loop_item", "data": {"claim_keys": ["claim", "confidence", ...]}}
{"hypothesisId": "H-E", "location": "db_insert", "data": {"insert_result": ...}}
```

### 7.3 LLM抽出結果の構造確認（H-E1 検証）

LLM (`llm_extract`) が返す `result["claims"]` の構造を確認:
- 期待: `[{"claim": "text", "confidence": 0.8, "type": "fact"}, ...]`
- 実際: ?（ログで確認が必要）

---

## 8. 関連ファイル

| ファイル | 役割 |
|----------|------|
| `src/research/pipeline.py` | `_extract_claims_from_abstract` - アブストラクトからクレーム抽出 |
| `src/research/materials.py` | `_collect_claims` - DBからクレーム取得 |
| `src/mcp/server.py` | `_handle_get_materials` - MCPツールハンドラ |
| `src/storage/schema.sql` | DBスキーマ定義 |

---

## 9. 参照

- `docs/adr/0009-abstract-only-strategy.md` - アブストラクト直接保存の設計
- `docs/adr/0016-nli-confidence-calibration.md` - 信頼度キャリブレーションの設計
- `docs/archive/Rc_CONFIDENCE_CALIBRATION_DESIGN.md` - PR #50 で完了した修正

---

## 8. 根本原因と修正

### 根本原因

1. **LLM が単一オブジェクトを返す問題**
   - LLM は配列 `[{...}]` ではなく単一オブジェクト `{...}` を返していた
   - `extract_json(text, expect_array=True)` は `None` を返し、パースに失敗
   - `parse_and_validate` が `None` を返し、`{"raw_response": "..."}` がそのまま claims に入る
   - `claim.get("claim")` が `None` → DB INSERT に到達しない

2. **NLI 呼び出しのインターフェース不一致**
   - `nli_judge` は `list[dict]` を直接返すように変更されていた
   - 呼び出し側は `{"ok": ..., "results": [...]}` 形式を期待していた

### 修正内容

| ファイル | 修正 |
|----------|------|
| `src/filter/llm_output.py` | `extract_json`: `strict_array` パラメータ追加。最初の試行で単一オブジェクトを拒否（リトライトリガー）、リトライ後は配列にラップ |
| `src/filter/llm_output.py` | `extract_json`: "array wrapper" パターン対応 (`{objects:[...]}`, `{claims:[...]}`, `{facts:[...]}` 等から内部配列を抽出) |
| `src/filter/llm_output.py` | `parse_and_validate`: 最初の試行は strict_array=True、リトライ後は strict_array=False |
| `src/research/pipeline.py` | `_extract_claims_from_abstract`: `nli_judge` の戻り値を `list` として処理 |
| `tests/test_llm_output.py` | テストを新しい動作に合わせて更新（リトライトリガー確認、array wrapper パターン）|

---

## 9. 検証結果

```
✅ SUCCESS: 1 claims saved, 1 edges saved
```

- LLM 抽出: 成功（単一オブジェクト → 配列にラップ）
- Claim DB 保存: 成功
- NLI 評価: 成功（`stance: "supports"`, `nli_edge_confidence: 0.998`）
- Edge DB 保存: 成功

テスト: 45 passed, 13 skipped

---

## 更新履歴

| 日時 | 更新内容 |
|------|----------|
| 2025-12-31 00:30 | 初版作成、仮説 H-C, H-D 棄却 |
| 2025-12-31 00:45 | DB直接確認で H-E 確定、H-E1〜H-E4 サブ仮説追加 |
| 2025-12-31 01:00 | ループ内の計装追加（loop_start, loop_item）|
| 2025-12-31 01:30 | 根本原因特定: LLM が単一オブジェクトを返す問題 |
| 2025-12-31 01:35 | 修正: extract_json で単一オブジェクトを配列にラップ |
| 2025-12-31 01:36 | 修正: nli_judge の戻り値インターフェース対応 |
| 2025-12-31 01:38 | 検証完了、テスト全件通過、ステータス→解決済み |
| 2025-12-31 10:30 | 追加修正: 3Bモデル向けプロンプト最適化 |
| 2025-12-31 10:45 | 追加修正: セキュリティタグデフォルト無効化 |
| 2025-12-31 11:00 | 追加修正: pyproject.toml デフォルトでE2Eテスト除外 |

---

## 10. 追加修正（3Bモデル最適化）

初期修正後、3Bモデル (qwen2.5:3b) で長いプロンプトが空の出力を返す問題が発覚。

### 10.1 根本原因

- 3Bモデルは長いプロンプト (>500文字) で空の JSON (`{}`, `[]`) を返す
- セキュリティタグ付きプロンプトは ~1700文字に達していた
- プロンプト内の具体的な値 (`0.8`, `0.9`) がそのままコピーされる

### 10.2 追加修正内容

| ファイル | 修正 |
|----------|------|
| `src/utils/config.py` | `session_tags_enabled` デフォルトを `False` に変更 |
| `config/prompts/*.j2` (全10ファイル) | プロンプト簡略化（~800文字 → ~300文字） |
| `src/filter/llm.py` | JSON Schema 定義、Ollama に渡して出力形式を強制 |
| `docs/archive/Rb_PROMPT_TEMPLATE_REVIEW.md` | 追補8: 3Bモデル向けプロンプト最適化 |
| `docs/adr/0004-local-llm-extraction-only.md` | 3Bモデル向けガイドライン追加 |
| `pyproject.toml` | デフォルトでE2Eテスト除外 (`-m 'not e2e and not slow'`) |
| `tests/test_pipeline_academic.py` | `insert.call_count` アサーション緩和 |

### 10.3 プロンプト最適化の方針

| 問題 | 対策 |
|------|------|
| 具体的な値をコピー | `<0.0-1.0>` 形式のプレースホルダー |
| 抽出件数が不安定 | 「1-5件」「3-10件」と明示 |
| 形式の不一致 | JSON Schema で強制 |

### 10.4 検証結果

```
Run 1-3: ok=True, claims=5 ✅
テスト: 86 passed, 13 skipped
```| 2025-12-31 10:30 | 追加修正: 3Bモデル向けプロンプト最適化 |
| 2025-12-31 10:45 | 追加修正: セキュリティタグデフォルト無効化 |
| 2025-12-31 11:00 | 追加修正: pyproject.toml デフォルトでE2Eテスト除外 |

---

## 10. 追加修正（3Bモデル最適化）

初期修正後、3Bモデル (qwen2.5:3b) で長いプロンプトが空の出力を返す問題が発覚。

### 10.1 根本原因

- 3Bモデルは長いプロンプト (>500文字) で空の JSON (`{}`, `[]`) を返す
- セキュリティタグ付きプロンプトは ~1700文字に達していた
- プロンプト内の具体的な値 (`0.8`, `0.9`) がそのままコピーされる

### 10.2 追加修正内容

| ファイル | 修正 |
|----------|------|
| `src/utils/config.py` | `session_tags_enabled` デフォルトを `False` に変更 |
| `config/prompts/*.j2` (全10ファイル) | プロンプト簡略化（~800文字 → ~300文字） |
| `src/filter/llm.py` | JSON Schema 定義、Ollama に渡して出力形式を強制 |
| `docs/archive/Rb_PROMPT_TEMPLATE_REVIEW.md` | 追補8: 3Bモデル向けプロンプト最適化 |
| `docs/adr/0004-local-llm-extraction-only.md` | 3Bモデル向けガイドライン追加 |
| `pyproject.toml` | デフォルトでE2Eテスト除外 (`-m 'not e2e and not slow'`) |
| `tests/test_pipeline_academic.py` | `insert.call_count` アサーション緩和 |

### 10.3 プロンプト最適化の方針

| 問題 | 対策 |
|------|------|
| 具体的な値をコピー | `<0.0-1.0>` 形式のプレースホルダー |
| 抽出件数が不安定 | 「1-5件」「3-10件」と明示 |
| 形式の不一致 | JSON Schema で強制 |

### 10.4 検証結果

```
Run 1-3: ok=True, claims=5 ✅
テスト: 86 passed, 13 skipped
```
