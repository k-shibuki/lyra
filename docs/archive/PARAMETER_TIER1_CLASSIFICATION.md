## Tier 1（Pythonコード中の文字列キー）分類と正規化方針（ドラフト）

この文書は **実装変更は行わず**、正規化（一撃置換）に向けて Tier 1（`foo["key"]`, `foo.get("key")`, `{"key": ...}` のような“文字列キー”）を
「正規化すべき契約キー」と「正規化対象外のデータ値」に切り分けるための、**分類結果と意思決定**をまとめる。

### 1. 入力と生成物

- 入力: `docs/archive/parameter-registry.code-string-keys.json`
  - Python AST から抽出した文字列キー（`src/` と `tests/`）
- 生成物:
  - `docs/archive/parameter-registry.tier1-classification.json`
    - 全キーを `normalize / review / keep` に分類（理由・優先度つき）
  - `docs/archive/parameter-registry.tier1-contract-keys.json`
    - `normalize / review` のみ（= “契約キー候補” のみを抽出）

分類スクリプト:
- `docs/archive/classify_tier1_string_keys.py`

### 2. 分類結果（要約）

現時点の分類（heuristic）:
- unique Tier1 keys: **1806**
  - **normalize**: **70**（インターフェース境界付近で “parameter-ish” と判定）
  - **review**: **218**（パラメータっぽいが境界不明／汎用語が多い）
  - **keep**: **1518**（HTTPヘッダ・URL・非ASCII・記号混在など “データ値” 優勢）

### 3. 正規化対象（Tier 1）の定義（決定）

Tier 1 はノイズが多いので、以下のルールで **正規化対象を限定**する。

- **Tier1-in（正規化対象）**:
  - “契約”として扱えるキー
    - `src/mcp/`, `src/storage/`, `src/research/`, `src/report/` など境界モジュール近傍で使われる
    - `*_confidence`, `*_score`, `*_weight`, `*_threshold`, `*_timeout`, `*_ttl`, `*_limit`, `*_ratio`, `*_count`, `*_label` など “parameter-ish”
  - かつ、Tier 0（DB/MCP schema/構造化モデル/prompt契約）の正規化方針と **衝突しない／整合する**もの

- **Tier1-out（正規化対象外）**:
  - HTTPヘッダキー（例: `Accept`, `User-Agent`）
  - URL/path/mime などのプロトコル定数（例: `/health`, `text/html`）
  - 非ASCII／自然言語のリテラル（例: 日本語断片、括弧つき会社種別など）
  - 3rd-party APIの生フィールド名（外部契約）と強く推定されるもの（要ケースで例外）

### 4. Tier 1 の正規化方針（決定）

Tier 1 は “全部一撃でリネーム” ではなく、**Tier 0 へ吸収**させるのが基本方針。

- **方針 A（推奨）: Tier1の汎用語を禁止し、Tier0のcanonicalへ寄せる**
  - 例: `nli_confidence` → `nli_edge_confidence_raw`
  - 例: `claim_confidence` → `llm_claim_confidence_raw`（または `bayes_claim_confidence` 等、意味で分岐）
  - `confidence` のような汎用キーは “review” 扱いにし、意味（LLM/NLI/Bayes）を確定後に **具体名へ分解**する

- **方針 B: Tier1 は局所キーとして keep、境界（MCP/DB）だけ正規化**
  - 実装の破壊が小さいが、「一撃で旧名ゼロ」を狙う場合は漏れが残りやすい

本プロジェクトの要件（破壊的でOK・旧名ゼロをgrepで保証したい）から、**方針Aを採用**する。

### 5. 高優先で “正規化確定” できるキー（例）

以下は Tier 0 と整合し、かつ Tier1 でも使用箇所が明確なので、**正規化対象として確定**できる。

- `nli_confidence`
  - Tier0: DB `edges.nli_confidence` → `edges.nli_edge_confidence_raw`
  - Tier1方針: `nli_confidence` → `nli_edge_confidence_raw`（edge由来を明示）

- `claim_confidence`
  - Tier0: DB `claims.claim_confidence` → `claims.llm_claim_confidence_raw`
  - Tier1方針: `claim_confidence` → `llm_claim_confidence_raw`
  - NOTE: `bayes_claim_confidence` と衝突しやすいので “claim_confidence” は廃止方向

### 6. “review” の代表例と決め方

- `confidence`（汎用語）
  - 同じキーが複数の意味（LLM自己評価/NLI確信度/Bayes集約等）を持つリスクが高い
  - **決め方（決定）**:
    - producer/object を必ず明示して分割する（`llm_*` / `nli_*` / `bayes_*`）
    - 境界（DB/MCP/prompt契約）に出るものは generic `confidence` を禁止

### 7. 次にやるべきこと（docs-only）

- Tier1 `review 218件` について、**私の判断で keep/normalize/split を確定**し、事故防止の置換ガイドも固定化する
  - `docs/archive/parameter-registry.tier1-review-decisions.json`
  - `docs/archive/RG_SAFE_REPLACEMENT_GUIDE.md`

補足:
- `confidence` / `type` / `status` のような汎用キーは **split** として扱い、グローバル置換を禁止する

### 8. split キーを先に“人間判断で確定してから”機械置換へ進むプロセス（決定）

目的: `rg` 一撃の誤爆を避けるため、意味が分岐するキー（split）を先に片付ける。

- **Step 0: split-key 台帳を確定**
  - `docs/archive/parameter-registry.tier1-review-decisions.json`
    - `confidence/type/status` は split として扱い、**グローバル置換禁止**を明記

- **Step 1: split-key をファイル単位で処理（置換する場合のみ）**
  - 置換の可否/先は `parameter-registry.tier1-review-decisions.json` の `replacements[]` を正とする
  - 例:
    - `confidence` は `src/filter/evidence_graph.py` の **legacy edge** だけ `legacy_edge_confidence` に寄せる（他は keep）
    - `type` は JSON Schema の `type` を絶対に触らず、`claim_decomposition` の LLM出力契約だけを `meta_claim_label_type` へ寄せる（promptと同時）

- **Step 2: “問題ないことの確認”**
  - `docs/archive/RG_SAFE_REPLACEMENT_GUIDE.md` の安全ルール（引用符キーのみ、ファイルスコープ、長い→短い順）に従う
  - split キーは置換後に **対象スコープ内の旧キーが0件**であることを確認（`expected_matches_in_scope` を活用）

- **Step 3: 残りを機械的に適用**
  - split が片付いた後、`normalize` 対象（信号系）と Tier0 rename map を機械置換で進める
  - 置換後に `rg` で旧語彙0件（対象語彙セット）を確認してからテストへ

