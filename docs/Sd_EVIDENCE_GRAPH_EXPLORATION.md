# Evidence Graph探索インターフェースの課題と提案

## 概要

本文書は、S_FULL_E2E.md ケーススタディ実行中に発見された `get_materials` ツールの課題と、AIエージェントがEvidence Graphを効果的に探索するためのインターフェース改善提案をまとめる。

加えて、ランキングシステムの簡素化とEmbedding永続化の提案を統合する。

---

## 1. 計測結果

### 1.1 task_9c48928b のデータサイズ

| テーブル | 件数 | テキストサイズ |
|----------|------|----------------|
| claims | 333件 | 38 KB |
| fragments | 67件 | 127 KB |
| edges | 333件 | (関係データのみ) |
| **合計テキスト** | - | **162 KB** |

### 1.2 JSONエクスポートサイズ

| ファイル | サイズ | 備考 |
|----------|--------|------|
| claims.json | 23 KB | 100件にLIMIT |
| edges.json | 49 KB | 333件 |
| fragments.json | 145 KB | 67件 |
| **合計** | **217 KB** | メタデータ含む |

### 1.3 get_materials 出力推定

`get_materials(include_graph=true, include_citations=true)` の出力は、上記JSONに加えて以下を含む：
- evidence_graph構造（nodes/edges配列）
- citations network
- summary統計

**推定サイズ: 300-400 KB**

---

## 2. 現状の課題

### 2.1 コンテキストオーバーフロー

**症状**: `get_materials` を1回呼び出すだけで、AIエージェントのコンテキストウィンドウを圧迫し、後続の処理ができなくなる。

**原因**:
- 全データを一度に返却する設計
- 333件のclaims × 関連fragmentsの全テキストが含まれる
- エージェント会話には他の文脈も存在する

### 2.2 探索不可能

**症状**: AIが「このEvidence Graphから何がわかるか」を判断できない。

**原因**:
- データが構造化されていても、量が多すぎて全体を把握できない
- 重要なclaims、矛盾するエビデンス、主要トピックが埋もれる

### 2.3 代替手段の限界

| 代替手段 | 問題 |
|----------|------|
| D3.js可視化 | 人間向け、AIの探索には役立たない |
| 手動でclaims抽出 | スケールしない、自動化できない |

### 2.4 ランキングシステムの問題

| 問題 | 詳細 |
|------|------|
| Rerankerのオーバーヘッド | CrossEncoder (O(n×d²)) は100件→20件の選定に過剰 |
| 効果測定なし | Reranker有無での精度比較データがない |
| 固定top_k | `top_k=20` のハードコードに根拠がない |
| Embedding使い捨て | 計算したEmbeddingがDBに永続化されない |

---

## 3. Lyraの目的との整合性

**Lyraの目的**: AIに信頼できる情報を与える

**必要なもの**:
1. AIがEvidence Graphを**自律的に探索できる**インターフェース
2. **効率的なランキング**（過剰な計算コストを避ける）
3. **永続化されたEmbedding**でセマンティック検索を可能に

---

## 4. 統合提案

### 4.1 アプローチ選定

**採用**: パターンA「SQL実行ツール」+ ベクトル検索ツール

| パターン | 説明 | 採用理由 |
|----------|------|----------|
| A: SQL実行ツール | sqlite3ラッパー、Read-only | ✅ 柔軟性最大、AI自律探索 |
| B: 定型ツール群 | 各ツールが10-20件返却 | ❌ ツール数増加、拡張性低 |

### 4.2 新規MCPツール

#### 4.2.1 `query_graph` - SQL実行ツール

```yaml
name: query_graph
description: |
  Execute read-only SQL against the Evidence Graph database.
  AI can freely explore claims, fragments, edges, pages tables.

  IMPORTANT: This is read-only. No INSERT/UPDATE/DELETE allowed.

  LYRA NOTE (L7): This tool MUST have a JSON schema (src/mcp/schemas/query_graph.json).
  Without a schema, Lyra's ResponseSanitizer may pass responses through unsanitized,
  defeating L7 allowlist filtering.

  SCHEMA HINT (Lyra-compatible):
  - Option A (recommended): query_graph(..., options.include_schema=true) to return a safe schema snapshot.
  - Option B: rely on config/views/*.sql.j2 templates (predefined analysis queries) rather than ad-hoc introspection SQL.

inputSchema:
  type: object
  properties:
    sql:
      type: string
      description: |
        Read-only SQL query. Examples:
        - "SELECT * FROM claims WHERE task_id = 'xxx' LIMIT 10"
        - "SELECT c.*, e.relation FROM claims c JOIN edges e ON c.id = e.source_id"
        - "SELECT * FROM pages WHERE paper_metadata IS NOT NULL"
    options:
      type: object
      additionalProperties: false
      properties:
        limit:
          type: integer
          default: 50
          maximum: 200
          description: Maximum rows to return (safety limit for output size)
        timeout_ms:
          type: integer
          default: 300
          maximum: 2000
          description: Hard timeout to interrupt long-running queries (DoS guard)
        max_vm_steps:
          type: integer
          default: 500000
          maximum: 5000000
          description: SQLite VM instruction budget (DoS guard, works with progress handler)
        include_schema:
          type: boolean
          default: false
          description: Return a safe schema snapshot (tables/columns only), without using PRAGMA from user SQL.
  required: [sql]

outputSchema:
  type: object
  properties:
    ok: { type: boolean }
    rows: { type: array, items: { type: object } }
    row_count: { type: integer }
    columns: { type: array, items: { type: string } }
    truncated: { type: boolean, description: "True if limit was applied" }
    elapsed_ms: { type: integer, description: "Query execution time (ms)" }
    schema:
      type: [object, "null"]
      description: "Only present when options.include_schema=true"
      properties:
        tables:
          type: array
          items:
            type: object
            properties:
              name: { type: string }
              columns: { type: array, items: { type: string } }
            additionalProperties: false
      additionalProperties: false
    error: { type: string }
```

**セキュリティ対策（Lyraの実装に合う形に強化）**:

本プロジェクトは `aiosqlite` を使用しており、MCPサーバは「長時間処理の自爆（DoS）」「ファイルシステム覗き見（ATTACH）」「拡張ロード（load_extension）」を最優先で潰す。

**方針（推奨順）**:
1. **Read-only接続**: `file:...mode=ro`（最重要）
2. **SQLite authorizer**: 危険オペレーションを機械的に拒否（正規表現より堅牢）
3. **progress handler**: VM命令数/経過時間で中断（巨大JOIN等のDoS対策）
4. **単一ステートメント制約**: `;` を含む複文を拒否（複数実行・インジェクション面の縮小）
5. **保険の正規表現**: `ATTACH/DETACH/load_extension/PRAGMA/DDL/DML` を拒否（ログにも出しやすい）

```python
import re
import sqlite3
import time

FORBIDDEN_PATTERNS = [
    r"\bATTACH\b",         # file system access via attach
    r"\bDETACH\b",
    r"\bload_extension\b", # arbitrary code execution
    r"\bCREATE\b", r"\bDROP\b", r"\bALTER\b",  # DDL
    r"\bINSERT\b", r"\bUPDATE\b", r"\bDELETE\b", r"\bREPLACE\b",  # DML
    r"\bPRAGMA\b",         # avoid toggling query_only/trusted_schema/etc from user SQL
]

def validate_sql_text(sql: str) -> None:
    """Reject obvious-dangerous SQL patterns and multi-statement payloads."""
    if ";" in sql.strip().rstrip(";"):
        raise ValueError("Multiple statements are not allowed")
    for pattern in FORBIDDEN_PATTERNS:
        if re.search(pattern, sql, re.IGNORECASE):
            raise ValueError(f"Forbidden SQL keyword detected: {pattern}")

def install_sqlite_guards(conn: sqlite3.Connection, *, timeout_ms: int, max_vm_steps: int) -> None:
    """Install authorizer + progress handler to prevent DoS / file access."""
    deadline = time.time() + (timeout_ms / 1000)

    def authorizer(action_code, param1, param2, dbname, source):
        """
        Pseudocode (Lyra):
        - Use SQLite authorizer callback to block risky operations at the engine level.
        - Deny: ATTACH/DETACH, PRAGMA, DDL/DML, transactions/savepoints, and any extension loading.
        - Allow: READ/SELECT on existing tables only.
        """
        # NOTE: action_code is an int defined by SQLite (not by Python).
        # Implementation should map known action codes (SQLITE_ATTACH, SQLITE_DETACH, SQLITE_PRAGMA, ...)
        # to deny/allow sets. Default should be DENY for unknown codes.
        #
        # return sqlite3.SQLITE_DENY  # for denied operations
        # return sqlite3.SQLITE_OK    # for allowed operations
        return sqlite3.SQLITE_OK  # placeholder (describe deny/allow above; implement in code)

    def progress_handler():
        if time.time() >= deadline:
            return 1  # non-zero => interrupt
        return 0

    conn.set_authorizer(authorizer)
    conn.set_progress_handler(progress_handler, max(1000, max_vm_steps // 1000))

# Read-only connect (critical)
conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
install_sqlite_guards(conn, timeout_ms=300, max_vm_steps=500000)
```

**実装メモ（Lyraに合わせる）**:
- MCPサーバはasyncで動くため、実装は `sqlite3.connect()` の直呼びではなく、`aiosqlite.connect("file:...mode=ro", uri=True)` を使い、必要なら内部コネクションに対して `set_authorizer` / `set_progress_handler` を設定する（イベントループをブロックしない）。

**脅威モデル**（シングルユーザー環境）:

| 脅威 | リスク | 対策 |
|------|--------|------|
| 任意コード実行 | `load_extension()`で共有ライブラリロード | 正規表現で拒否 + Read-only接続 |
| ファイルシステムアクセス | `ATTACH DATABASE '/etc/passwd'` | ATTACH禁止 + Read-only |
| DoS（自爆） | 巨大CROSS JOIN/再帰CTEでCPU/メモリ枯渇 | progress handler（timeout/VM steps）+ 出力行数limit |

#### 4.2.2 `vector_search` - ベクトル検索ツール

```yaml
name: vector_search
description: |
  Semantic similarity search over fragments/claims using embeddings.
  Use BEFORE query_graph to find relevant content by meaning, not keywords.

  WORKFLOW:
  1. vector_search(query="...", target="fragments") → get relevant IDs
  2. query_graph(sql="SELECT * FROM fragments WHERE id IN (...)") → get full data

  LYRA NOTE (L7): This tool MUST have a JSON schema (src/mcp/schemas/vector_search.json),
  otherwise responses may bypass allowlist sanitization.

inputSchema:
  type: object
  properties:
    query:
      type: string
      description: Natural language query for semantic search
    target:
      type: string
      enum: [fragments, claims]
      default: claims
      description: |
        Table to search.
        Lyra product fit suggests claims-first (see §4.4.2). Fragments are follow-ups.
    task_id:
      type: string
      description: |
        Optional. Scope search to specific task.
        - claims: recommended (claims are task-scoped)
        - fragments: optional (task scoping can be done via SQL join/CTE; see §4.4.2.1)
    top_k:
      type: integer
      default: 10
      maximum: 50
      description: Number of results to return
    min_similarity:
      type: number
      default: 0.5
      minimum: 0.0
      maximum: 1.0
      description: Minimum cosine similarity threshold
  required: [query]

outputSchema:
  type: object
  properties:
    ok: { type: boolean }
    results:
      type: array
      items:
        type: object
        properties:
          id: { type: string }
          text_preview: { type: string, description: "First 200 chars" }
          similarity: { type: number }
    total_searched: { type: integer, description: "Total embeddings searched" }
    error: { type: string }
```

### 4.2.3 分析ビュー

探索ヒントを動的に生成するのではなく、**構造化されたビューを事前定義**することで、AIに分析の導線を提供する。

#### Evidence Graph分析

| ビュー名 | 分析目的 | 主要カラム |
|----------|----------|------------|
| `v_claim_evidence_summary` | Claim毎のエビデンス集約状況 | claim_id, claim_text, support_count, refute_count, neutral_count, bayesian_confidence, is_controversial |
| `v_contradictions` | 矛盾するエビデンスを持つClaim | claim_id, claim_text, supporting_fragments, refuting_fragments, controversy_score |
| `v_unsupported_claims` | エビデンス不足のClaim | claim_id, claim_text, evidence_count, uncertainty |
| `v_evidence_chain` | Fragment→Claim→Claimの推論連鎖 | source_fragment_id, intermediate_claim_id, derived_claim_id, chain_confidence |

#### Citation Network分析

| ビュー名 | 分析目的 | 主要カラム |
|----------|----------|------------|
| `v_hub_pages` | 複数Claimを支持する中核ソース | page_id, title, domain, claims_supported, citation_count |
| `v_citation_flow` | 引用関係の方向性 | citing_page_id, cited_page_id, citation_source, hop_distance |
| `v_citation_clusters` | 相互引用するページ群 | cluster_id, page_ids, internal_citations, cluster_size |
| `v_orphan_sources` | 引用されていない孤立ソース | page_id, title, domain, claims_supported |

#### 時系列構造分析

| ビュー名 | 分析目的 | 主要カラム |
|----------|----------|------------|
| `v_evidence_timeline` | 年別エビデンス分布 | year, fragment_count, claim_count, avg_confidence |
| `v_claim_temporal_support` | Claimを支持するエビデンスの時代分布 | claim_id, earliest_year, latest_year, year_span, temporal_consistency |
| `v_emerging_consensus` | 時間経過で支持が増加したClaim | claim_id, claim_text, support_trend, years_observed |
| `v_outdated_evidence` | 古いエビデンスのみに依存するClaim | claim_id, claim_text, newest_evidence_year, years_since_update |

#### 複合分析（Graph × Citation × Timeline）

| ビュー名 | 分析目的 | 主要カラム |
|----------|----------|------------|
| `v_source_authority` | 引用数×被引用数×時間的新しさの総合スコア | page_id, title, authority_score, citation_count, cited_by_count, year |
| `v_controversy_by_era` | 時代別の論争トピック | decade, controversial_claims, consensus_claims, shift_detected |
| `v_citation_age_gap` | 新しい論文が古い論文を引用するパターン | citing_year, cited_year, age_gap, frequency |
| `v_evidence_freshness` | Claim別の最新エビデンス鮮度 | claim_id, claim_text, avg_evidence_age, has_recent_support, has_recent_refutation |

#### ビュー使用例

```
-- AIの典型的な探索パターン

-- 1. まず矛盾を確認
SELECT * FROM v_contradictions ORDER BY controversy_score DESC LIMIT 5;

-- 2. 中核となるソースを特定
SELECT * FROM v_hub_pages ORDER BY claims_supported DESC LIMIT 10;

-- 3. 時系列で見解の変化を追跡
SELECT * FROM v_evidence_timeline WHERE year >= 2015;

-- 4. 古いエビデンスに依存するClaimを警告
SELECT * FROM v_outdated_evidence WHERE years_since_update > 5;
```

**設計原則**:
- ビュー名から分析意図が読み取れる（self-documenting）
- 複雑なJOINはビュー内に隠蔽
- AIは `SELECT * FROM v_xxx` で分析開始可能
- 生SQLも許可（柔軟性維持）

#### SQLテンプレート外部化

LLMプロンプト（`config/prompts/*.j2`）と同様に、SQLビュー定義を外部テンプレート化する。

```
config/
  prompts/          # LLMプロンプト（既存）
    *.j2
  views/            # SQLビュー（新規）
    *.sql.j2
```

**テンプレート例** (`config/views/contradictions.sql.j2`):

```sql
-- 矛盾するエビデンスを持つClaim
SELECT
    c.id as claim_id,
    c.claim_text,
    COUNT(CASE WHEN e.relation = 'supports' THEN 1 END) as support_count,
    COUNT(CASE WHEN e.relation = 'refutes' THEN 1 END) as refute_count
FROM claims c
LEFT JOIN edges e ON e.target_id = c.id AND e.target_type = 'claim'
{% if task_id %}
WHERE c.task_id = '{{ task_id }}'
{% endif %}
GROUP BY c.id
HAVING refute_count > 0 AND support_count > 0
ORDER BY refute_count DESC
```

**ViewManager** (`src/storage/view_manager.py`):

| メソッド | 説明 |
|----------|------|
| `render(view_name, **kwargs)` | テンプレートをレンダリングしてSQL文字列を返す |
| `query(view_name, task_id, limit)` | レンダリング→実行→結果返却 |
| `list_views()` | 利用可能なビュー一覧 |

**使用パターン**:

```python
# 1. 単独クエリ
results = await vm.query("contradictions", task_id="task_xxx", limit=10)

# 2. CTE（WITH句）として組み合わせ
base_sql = vm.render("hub_pages", task_id="task_xxx")
custom_sql = f"WITH hub AS ({base_sql}) SELECT * FROM hub WHERE claims_supported > 3"
```

**メリット**:
- SQLロジックがコードから独立
- 非エンジニアでも`.sql.j2`ファイルを直接編集可能
- `task_id`を動的に注入してタスク単位でスコープ
- CREATE VIEW不要（CTEとして使用、または直接実行）
- 各テンプレートを個別にテスト可能

### 4.3 ランキングシステムの簡素化

#### 4.3.1 Reranker削除

**変更前（3段階）**:
```
BM25 → Embedding → Reranker → top_k固定
```

**変更後（2段階 + 動的カットオフ）**:
```
BM25 → Embedding → 動的カットオフ
```

#### 4.3.2 Kneedleアルゴリズムによる動的カットオフ

**学術的根拠**: [Satopaa et al., "Finding a Kneedle in a Haystack: Detecting Knee Points in System Behavior", ICDCS 2011](https://raghavan.usc.edu/papers/kneedle-simplex11.pdf)

Kneedle はスコア曲線の「膝」（急落点＝最大曲率点）を検出するアルゴリズム。これ以降の結果は追加しても価値が低いことを意味する。

```python
from kneed import KneeLocator

def kneedle_cutoff(
    ranked: list[dict],
    min_results: int = 3,
    max_results: int = 50,
    sensitivity: float = 1.0,
) -> list[dict]:
    """
    Kneedleアルゴリズムによる適応的カットオフ。

    スコア曲線の「膝」（急落点）を検出し、そこでカットオフする。

    Args:
        ranked: スコア降順でソート済みの結果リスト
        min_results: 最低保証件数
        max_results: 最大件数
        sensitivity: Kneedle感度パラメータ（デフォルト1.0）

    Returns:
        カットオフ適用後の結果リスト
    """
    if len(ranked) <= min_results:
        return ranked

    scores = [p["final_score"] for p in ranked[:max_results]]
    x = list(range(len(scores)))

    kneedle = KneeLocator(
        x, scores,
        curve="convex",
        direction="decreasing",
        S=sensitivity,
    )

    cutoff = kneedle.knee if kneedle.knee else len(scores)
    cutoff = max(cutoff, min_results)

    return ranked[:cutoff]
```

**パラメータ根拠**:

| パラメータ | 値 | 根拠 |
|------------|-----|------|
| `sensitivity` | 1.0 | Kneedleデフォルト値（原論文推奨） |
| `min_results` | 3 | 最低保証件数 |
| `max_results` | 50 | 計算量制限 |

#### 4.3.3 設定パラメータ

```yaml
# config/settings.yaml
ranking:
  # Stage 1: BM25
  bm25_top_k: 150  # 旧 reranker.max_top_k

  # Stage 2: Embedding
  embedding_weight: 0.7
  bm25_weight: 0.3

  # 動的カットオフ（Stage 3 Rerankerの代替）
  kneedle_cutoff:
    enabled: true
    min_results: 3
    max_results: 50
    sensitivity: 1.0  # Kneedle S parameter
```

**依存関係追加**:

```toml
# pyproject.toml
[project.dependencies]
kneed = ">=0.8.0"
```

### 4.4 Embeddingとベクトル検索

#### 4.4.1 Embeddingとは

**テキスト → 768次元の数値ベクトルへの変換**

```
"DPP-4阻害薬は血糖値を下げる"
    ↓ bge-m3 モデル
[0.023, -0.156, 0.089, ..., 0.042]  (768個の数値)
```

**特性**: 意味が似たテキストは、ベクトルも近くなる（コサイン類似度が高い）

#### 4.4.2 何をどこに埋め込むか（決定版）

| 対象 | テキスト | タイミング | task紐づき |
|------|----------|-----------|-----------|
| fragment | 抽出したテキスト断片 | 生成/保存時（extract） | task_idは直接は持たない（taskから辿れる） |
| claim | 抽出した主張 | Claim抽出時 | **task固有（claims.task_id）** |

#### 4.4.2.1 スコープ定義（Task / Search / Global）

Lyraには「Task（研究タスク）」の中に複数の「Search（= `queries` 行。検索クエリ実行の単位）」が存在する。
ただしEmbeddingは **Search単位ではなく、DB上の“エンティティ（claim/fragment）”単位**で行うのが自然である。
（`pages` はEvidence Graph/Citationの原典テーブルとして保持するが、本提案では埋め込み対象にしない）

| DBエンティティ | 現状スキーマ上のキー | スコープ（現状の意味論） | 補足 |
|---|---|---|---|
| claim | `claims.id` + `claims.task_id` | **task固有** | Claimは task の成果物（Evidence Graphの最小単位） |
| page | `pages.url`（UNIQUE） / `pages.id` | **グローバル寄り** | 同一URLは再利用され得る（キャッシュ/重複排除の前提） |
| fragment | `fragments.id`（task_idは持たない） | **ページ由来でグローバルだが、taskから辿れる** | task_idが無いので、taskスコープ探索は `claim(task_id)`→`edges`→`fragments` で実現している |

**重要な注意（提案書で明確化すべき点）**:
- `fragments` は **task_idを持たない**。ただしLyraでは task は `claims.task_id` を起点に `edges` を辿って fragment に到達できる。
  そのため「taskスコープの fragment embedding 集合」は、SQLのJOIN/CTEで抽出できる（下記）。

**紐づきの考え方（提案）**:
- Embeddingベクトルは「text × model」で決まるため、原理的にはtaskに依存しない。
- 本提案では **page埋込は行わない**（pageは原典であり、必要時にURL/メタデータを参照すれば足りる）。
- 本提案では **claim + fragment の2対象を最初から実装**する（段階分割はしない）。
- `embeddings` テーブル自体には **task_idを持たせない**。taskスコープの切り出しはSQLで行う。

**例: taskスコープで fragment embeddings を切り出す（JOIN/CTE）**:

```sql
-- task内で参照されているfragment集合を作り、その集合に属するembeddingだけを取得
WITH task_fragments AS (
  SELECT DISTINCT e.source_id AS fragment_id
  FROM edges e
  JOIN claims c
    ON e.target_type = 'claim'
   AND e.target_id = c.id
  WHERE e.source_type = 'fragment'
    AND c.task_id = :task_id
)
SELECT emb.target_id, emb.embedding_blob
FROM embeddings emb
JOIN task_fragments tf
  ON emb.target_type = 'fragment'
 AND emb.target_id = tf.fragment_id
WHERE emb.model_id = :model_id;
```

**例: taskスコープで claim embeddings を切り出す**:

```sql
SELECT emb.target_id, emb.embedding_blob
FROM embeddings emb
JOIN claims c
  ON emb.target_type = 'claim'
 AND emb.target_id = c.id
WHERE c.task_id = :task_id
  AND emb.model_id = :model_id;
```

**埋め込み対象（決定）**:
- **claim + fragment の2対象のみ**
- page は埋め込み対象にしない（原典は query_graph で参照すれば足りる）

#### 4.4.3 ベクトル検索で何ができるか

**Before（FTS5のみ）**:
```sql
-- キーワード一致のみ
SELECT * FROM fragments WHERE text_content LIKE '%血糖%'
```
問題: 「グルコース値」「糖尿病の指標」など、同じ意味でも単語が違うとヒットしない

**After（ベクトル検索）**:
```
vector_search(query="血糖値への影響", target="fragments")
```
結果:
```
| id       | text_preview                          | similarity |
|----------|---------------------------------------|------------|
| frag_012 | "DPP-4阻害薬はグルコース値を..."      | 0.89       |
| frag_045 | "HbA1cの低下が認められ..."            | 0.82       |
| frag_023 | "インスリン分泌を促進し..."           | 0.76       |
```

**違い**: 「血糖」という単語がなくても、**意味的に関連する**断片が見つかる

#### 4.4.4 具体的なユースケース

**1. 矛盾するエビデンスの発見**
```
# AIが「副作用は軽微」という主張に対して
vector_search(query="副作用 深刻 危険", target="fragments")
# → 「重篤な膵炎のリスク」などの反論エビデンスを発見
```

**2. 関連Claimの探索**
```
# あるClaimに関連する他のClaimを探す
vector_search(query="心血管イベントのリスク", target="claims")
# → 心臓病、脳卒中、動脈硬化に関するClaimが見つかる
```

**3. SQL検索との組み合わせ**
```
# Step 1: セマンティック検索でID取得
vector_search(query="長期安全性", target="fragments") → [frag_012, frag_045, ...]

# Step 2: SQLで詳細取得（JOIN、フィルタ等）
query_graph(sql="SELECT f.*, p.url FROM fragments f
                 JOIN pages p ON f.page_id = p.id
                 WHERE f.id IN ('frag_012', 'frag_045')")
```

#### 4.4.5 なぜ永続化が必要か

| 方式 | 問題 |
|------|------|
| 毎回計算 | GPU負荷、遅延（100件で数秒） |
| キャッシュ（現状） | TTL切れで消える、検索不可 |
| **永続化** | 一度計算すれば再利用、検索可能 |

#### 4.4.6 スキーマ変更

```sql
-- cache_embed を置き換え（キャッシュではなく永続データ）
CREATE TABLE IF NOT EXISTS embeddings (
    id TEXT PRIMARY KEY,
    target_type TEXT NOT NULL,  -- 'fragment' | 'claim'
    target_id TEXT NOT NULL,    -- fragments.id | claims.id
    model_id TEXT NOT NULL,     -- 'BAAI/bge-m3'
    embedding_blob BLOB NOT NULL,
    dimension INTEGER NOT NULL,  -- 768
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(target_type, target_id, model_id)
);
CREATE INDEX IF NOT EXISTS idx_embeddings_target ON embeddings(target_type, target_id);
CREATE INDEX IF NOT EXISTS idx_embeddings_type ON embeddings(target_type);

-- 旧 cache_embed は削除
DROP TABLE IF EXISTS cache_embed;
```

**task_id の扱い（決定）**:
- `embeddings` には `task_id` を持たせない
- taskスコープは `claims.task_id` と `edges` のJOIN（上記CTE）で切り出す

#### 4.4.7 永続化タイミング

| タイミング | 処理 |
|-----------|------|
| Claim抽出時 | claims の embedding を永続化 |
| Fragment生成/保存時 | fragments の embedding を永続化 |

#### 4.4.8 ベクトル検索の実装

```python
# src/storage/vector_store.py

async def vector_search(
    query: str,
    target_type: str,  # 'fragment' | 'claim'
    task_id: str | None = None,
    top_k: int = 10,
    min_similarity: float = 0.5,
) -> list[dict]:
    """
    セマンティック類似度検索。

    実装方針:
    - SQLite上でブルートフォース（1000件以下なら十分高速）
    - 将来的にsqlite-vecやhnswlibへの移行も可能
    """
    # 1. クエリのembeddingを計算（ML Server経由）
    ml_client = get_ml_client()
    query_embeddings = await ml_client.embed([query])
    query_vec = query_embeddings[0]

    # 2. 対象のembeddingsをDBから取得
    db = await get_database()

    sql = """
        SELECT e.target_id, e.embedding_blob,
               CASE
                 WHEN e.target_type = 'fragment' THEN f.text_content
                 WHEN e.target_type = 'claim' THEN c.claim_text
               END as text_content
        FROM embeddings e
        LEFT JOIN fragments f ON e.target_type = 'fragment' AND e.target_id = f.id
        LEFT JOIN claims c ON e.target_type = 'claim' AND e.target_id = c.id
        WHERE e.target_type = ?
    """
    params = [target_type]

    # task_idでフィルタ（embeddingsにtask_idは持たせない。JOIN/CTEで絞る）
    if task_id and target_type == "claim":
        sql += " AND c.task_id = ?"
        params.append(task_id)
    elif task_id and target_type == "fragment":
        sql = f"""
        WITH task_fragments AS (
          SELECT DISTINCT e2.source_id AS fragment_id
          FROM edges e2
          JOIN claims c2
            ON e2.target_type = 'claim'
           AND e2.target_id = c2.id
          WHERE e2.source_type = 'fragment'
            AND c2.task_id = ?
        )
        {sql}
        AND e.target_id IN (SELECT fragment_id FROM task_fragments)
        """
        params = [task_id, *params]

    rows = await db.fetch_all(sql, params)

    # 3. コサイン類似度を計算
    results = []
    for row in rows:
        emb = deserialize_embedding(row["embedding_blob"])
        sim = cosine_similarity(query_vec, emb)
        if sim >= min_similarity:
            results.append({
                "id": row["target_id"],
                "similarity": sim,
                "text_preview": row["text_content"][:200] if row["text_content"] else "",
            })

    # 4. ソートしてtop_k返却
    results.sort(key=lambda x: x["similarity"], reverse=True)
    return results[:top_k]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """コサイン類似度（正規化済みベクトル前提）"""
    return sum(x * y for x, y in zip(a, b))
```

**パフォーマンス見込み**:
| 件数 | 想定時間 | 備考 |
|------|----------|------|
| 100件 | ~10ms | 即座 |
| 1,000件 | ~100ms | 許容範囲 |
| 10,000件 | ~1s | 要検討（sqlite-vec導入） |

**将来の最適化オプション**:
- `sqlite-vec`: SQLite拡張でベクトルインデックス
- `hnswlib`: 近似最近傍探索ライブラリ
- NumPy/バッチ処理: 大量データ時の高速化

### 4.5 get_materials の廃止

**決定**: `get_materials` は**完全に廃止**。サマリ機能は `get_status` に統合する。

**理由**:
- サマリを返すだけなら別ツールにする必要がない
- `get_status` は検索完了時に呼ばれる → その時点でサマリを含めれば十分
- ツール数削減によりAIの認知負荷軽減

#### 4.5.1 get_status の拡張

```yaml
# get_status の出力に追加（status=completed の場合のみ）
outputSchema:
  type: object
  properties:
    # ... 既存フィールド ...

    # 完了時のみ含まれるサマリ
    evidence_summary:
      type: object
      description: "Only present when status=completed"
      properties:
        total_claims: { type: integer }
        total_fragments: { type: integer }
        total_pages: { type: integer }
        supporting_edges: { type: integer }
        refuting_edges: { type: integer }
        neutral_edges: { type: integer }
        top_domains: { type: array, items: { type: string } }
```

**分析の導線**: §4.2.3の分析ビューにより、AIは構造化された入口から探索を開始できる。動的なヒント生成ではなく、事前定義されたビューで分析パターンを提供する。

---

## 5. 影響範囲

### 5.1 削除対象

#### Reranker関連（完全削除）

| ファイル | 変更 |
|----------|------|
| `src/ml_server/reranker.py` | **削除** |
| `src/ml_server/main.py` | `/rerank` エンドポイント削除 |
| `src/ml_server/models.py` | `RerankRequest`, `RerankResponse` 削除 |
| `src/ml_server/schemas.py` | `RerankRequest` 削除 |
| `src/ml_server/model_paths.py` | reranker パス削除 |
| `src/ml_client.py` | `rerank()` メソッド、`RerankingError` 削除 |
| `src/filter/ranking.py` | `Reranker` クラス完全削除 |
| `src/scheduler/jobs.py` | `JobKind.RERANK` 削除 |
| `src/utils/config.py` | `RerankerConfig` 削除 |
| `config/settings.yaml` | `reranker:` セクション削除 |
| `docker/Dockerfile.ml` | reranker モデルダウンロード削除 |
| `scripts/download_models.py` | reranker ダウンロード削除 |
| `.env.example` | `LYRA_ML__RERANKER_MODEL` 削除 |
| `tests/test_ranking.py` | reranker モック・テスト削除 |
| `tests/test_ml_server.py` | reranker テスト削除 |
| `tests/test_ml_server_e2e.py` | reranker E2Eテスト削除 |
| `tests/conftest.py` | reranker フィクスチャ削除 |

#### get_materials関連（完全削除）

| ファイル | 変更 |
|----------|------|
| `src/mcp/tools/materials.py` | **削除** |
| `src/mcp/schemas/get_materials.json` | **削除** |
| `src/research/materials.py` | **削除** |
| `src/mcp/server.py` | get_materials ツール定義削除 |
| `tests/test_materials.py` | **削除**（存在する場合） |

#### スキーマ（DB再作成）

| テーブル | 変更 |
|----------|------|
| `cache_embed` | **削除**（`embeddings` に置き換え） |

**注意**: DBはマイグレーションではなく**削除→再作成**。既存データは破棄。

### 5.2 修正対象

| ファイル | 変更 |
|----------|------|
| `src/storage/schema.sql` | `cache_embed` 削除、`embeddings` テーブル新規作成、分析ビュー追加（§4.2.3） |
| `src/storage/database.py` | embedding 永続化メソッド追加 |
| `src/filter/ranking.py` | Reranker削除、動的カットオフ実装、embedding永続化 |
| `src/main.py` | `top_k=20` ハードコード削除 |
| `src/mcp/server.py` | get_materials削除、新規ツール登録 |
| `src/mcp/tools/task.py` | `get_status` にサマリ出力追加 |

### 5.3 新規作成

| ファイル | 内容 |
|----------|------|
| `src/mcp/tools/sql.py` | `query_graph` ツールハンドラ |
| `src/mcp/tools/vector.py` | `vector_search` ツールハンドラ |
| `src/mcp/schemas/query_graph.json` | SQLツールスキーマ |
| `src/mcp/schemas/vector_search.json` | ベクトル検索スキーマ |
| `src/storage/vector_store.py` | Embedding検索ロジック |
| `src/storage/view_manager.py` | SQLビューテンプレート管理（§4.2.3） |
| `config/views/*.sql.j2` | 分析ビューテンプレート（16ファイル） |
| `tests/test_query_graph.py` | SQLツールテスト |
| `tests/test_vector_search.py` | ベクトル検索テスト |
| `tests/test_view_manager.py` | ViewManagerテスト |
| `docs/adr/0017-ranking-simplification.md` | ADR |

### 5.4 ADR更新

| ADR | 変更 |
|-----|------|
| ADR-0001 | lyra-ml から reranker 削除を反映 |
| ADR-0005 | vector_search ツール追加を反映 |
| 新規 ADR-0017 | ランキング簡素化とベクトル検索の設計決定 |

### 5.5 ドキュメント更新

| ファイル | 変更 |
|----------|------|
| `README.md` | MLモデル一覧からreranker削除 |
| `docs/archive/REQUIREMENTS.md` | §3.3, §5.1 の reranker 記述更新 |
| `docs/archive/P_EVIDENCE_SYSTEM.md` | ランキングパイプライン更新 |

---

## 6. 実装方針

### クリーン移行（一括実装）

**原則**: 後方互換性不要。レガシーコードを一切残さず、クリーンに移行する。

```
1. 削除
   - Reranker関連コード・テスト・設定を完全削除
   - get_materials関連コード・テスト・スキーマを完全削除
   - cache_embed テーブル削除

2. 新規実装
   - 動的カットオフ（ranking.py）
   - embeddings テーブル + 永続化ロジック
   - query_graph MCPツール
   - vector_search MCPツール
   - get_status へのサマリ統合

3. DB再作成
   - data/lyra.db を削除
   - schema.sql から新規作成

4. テスト
   - 新規テストのみ作成
   - 旧テストは削除（修正ではなく削除）

5. ドキュメント
   - ADR-0017 新規作成
   - 既存ADR・REQUIREMENTSからreranker/get_materials記述削除
```

### 作業順序

```
[削除] → [スキーマ変更] → [新規実装] → [テスト] → [ドキュメント]
```

**注意**: フラグ制御やマイグレーションは行わない。一括で移行する。

---

## 7. リスクと対策

| リスク | 対策 |
|--------|------|
| Reranker削除で精度低下 | fragments 67件に対しCrossEncoder（O(n×d²)）は過剰。Embeddingスコア + Kneedleカットオフで十分 |
| Embedding永続化でDB肥大 | 768次元 × 4bytes = 3KB/件、許容範囲 |
| 任意コード実行 | Read-only接続 + FORBIDDEN_PATTERNS（§4.2.1参照）。`load_extension`, `ATTACH` 等を正規表現で拒否 |
| ベクトル検索の遅延 | SQLite上でブルートフォース、1000件以下なら許容 |
| 既存データ喪失 | DB再作成のため全データ破棄。問題なし（開発中） |

---

## 8. 期待効果

| 項目 | Before | After |
|------|--------|-------|
| GPU使用量 | Embedding + Reranker | Embedding のみ（約40%削減） |
| ランキング速度 | O(n×d²) CrossEncoder | O(n×d) Embedding のみ |
| DB検索 | FTS5 キーワードのみ | FTS5 + セマンティック検索 |
| AI探索 | get_materials 一括取得（コンテキスト圧迫） | SQL + ベクトル検索で自律探索 |
| 透明性 | AIが何を見たか不明 | SQLクエリで追跡可能 |
| MCPツール数 | 10ツール（get_materials含む） | 10ツール（query_graph, vector_search追加、get_materials削除） |
| コード量 | Reranker + get_materials | 削減（不要コード除去） |

---

## 参考

- 関連タスク: task_9c48928b（DPP-4阻害薬の有効性と安全性）
- 関連ADR: ADR-0005 Evidence Graph Structure
- 関連ファイル: `case_study/lyra/evidence_graph.html`（D3.js可視化）
