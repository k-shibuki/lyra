## Evidence System: 現状ステータス（コードベース突合レビュー）

作成日: 2025-12-24  
対象ドキュメント（参考・アーカイブ）: `docs/archive/P_EVIDENCE_SYSTEM.md`  

本ドキュメントは、上記アーカイブが主張する「Phase 1〜6 DONE」を、**現行コードベースと突合して評価**した結果をまとめたもの。  
アーカイブは「当時のスナップショット」であり、現行実装の事実は **コードとMCP契約（スキーマ/L7サニタイズ）** を正とする。

---

### 結論（レビュー判断）

`docs/archive/P_EVIDENCE_SYSTEM.md` の内容は、**"内部実装が存在する"という意味では多くが実装済み**に見える一方で、  
**"MCP経由で外部に露出し、仕様どおりに成立する"という意味では未完了の箇所がある**ため、現状は **「完全に完了した」とは言えない**。

当初 未完了と判断した主因は次の2点:

- ~~**L7サニタイズ（スキーマallowlist）と `get_materials` の実返却の不整合**~~ → ✅ 解消済み（2025-12-24）
- **EvidenceGraph の統計（独立ソース数・時間メタデータ）が実運用パスで成立していない疑い** → 未着手

---

### 確認できた「実装済み」要素（根拠ファイル）

- **Phase 6: `feedback` ツール（6 actions）**
  - 実装: `src/mcp/server.py`（ツール登録と `_handle_feedback`）
  - ルーティング/DB永続化/即時反映: `src/mcp/feedback_handler.py`
  - レスポンススキーマ: `src/mcp/schemas/feedback.json`

- **Phase 6: DBスキーマ棚卸し（少なくとも該当テーブル/カラムが存在）**
  - `nli_corrections`, `domain_override_rules`, `domain_override_events` の定義: `src/storage/schema.sql`
  - `claims.claim_adoption_status` / `claim_rejection_reason` / `claim_rejected_at` の定義: `src/storage/schema.sql`

- **Phase 4/4b 相当: ベイズ統計（confidence/uncertainty/controversy）と時間メタデータの生成**
  - ベイズ更新 + `evidence` / `evidence_years` を返す実装: `src/filter/evidence_graph.py:EvidenceGraph.calculate_claim_confidence`
  - `get_materials_action()` がそれらを claims に詰める実装: `src/research/materials.py`

- **旧フィールド/旧概念の残骸掃除（少なくとも `src/`・`tests/` での grep 上は 0 件）**
  - 確認対象: `trust_level`, `is_influential`, `is_contradiction`, `can_restore`, `rejected_claims`, `rejection_rate`

---

### 解消済み

#### 1) `get_materials` の実装と MCP契約（スキーマ/L7）不整合 → ✅ 解消（2025-12-24）

**修正内容**:
- `src/mcp/schemas/get_materials.json` を修正し、`uncertainty/controversy/evidence/evidence_years` を allowlist に追加
- L7後もフィールドが保持されることをテストで固定化
  - `tests/test_mcp_integration.py::test_get_materials_call_tool_preserves_bayesian_fields`
  - `tests/test_mcp_integration.py::test_get_materials_l7_strips_unknown_claim_fields_but_keeps_allowed`
- 契約ドキュメント追加: `docs/sequences/get_materials_l7_contract.md`

---

### 未完了/不整合（重要）

#### 2) EvidenceGraph の「独立ソース数/時間メタデータ」が実運用で成立しない疑い

**現象（疑い）**:
`EvidenceGraph.calculate_claim_confidence()` の `independent_sources` は **PAGEノード**を根拠に数えるが、  
通常の検索実行パスは **FRAGMENT→CLAIM** の NLI エッジを作るため、PAGEノードが十分に関与しない場合、
`independent_sources` が 0 のままになり得る。

**根拠**:
- NLIエッジ永続化の実運用: `src/research/executor.py` が `add_claim_evidence()`（FRAGMENT→CLAIM）を実行
- 独立ソース数の計算が PAGE ノード依存: `src/filter/evidence_graph.py:calculate_claim_confidence`

**影響**:
`SourceVerifier` は `independent_sources >= 2` を VERIFIED（昇格含む）の条件に使うため、
実運用で `independent_sources` が期待どおりに増えない場合、検証フローが想定どおり動かない可能性がある。

---

### テスト/検証に関する注意点（今回のレビューで見えたこと）

- `tests/test_mcp_integration.py` は主に `get_materials_action()` を直接呼ぶテストがあり、  
  **MCPの最終出力（L7サニタイズ後）を検証しているわけではない**ケースがある。
- E2Eスクリプト `tests/scripts/verify_mcp_integration.py` は `_dispatch_tool` を使うが、  
  それも `call_tool()` の L7 サニタイズ経路とは異なる（= 最終応答の契約検証としては弱くなり得る）。

---

### 次セッション（/integration-design でのデバッグ前提）

次のセッションでは、`/integration-design` の手順に沿って、特に以下を "契約/伝播" 観点で確定させるのがよい:

- ~~**`get_materials` の契約確定**~~ → ✅ 解消済み（2025-12-24）
  - ~~`src/mcp/schemas/get_materials.json` と `src/research/materials.py` の整合~~
  - ~~L7サニタイズ後に `uncertainty/controversy/evidence/evidence_years` が残ることのE2E確認~~

- **独立ソース数の定義と wiring**（未着手）
  - FRAGMENT→CLAIM を前提に「independent_sources をどう数えるか」を決める
  - `EvidenceGraph.calculate_claim_confidence()` の実運用データから値が増えることを確認

---

### 参考（レビューで直接参照した主な実装）

- `src/mcp/server.py`
- `src/mcp/response_sanitizer.py`
- `src/mcp/schemas/get_materials.json`
- `src/research/materials.py`
- `src/filter/evidence_graph.py`
- `src/research/executor.py`
- `src/filter/source_verification.py`
- `src/storage/schema.sql`
- `docs/sequences/get_materials_l7_contract.md`（2025-12-24 追加: L7契約のシーケンス図/伝播マップ）
- `tests/test_mcp_integration.py`（L7後のフィールド保持テスト）


