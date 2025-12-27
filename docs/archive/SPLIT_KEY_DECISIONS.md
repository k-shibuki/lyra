## Split keys: 意味確定（ADR/MCP整合）と正規化確定（破壊的移行前提）

この文書は「**split（同名キーが複数意味を持つ）**」を先に解決するための決定台帳である。
機械置換（rg一撃）は、この決定が揃ってから実行する。

参照（機械台帳）:
- `docs/archive/parameter-registry.tier1-review-decisions.json`
- `docs/archive/RG_SAFE_REPLACEMENT_GUIDE.md`

### 0. 原則（必須）

- **同名キーは“意味が一意でない限り”禁止**（例: `confidence` / `type` / `status`）
- splitキーは、必ず **producer/object を明示**した名前へ分解する
- JSON Schema の `type` は外部仕様なので **絶対に触らない**

---

## 1) `confidence`（最優先の split）

### 1.1 現状（確定した事実）

#### DB（Evidence Graph）
- `edges.nli_confidence`: NLIモデルが出した evidence weight（supports/refutes の強さ）
- `edges.confidence`: **compatibility alias + 用途混在**
  - Fragment→Claim の evidence edge では、`edges.confidence == edges.nli_confidence`
    - 根拠: `src/research/executor.py` が `confidence=nli_conf` と明示して保存
  - CITES (Page→Page) では、`edges.confidence = 1.0` で `nli_confidence` は NULL
    - 根拠: `src/filter/evidence_graph.py:add_citation`

#### MCP（get_materials）
- `claims[].confidence` は「claimの集約信頼度」として使われているが、内部では
  - Bayes算出結果（`calculate_claim_confidence`）または
  - DB `claims.claim_confidence`（LLM自己評価）へのフォールバック
  という **混在**がある（= split対象）。

### 1.2 正規化（確定）

#### (A) Evidence edge（Fragment→Claim）
- **出すべき canonical**
  - `nli_edge_confidence_raw`（未校正の生スコア）
  - `nli_edge_label`（supports/refutes/neutral）
- **禁止**
  - エッジ上の generic `confidence`
  - `edges.confidence` の露出（aliasのまま出すと意味が混線する）

#### (B) Citation edge（Page→Page）
- **出すべき canonical**
  - `relation="cites"` と `citation_source`/`citation_context`（必要なら）
- **禁止**
  - `confidence=1.0` のような “重みっぽいが意味のない数値” の露出

#### (C) Claim（get_materials claims[]）
- **分解して出す（必須）**
  - `bayes_claim_confidence`（Beta更新の posterior mean）
  - `llm_claim_confidence_raw`（DB由来のLLM自己評価）
  - `claim_confidence_source`（`bayes | llm_fallback`）
- **禁止**
  - `claims[].confidence`（汎用語）

---

## 2) `type`（2番目の split）

### 2.1 現状（確定した事実）

- JSON Schema（MCP schema）では `type` は仕様キーワード
- 一方、プロダクト内でも `type` は
  - graph node type（claim/fragment）
  - LLM出力の claim type（factual/causal/...）
  - SecurityWarning.type（dangerous_pattern/...）
 などに使われ、意味が分岐している

### 2.2 正規化（確定）

- **JSON Schema の `type`**: keep（外部仕様）
- **graph node type**: `node_type` に統一（`type` 禁止）
- **claim decomposition（decompose promptの `type`）**
  - `meta_claim_label_type` に改名（`type` 禁止）
- **prompt extract_claims の `type`**
  - `llm_claim_type` に改名（`type` 禁止）

---

## 3) `status`（3番目の split）

### 3.1 現状（確定した事実）

- `status` は task/search/job/provider など複数オブジェクトに跨る
- MCP `get_status` は top-level `status` と nested `searches[].status` / `queue.items[].status` があり、同名で意味が分岐する

### 3.2 正規化（確定）

MCP `get_status` は、同名 `status` を object別に分解する:
- `meta_task_status`
- `meta_search_status`（`searches[]`）
- `meta_search_queue_item_status`（`queue.items[]`）

provider（LLMResponseなど）の `status` は:
- `llm_response_status`

（補足）DB側は `tasks.status`, `jobs.state`, `engine_health.status` 等があり、全項目正規化フェーズで object別に統一する。

