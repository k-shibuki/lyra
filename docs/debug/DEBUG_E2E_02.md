# DEBUG_E2E_02: E2Eパイプライン総合検証

**日付**: 2025-12-31  
**タスクID**: task_e0f05ce7  
**ステータス**: ✅ 完了（DEBUG_E2E_01の修正が正常動作、追加問題なし）

---

## 1. セッション概要

DEBUG_E2E_01で修正したクレーム抽出パイプラインの動作確認と、E2Eフロー全体の健全性検証を実施。

### 参照ADR

- ADR-0002: Thinking-Working Separation
- ADR-0005: Evidence Graph Structure
- ADR-0009: Test Layer Strategy

---

## 2. 検証結果サマリー

| 検証項目 | 結果 | 詳細 |
|----------|------|------|
| クレーム抽出 | ✅ | 35件正常抽出 |
| NLI評価 | ✅ | 35件すべて評価済み |
| DB保存 | ✅ | 整合性OK |
| MCPサーバーログ | ✅ | エラー0件 |
| Evidence Graph | ✅ | 構造正常 |
| タスクライフサイクル | ✅ | 正常完了 |
| 自動テスト | ✅ | 3645 passed（7件修正済み） |

---

## 3. 詳細検証

### 3.1 MCPサーバーログ分析

```
logs/lyra_20251231.log (276行)
```

| レベル | 件数 | 分類 |
|--------|------|------|
| ERROR | 0件 | - |
| WARNING | 5件 | すべて Normal |

#### WARNING の内訳

| イベント | 件数 | 分類 | 理由 |
|----------|------|------|------|
| OpenAlex 404 | 2件 | Normal | 参照論文が存在しない |
| Non-retryable HTTP status | 2件 | Normal | 404のリトライ不要判定 |
| Pipeline timeout | 1件 | Normal | 180秒タイムアウト（設計通り） |

---

### 3.2 DB整合性チェック（ADR-0005準拠）

```sql
-- チェック結果
```

| チェック項目 | 結果 | 備考 |
|-------------|------|------|
| Orphan claims | 2件 | `task_d879d41a`（DEBUG_E2E_01以前の問題） |
| Orphan edges (fragment) | 0件 | ✅ |
| Orphan edges (claim) | 0件 | ✅ |
| Orphan fragments | 0件 | ✅ |
| Task scoping | 35/35 | ✅ claims/edges 一致 |
| Stuck jobs | 1件 | `s_06389bf7cd4b`（過去のrunning状態） |

**今回のタスク `task_e0f05ce7` に問題なし。**

---

### 3.3 Evidence Graph構造（ADR-0005準拠）

```sql
-- task_e0f05ce7 のグラフ統計
```

| 指標 | 値 |
|------|-----|
| Claims | 35 |
| Edges (neutral) | 35 |
| Unique fragments | 7 |
| Edge-Claim ratio | 1:1 ✅ |

#### NLI Confidence分布

| 帯域 | 件数 | 割合 |
|------|------|------|
| High (>=0.7) | 34 | 97% |
| Medium (0.3-0.7) | 1 | 3% |
| Low (<0.3) | 0 | 0% |

**観察**: すべてのエッジが `neutral` と判定。アブストラクトから直接抽出したクレームなので、NLIモデルが「中立」と判定するのは妥当。

---

### 3.4 タスクライフサイクル（ADR-0002準拠）

```
create_task → queue_searches → get_status → get_materials → stop_task
```

| ステップ | 状態 |
|----------|------|
| Task | status = `completed` ✅ |
| Job | state = `completed` ✅ |
| Intervention Queue | 0件（認証不要） ✅ |

---

### 3.5 自動テスト（ADR-0009準拠）

```bash
make test  # L1 + L2 テスト
```

| 結果 | 件数 |
|------|------|
| Passed | 3645 |
| Failed | 0 |
| Skipped | 22 |
| 所要時間 | 3分29秒 |

#### 修正したテスト（7件）

| テストファイル | 修正数 | 根本原因 |
|---------------|--------|----------|
| test_prompt_manager.py | 4 | プロンプト簡略化（DEBUG_E2E_01）で期待値不一致 |
| test_calibration_rollback.py | 2 | `call_tool` 戻り値形式変更（dict直接返却） |
| test_mcp_integration.py | 1 | 同上 |

**修正内容**:
- `test_empty_string_input`: "INPUT DATA" → "Extract", "Text:"
- `test_json_format_decompose`: "  {" → '{"text":'
- `test_densify_renders_correctly`: "densify" → "information-dense"
- `test_initial_summary_with_query_context`: "Research question" → "Research context:"
- `test_mcp_error_returns_structured_response`: list[Content] → dict
- `test_unexpected_error_wrapped_as_internal`: list[Content] → dict
- `test_get_materials_call_tool_preserves_bayesian_fields`: list[Content] → dict

---

## 4. 既知の問題（次セッションで分析）

### 4.1 Orphan Claims（2件）

| claim_id | task_id | 原因 |
|----------|---------|------|
| c_3072a88d | task_d879d41a | DEBUG_E2E_01以前のNLI失敗 |
| c_e8201bb8 | task_d879d41a | 同上 |

**次セッション課題**: 
- ADR-0005のHard cleanup（orphans_only）による削除手順の確立
- Orphan発生原因の根本分析（E2Eデバッグ開始前の事象ではあるが、分析する）

### 4.2 Stuck Job（1件）

| job_id | task_id | 状態 | 作成日時 |
|--------|---------|------|----------|
| s_06389bf7cd4b | task_1dbcd8ea | running | 2025-12-30 15:32:32 |

**次セッション課題**:
- キャンセル/中断されたジョブの扱いに関するワークフロー検討
- `running` 状態で放置されたジョブの自動検出・クリーンアップ機構
- タイムアウトによる自動 `failed` 遷移の実装検討

---

## 5. 仮説検証ログ

### DEBUG_E2E_01からの引き継ぎ仮説

| ID | 仮説 | 状態 | 証拠 |
|----|------|------|------|
| H-A | LLMが空配列を返す | ❌ 棄却 | 正しいJSON配列を返している |
| H-B | LLMが空オブジェクトを返す | ❌ 棄却 | 同上 |
| H-C | parse_and_validateが失敗 | ❌ 棄却 | validated_count: 5 |
| H-D | LLMが非JSON形式を返す | ❌ 棄却 | 全レスポンスがJSON配列 |
| H-E | result["claims"]が空 | ❌ 棄却 | ok: true, claims_count: 5 |

### 計装コード

```python
# すべて削除済み
# 1. llm.py:response_text - LLM生出力
# 2. llm.py:provider_parse_result - parse_and_validate結果
# 3. pipeline.py:result - llm_extract最終結果
```

---

## 6. 結論

| 項目 | 判定 |
|------|------|
| DEBUG_E2E_01の修正 | ✅ 正常動作 |
| E2Eパイプライン | ✅ 健全 |
| Evidence Graph | ✅ 構造正常 |
| タスクライフサイクル | ✅ 正常完了 |
| 追加の修正 | 不要 |

**セッション完了。次のステップとして推奨:**
1. Orphan Claims / Stuck Job の根本原因分析と対応ワークフロー策定
2. キャンセル/中断されたジョブの扱いに関するワークフロー検討
3. S_FULL_E2E.mdに基づく本格的なケーススタディ実行

---

## 7. 関連ドキュメント

| ドキュメント | 用途 |
|-------------|------|
| DEBUG_E2E_01 | クレーム抽出→DB保存の修正（解決済み） |
| S_FULL_E2E.md | E2Eケーススタディ設計 |
| ADR-0002 | Thinking-Working Separation |
| ADR-0005 | Evidence Graph Structure |
| ADR-0009 | Test Layer Strategy |

---

## 8. get_materials vs DB直接比較検証

### 8.1 検証目的

MCPツール `get_materials` が返すデータが、DB（SQLite）の実データと整合しているか確認する。
乖離がある場合は `get_materials` のロジックにバグがあるか、DB自体の不整合を示唆する。

### 8.2 検証方法

1. **get_materials呼び出し**: `task_id=task_e0f05ce7`, `include_graph=true`
2. **DB直接クエリ**: sqlite3 で6つのクエリを実行

### 8.3 比較結果

| 項目 | get_materials | DB直接 | 一致 |
|------|--------------|--------|------|
| Claims数 | 35 | 35 | ✅ |
| Edges数 | 35 | 35 | ✅ |
| Fragments数 | 7 | 7 | ✅ |
| NLI relation分布 | neutral: 35 | neutral: 35 | ✅ |
| Avg NLI confidence | ~0.978 | 0.9783 | ✅ |
| Orphan claims | 0 | 0 | ✅ |

### 8.4 詳細検証

#### Claims詳細

DB直接クエリで取得した35件のclaim_idはすべて `get_materials.claims[].id` と完全一致。

| claim_id | llm_claim_confidence | claim_adoption_status |
|----------|---------------------|-----------------------|
| c_03b76615 | 0.8 | adopted |
| c_0846e0ed | 0.85 | adopted |
| ... (全35件) | 0.75 - 0.95 | adopted |

#### Edges詳細

DB直接クエリで取得した35件のedge_idはすべて `get_materials.evidence_graph.edges[].edge_id` と完全一致。

```sql
-- DB直接クエリ結果（一部）
e_125160f2|frag_f855c5ee|c_4028a209|neutral|0.9974
e_1c3d892c|frag_1ba4b3ca|c_e93fbb2b|neutral|0.9849
e_deb23e21|frag_991b6db7|c_9535d527|neutral|0.6181  -- 最低confidence
...
```

#### NLI Confidence分布

| 帯域 | 件数 | 備考 |
|------|------|------|
| High (>=0.9) | 33 | 94% |
| Medium (0.6-0.9) | 2 | 6%（e_deb23e21=0.618, e_f1bae37f=0.894） |
| Low (<0.6) | 0 | 0% |

### 8.5 結論

| 検証項目 | 結果 |
|----------|------|
| get_materials vs DB整合性 | ✅ 完全一致 |
| データ欠損 | なし |
| Edge ID整合 | ✅ 35/35 一致 |
| Confidence値整合 | ✅ 小数点4桁まで一致 |

**get_materials API は DB の実データを正確に反映している。**

---

## 9. 追加分析による課題の特定

### 9.1 別AIによるエビデンスグラフ分析結果

外部AIにエビデンスグラフを分析させた結果、以下の構造的特徴と課題が特定された。

#### グラフ構造

| 項目 | 値 |
|------|-----|
| 総クレーム数 | 35件 |
| ソース論文 | 7本（すべて学術論文、DOI付き） |
| 時間範囲 | 2019年〜2023年 |
| 反駁エビデンス | 0件（has_refutation = false） |

#### 2つのトピッククラスター

- **AI/MLクラスター**: ACM Computing Surveys 2019, Remote Sensing 2020
- **サンゴ/気候クラスター**: IPCC AR6 2023, Science 2020, PLOS Climate 2022, Frontiers Marine 2020, GCB 2021

### 9.2 特定された課題

#### 課題1: ベイズ更新の内部実装

**症状**:
- すべてのクレームで `bayesian_claim_confidence = 0.5`
- supports / refutes エッジが 0件
- すべてのエッジが `neutral` 関係

**問題の本質**:
- ベイズ信頼度0.5は「十分なエビデンスが蓄積されていない状態」を示す
- neutralエッジのみではベイズ更新が実質的に機能しない
- α = 1, β = 1 の初期状態から更新されていない可能性

**調査すべき点**:
1. NLIモデルがneutral以外を出力する条件
2. アブストラクトからの直接抽出でsupports/refutesが出にくい仕様上の問題
3. ベイズ更新の計算ロジック（`EvidenceGraph.calculate_claim_confidence`）

#### 課題2: 引用ネットワークの仕様確定

**症状**:
- `cites` 関係のエッジが0件
- paper_metadataには `citation_count` / `reference_count` はあるが、具体的な引用リストがない

**問題の本質**:
- Semantic Scholar / OpenAlex APIから引用関係を取得する機能が未実装または未使用
- 引用ネットワークなしでは、情報の伝播経路（citation loop）を検出できない
- ADR-0005で言及されている引用関係の活用ができていない

**調査すべき点**:
1. Semantic Scholar API の references/citations エンドポイントの呼び出し有無
2. `citation_source` フィールドの利用状況
3. 引用エッジ生成のトリガー条件

### 9.3 改善の方向性

| 課題 | 短期対応 | 長期対応 |
|------|----------|----------|
| ベイズ更新 | `edge_correct` で手動でsupports/refutesを付与し検証 | NLIモデルのプロンプト/閾値調整、クレーム-フラグメント間の関係性強化 |
| 引用ネットワーク | APIから引用リストを取得するパイプライン追加 | 引用グラフの自動構築、citation loop検出の実装 |

### 9.4 次セッションでの優先タスク

1. **ベイズ更新のデバッグ**: `EvidenceGraph.calculate_claim_confidence` の計算ロジックをトレース
2. **NLIモデルの出力分析**: neutralが支配的な理由を調査（モデルの仕様か、入力の問題か）
3. **引用API呼び出しの確認**: Semantic Scholar/OpenAlexの引用取得機能の実装状況を確認
4. **ADR-0005との照合**: Evidence Graph仕様と現実装のギャップ分析

---

## 更新履歴

| 日時 | 更新内容 |
|------|----------|
| 2025-12-31 11:00 | 初版作成 |
| 2025-12-31 11:10 | 計装追加、E2Eテスト実行 |
| 2025-12-31 11:15 | ログ分析完了、すべての仮説棄却 |
| 2025-12-31 11:20 | DB状態確認、計装削除 |
| 2025-12-31 11:30 | MCPサーバーログ分析追加 |
| 2025-12-31 11:40 | DB整合性チェック、Evidence Graph構造確認 |
| 2025-12-31 11:50 | タスクライフサイクル確認、自動テスト実行 |
| 2025-12-31 12:00 | セッション完了、ドキュメント最終化 |
| 2025-12-31 12:15 | テスト7件修正、全テスト Pass |
| 2025-12-31 12:20 | 次セッション課題を明確化 |
| 2025-12-31 14:30 | get_materials vs DB直接比較検証を追加 |
| 2025-12-31 15:00 | 別AIによるエビデンスグラフ分析結果を追加 |
| 2025-12-31 15:00 | 課題特定: ベイズ更新の内部実装、引用ネットワークの仕様確定 |
