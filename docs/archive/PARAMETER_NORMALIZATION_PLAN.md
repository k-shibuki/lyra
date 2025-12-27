## Parameter Normalization Plan (Destructive / DB Rebuild)

**Date**: 2025-12-27  
**Scope**: DB schema, MCP tool schemas/responses, source code, tests, prompt templates (`config/prompts/*.j2`)  
**Out of scope**: Backward compatibility (explicitly *not required*)  

### 1. 結論（今すぐ実行すべきか？）

**おすすめは「今すぐ実装に着手」ではなく、まずこの計画書を“変更リストとして確定”してから着手**です。  
理由は、Lyra は **L7: MCPレスポンスをJSON Schemaでallowlist化**しており、命名変更は「コードだけ直す」では済まず、**MCP schema・テスト・ドキュメントも連鎖的に壊れる**ためです。

ただし、**破壊的変更・DB作り直しを許容できるなら、早期に一気に揃える価値は高い**です（命名負債が増える前に止血できる）。

### 2. 正規名（canonical）命名規則

**目的**: “どのモデルの、どの対象の、どの指標か” が機械的に識別できること。

#### 2.1 Canonical key format

`<producer>_<object>_<metric>[_<qualifier>]`

- **producer**（生成元）: `rank | llm | nli | bayes | calib | meta | policy | crawl | search`
- **object**（対象）: `fragment | claim | fact | edge | page | citation | domain | engine | task | job`
- **metric**（指標）: `text | keywords | hints | score | confidence | prob | logit | label | weight | uncertainty | controversy | count | ratio | status`
- **qualifier**（任意）: `raw | calibrated | bm25 | embed | rerank | final | category | before | after | expected | predicted`

例:
- `llm_claim_confidence_raw`
- `nli_edge_confidence_raw`
- `bayes_claim_confidence`
- `rank_fragment_score_bm25`
- `rank_fragment_score_final`

#### 2.2 例外ルール（最小）

- **ID/URL等の識別子**: `*_id`, `*_url` は既存慣習に合わせる（例: `task_id`, `page_id`）。
- **enum的フィールド**: `*_label`, `*_status`, `*_category` を優先。

### 3. 変更の中心方針

1. **DB: schemaを作り直し**（列名・テーブル名の全面正規化）
2. **MCP: tool schema を正規名に合わせる**（L7 allowlistのため必須）
3. **コード/テスト: 正規名へ一括置換**（旧名は残さない）
4. **最後に grepで漏れゼロを検証**

### 4. 完全な変更リスト（初版）

> NOTE: この表は「モデル系スコア/確信度/重み」をまず確実に正規化する最小核（High ROI）。
> 文字通り “全パラメータ” をやる場合は、5章の手順で自動抽出して表を拡張する。

#### 4.1 DB（`src/storage/schema.sql`）: rename map

| 現状 | 新（提案） | 意味 |
|---|---|---|
| `claims.claim_confidence` | `claims.llm_claim_confidence_raw` | LLM抽出の自己評価（真偽ではない） |
| `edges.nli_confidence` | `edges.nli_edge_confidence_raw` | NLI出力スコア（未校正） |
| `edges.nli_label` | `edges.nli_edge_label` | supports/refutes/neutral |
| `edges.confidence` | **削除**（または `edges.legacy_edge_confidence`） | レガシー総合 |
| `fragments.bm25_score` | `fragments.rank_fragment_score_bm25` | rank stage1 |
| `fragments.embed_score` | `fragments.rank_fragment_score_embed` | rank stage2 |
| `fragments.rerank_score` | `fragments.rank_fragment_score_rerank` | rank stage3 |
| （派生） | `fragments.rank_fragment_score_final` | rerank × category_weight（必要なら永続化） |
| `edges.source_domain_category` | `edges.rank_source_domain_category` | ranking参照情報（confidenceではない） |
| `edges.target_domain_category` | `edges.rank_target_domain_category` | 同上 |
| `calibration_evaluations.brier_score` | `calibration_evaluations.calib_brier_score_before` | 校正評価 |
| `calibration_evaluations.brier_score_calibrated` | `calibration_evaluations.calib_brier_score_after` | 校正評価 |
| `calibration_evaluations.expected_calibration_error` | `calibration_evaluations.calib_ece` | 校正評価 |
| `nli_corrections.predicted_confidence` | `nli_corrections.nli_edge_confidence_raw` | NLI出力（補正前） |

#### 4.2 MCP: tool schema / response fields（例：get_materials）

`get_materials` の `claims[]` は **“真偽推定”と“抽出品質”を分離**して出す。

| 現状フィールド | 新（提案） | 意味 |
|---|---|---|
| `claims[].confidence` | `claims[].bayes_claim_confidence` | Beta更新（集約後） |
| （なし） | `claims[].llm_claim_confidence_raw` | DBからのllmスコア |
| （なし） | `claims[].claim_confidence_source` | `bayes | llm_fallback` 等 |
| `claims[].uncertainty` | `claims[].bayes_claim_uncertainty` | Beta stddev |
| `claims[].controversy` | `claims[].bayes_claim_controversy` | conflict |
| `evidence[].nli_confidence` | `evidence[].nli_edge_confidence_raw` | NLIスコア |

#### 4.3 コード: “model signal” の代表的rename

| 現状 | 新（提案） |
|---|---|
| `confidence_info["confidence"]` | `bayes_claim_confidence` |
| `row["claim_confidence"]` | `row["llm_claim_confidence_raw"]` |
| `edge["nli_confidence"]` | `edge["nli_edge_confidence_raw"]` |
| `passage["final_score"]` | `passage["rank_fragment_score_final"]` |
| `passage["category_weight"]` | `passage["rank_fragment_weight_category"]` |

#### 4.4 Prompt templates（`config/prompts/*.j2`）: 出力JSONキー（契約）rename map（初版）

> NOTE: prompt出力キーは「プロンプト ↔ パーサ」の契約そのものなので、正規化するなら **テンプレとパーサの同時変更**が必須。

| 現状 | 新（提案） | 備考 |
|---|---|---|
| `prompt:extract_claims.j2:claim` | `claim_text`（または `llm_claim_text`） | 文字列（識別子/本文系）。canonicalの例外扱い候補 |
| `prompt:extract_claims.j2:type` | `llm_claim_type` | enum（`fact|opinion|prediction`）。`*_label` へ寄せるかは要決定 |
| `prompt:extract_claims.j2:confidence` | `llm_claim_confidence_raw` | DB `claims.claim_confidence` の正規化と揃える |
| `prompt:extract_facts.j2:fact` | `fact_text`（または `llm_fact_text`） | 現状DBに “facts” が無いなら、後段の保存設計とセットで確定 |
| `prompt:extract_facts.j2:confidence` | `llm_fact_confidence_raw` | “fact”導入時の命名 |
| `prompt:decompose.j2:text` | `claim_text`（または `meta_claim_text`） | atomic claim本文 |
| `prompt:decompose.j2:polarity` | `meta_claim_label_polarity_expected` | `expected`/`predicted` の語順は要統一 |
| `prompt:decompose.j2:granularity` | `meta_claim_label_granularity` | enum |
| `prompt:decompose.j2:type` | `meta_claim_label_type` | enum（`factual|causal|...`） |
| `prompt:decompose.j2:keywords` | `meta_claim_keywords` | list[str]（canonical formatの適用方法は要決定） |
| `prompt:decompose.j2:hints` | `meta_claim_hints` | list[str]（canonical formatの適用方法は要決定） |

### 5. 「すべてのパラメータ」を正規化するための拡張手順（漏れゼロ化）

“全パラメータ”を文字通り実施するには、まず **自動抽出でカタログ化**してから、置換と検証を機械的に回す。

#### 5.1 自動抽出（棚卸し）

- **DB**: `schema.sql` から列名・テーブル名を抽出（SQLパーサ or 正規表現）
- **MCP**: `src/mcp/schemas/*.json` の `properties` を全列挙
- **コード/テスト**: `src/` と `tests/` を文字列/属性アクセスで走査（`["..."]`, `.field`, `Field(...)`）
- **Prompt templates**: `config/prompts/*.j2` から **出力JSON例のキー**を抽出（例: `{"confidence": ...}` の `"..."` キー）
- **Code (stringly-typed keys)**: Python AST で `foo["key"]` / `foo.get("key")` / `{"key": ...}` を抽出（構造化モデルに出ない“実ランタイム契約”を拾う）
- **Env vars**: Python AST で `os.getenv("NAME")` / `os.environ.get("NAME")` / `os.environ["NAME"]` を抽出

このリポジトリでは、棚卸しの機械抽出結果を `docs/archive/` に保存している:
- `docs/archive/PARAMETER_REGISTRY_EXTRACTED.md`
- `docs/archive/parameter-registry.prompts-json-keys.json`
- `docs/archive/parameter-registry.code-string-keys.json`
- `docs/archive/parameter-registry.env-vars.json`
- `docs/archive/parameter-registry.shell-make-env.json`
- `docs/archive/PARAMETER_RENAME_MAP_TEMPLATE.json`（old→canonical の作業台・未確定）
- `docs/archive/PARAMETER_RENAME_MAP_DRAFT.json`（初版ドラフト: “keep or rename” を機械充填）

#### 5.2 Parameter Registry（単一の真実）

`docs/archive/parameter-registry.md`（または `src/utils/parameter_registry.py`）に

- canonical_name
- current_name（旧→新の追跡に使うが、破壊的移行なら最終的に不要）
- type（score/confidence/weight/…）
- producer/object
- where（DB/MCP/code）

を持たせ、変更の根拠を残す。

#### 5.3 grepによる漏れ検証（破壊的向け）

移行後に以下の旧名が **0件**であることを保証する（例）:

- `claim_confidence`
- `nli_confidence`
- `bm25_score`, `embed_score`, `rerank_score`, `final_score`, `category_weight`
- `expected_calibration_error`
- `confidence_score`（レガシー名）

加えて、新名が **期待ファイル群に存在**することも確認する。

### 6. 実行順序（実装フェーズ）

1. **DB schema を正規化して再作成**
2. DBアクセス層（SQL/insert/select）を更新
3. EvidenceGraph / ranking / materials / feedback / calibration を更新
4. MCP tool schemas を更新（L7 allowlist）
5. すべてのテストを更新
6. grepで旧名0件＋新名存在チェック

---

### 7. 判断（あなたの質問への直接回答）

- **「今すぐ実行」が良いか？**:  
  **“この計画書の変更リストを確定できるなら”今すぐ実行が合理的**。理由は、破壊的移行は後になるほどコストが増えるため。
- **ただし**、文字通り「全パラメータ」を一撃で正規化するのは巨大になりがちなので、  
  **まず“モデル系のスコア/確信度/重み（signal）”を核として確実に揃え、残りはレジストリ駆動で拡張**が現実的。

