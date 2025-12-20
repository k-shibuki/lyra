# Trust Level System Design

このドキュメントでは、Lyraの信頼レベル（Trust Level）システムの現状、課題、および改善提案を記述する。

## 目次

1. [用語定義](#用語定義)
2. [現状の設計](#現状の設計)
3. [処理フロー（シーケンス図）](#処理フローシーケンス図)
4. [課題と問題点](#課題と問題点)
5. [関連する学術的フレームワーク](#関連する学術的フレームワーク)
6. [改善提案](#改善提案)
7. [実装ロードマップ](#実装ロードマップ)

---

## 用語定義

### 主要概念

| 用語 | 英語 | 定義 |
|------|------|------|
| **信頼度** | Confidence | 主張が正しい確率の期待値。ベイズ更新により計算。ドメイン分類に依存しない |
| **不確実性** | Uncertainty | 信頼度の不確実さ。エビデンス量が少ないと高い |
| **論争度** | Controversy | 支持と反論が拮抗している度合い |
| **ドメイン分類** | Trust Level | ソースドメインの事前分類（PRIMARY〜BLOCKED）。ランキングのみに使用 |

### エビデンスグラフ関連

| 用語 | 定義 |
|------|------|
| **主張 (Claim)** | 検証対象の事実的主張。エビデンスグラフのノード |
| **フラグメント (Fragment)** | ソースから抽出されたテキスト断片。エッジの起点 |
| **エッジ (Edge)** | 主張とフラグメント間の関係（SUPPORTS/REFUTES/NEUTRAL） |
| **エッジ信頼度** | NLIモデルが出力する関係の確信度（0.0-1.0） |
| **独立ソース数** | 主張を裏付けるユニークなソース（PAGE）の数 |

### ベイズ信頼度モデル（提案）

| 用語 | 定義 |
|------|------|
| **α (alpha)** | 支持エビデンスの累積。事前値1 + SUPPORTSエッジの重み付き合計 |
| **β (beta)** | 反論エビデンスの累積。事前値1 + REFUTESエッジの重み付き合計 |
| **事後分布** | Beta(α, β)。信頼度と不確実性を導出する確率分布 |

### 設計原則

```
信頼度 = f(エビデンス量, エビデンス質)
       ≠ f(ドメイン分類)

ドメイン分類 = ランキング調整のみに使用
             = 高推論AIへの参考情報（エッジに付与）
             ≠ 信頼度計算への入力
```

**根拠**: ドメインが何であれ誤った情報は存在する（再現性危機、論文撤回、ハゲタカジャーナル）。信頼度はエビデンスの量と質のみで決定すべき。

---

## 現状の設計

### Trust Level 定義

ソースのドメインに対して以下の信頼レベルを割り当てる（`src/utils/domain_policy.py`）:

| レベル | 説明 | 重み係数 |
|--------|------|:--------:|
| `PRIMARY` | 標準化団体・レジストリ (iso.org, ietf.org) | 1.0 |
| `GOVERNMENT` | 政府機関 (.go.jp, .gov) | 0.95 |
| `ACADEMIC` | 学術機関 (arxiv.org, pubmed.gov) | 0.90 |
| `TRUSTED` | 信頼メディア・ナレッジベース (専門誌等) | 0.75 |
| `LOW` | L6検証により昇格（UNVERIFIED→LOW）、または Wikipedia | 0.40 |
| `UNVERIFIED` | 未知のドメイン（デフォルト） | 0.30 |
| `BLOCKED` | 除外（矛盾検出/危険パターン） | 0.0 |

**注**: この重み係数は**ランキング時のスコア調整**に使用される（`ranking.py`）。主張の信頼度（confidence）計算には使用しない。信頼度は独立ソース数に基づく（§決定3参照）。

### 割り当てフロー

```
┌─────────────────────────────────────────────────────────────┐
│ 1. config/domains.yaml (allowlist)                          │
│    → 事前定義されたドメインに固定レベルを付与                   │
└─────────────────────────────────────────────────────────────┘
                              ↓ 該当なし
┌─────────────────────────────────────────────────────────────┐
│ 2. デフォルト: UNVERIFIED                                    │
│    → 未知ドメインは暫定採用                                    │
└─────────────────────────────────────────────────────────────┘
                              ↓ L6検証
┌─────────────────────────────────────────────────────────────┐
│ 3. L6 Source Verification (src/filter/source_verification.py)│
│                                                              │
│    昇格条件: ≥2 独立ソースで裏付け → LOW                       │
│    降格条件:                                                  │
│      - 矛盾検出 (UNVERIFIED のみ) → BLOCKED                   │
│      - rejection_rate > 30% (UNVERIFIED/LOW) → BLOCKED       │
│                                                              │
│    TRUSTED以上: REJECTED マークのみ（自動降格なし）            │
└─────────────────────────────────────────────────────────────┘
```

### 現在の矛盾検出ロジック

`source_verification.py:294`:
```python
if has_contradictions or refuting_count > 0:
    if original_trust_level == TrustLevel.UNVERIFIED:
        return (REJECTED, BLOCKED, DEMOTED, "Contradiction detected")
```

**問題**: `refuting_count > 0` で即座にREJECTED/BLOCKEDとなる。

---

## 処理フロー（シーケンス図）

### 現状のフロー

```
┌─────────┐     ┌─────────┐     ┌──────────────┐     ┌─────────────┐     ┌──────────────┐
│Cursor AI│     │   MCP   │     │  Pipeline    │     │Academic API │     │   Browser    │
│         │     │ Server  │     │              │     │(S2/OpenAlex)│     │  (Playwright)│
└────┬────┘     └────┬────┘     └──────┬───────┘     └──────┬──────┘     └──────┬───────┘
     │               │                  │                    │                   │
     │ create_task   │                  │                    │                   │
     │──────────────>│                  │                    │                   │
     │   task_id     │                  │                    │                   │
     │<──────────────│                  │                    │                   │
     │               │                  │                    │                   │
     │ search(query) │                  │                    │                   │
     │──────────────>│                  │                    │                   │
     │               │                  │                    │                   │
     │               │ _is_academic_query()?                 │                   │
     │               │─────────────────>│                    │                   │
     │               │                  │                    │                   │
     │               │    ┌─────────────┴─────────────┐      │                   │
     │               │    │ アカデミック: Yes         │      │                   │
     │               │    │  → 並列検索              │      │                   │
     │               │    │ アカデミック: No          │      │                   │
     │               │    │  → ブラウザのみ          │      │                   │
     │               │    └─────────────┬─────────────┘      │                   │
     │               │                  │                    │                   │
     │               │  [アカデミッククエリの場合]            │                   │
     │               │                  │ search(query)      │                   │
     │               │                  │───────────────────>│                   │
     │               │                  │                    │                   │
     │               │                  │ search_serp(query) │                   │
     │               │                  │───────────────────────────────────────>│
     │               │                  │                    │                   │
     │               │                  │    Papers[]        │                   │
     │               │                  │<───────────────────│                   │
     │               │                  │                    │   SERP items[]    │
     │               │                  │<───────────────────────────────────────│
     │               │                  │                    │                   │
     │               │                  │ ┌──────────────────┴───────────────────┐
     │               │                  │ │ Phase 2-4: 統合・重複排除            │
     │               │                  │ │  - 識別子抽出 (DOI/PMID/ArXiv)       │
     │               │                  │ │  - CanonicalPaperIndex で統合        │
     │               │                  │ └──────────────────┬───────────────────┘
     │               │                  │                    │                   │
     │               │                  │ ┌──────────────────┴───────────────────┐
     │               │                  │ │ Phase 5: Abstract Only               │
     │               │                  │ │  - abstractあり → pages保存          │
     │               │                  │ │  - abstractなし → 未処理 ⚠️          │
     │               │                  │ └──────────────────┬───────────────────┘
     │               │                  │                    │                   │
     │               │                  │ ┌──────────────────┴───────────────────┐
     │               │                  │ │ Phase 6: 引用グラフ (Top 5のみ) ⚠️   │
     │               │                  │ │  - get_citation_graph (S2のみ)       │
     │               │                  │ │  - related_papers はpagesに追加されない│
     │               │                  │ │  - エッジがスキップされる             │
     │               │                  │ └──────────────────┬───────────────────┘
     │               │                  │                    │                   │
     │  SearchResult │<─────────────────│                    │                   │
     │<──────────────│                  │                    │                   │
     │               │                  │                    │                   │
     │  [非アカデミッククエリの場合]     │                    │                   │
     │               │                  │                    │                   │
     │               │                  │ search_serp(query) │                   │
     │               │                  │───────────────────────────────────────>│
     │               │                  │                    │   SERP items[]    │
     │               │                  │<───────────────────────────────────────│
     │               │                  │                    │                   │
     │               │                  │ ┌──────────────────────────────────────┐
     │               │                  │ │ ⚠️ 問題点:                           │
     │               │                  │ │  - 学術API補完なし                   │
     │               │                  │ │  - 引用追跡なし                      │
     │               │                  │ │  - ページ内DOI/学術リンク見逃し      │
     │               │                  │ └──────────────────────────────────────┘
     │               │                  │                    │                   │
     │  SearchResult │<─────────────────│                    │                   │
     │<──────────────│                  │                    │                   │
```

### 現状の問題点

| 箇所 | 問題 |
|------|------|
| アカデミック判定 | キーワードベースで偽陰性あり |
| 非アカデミック検索 | ブラウザのみ、学術リンクを見逃す |
| 引用追跡 | Top 5論文のみ、S2のみ |
| 引用先論文 | pagesに追加されない → エッジがスキップ |
| 新理論 | 引用先が追跡されず孤立ノードになる |

### 改善後のフロー

**設計原則**: アカデミッククエリかどうかは**優先度の違い**であり、非アカデミッククエリでも学術論文に出会えば学術APIを活用する。

```
┌─────────┐     ┌─────────┐     ┌──────────────┐     ┌─────────────┐     ┌──────────────┐
│Cursor AI│     │   MCP   │     │  Pipeline    │     │Academic API │     │   Browser    │
│         │     │ Server  │     │              │     │(S2+OpenAlex)│     │  (Playwright)│
└────┬────┘     └────┬────┘     └──────┬───────┘     └──────┬──────┘     └──────┬───────┘
     │               │                  │                    │                   │
     │ create_task   │                  │                    │                   │
     │──────────────>│                  │                    │                   │
     │   task_id     │                  │                    │                   │
     │<──────────────│                  │                    │                   │
     │               │                  │                    │                   │
     │ search(query) │                  │                    │                   │
     │──────────────>│                  │                    │                   │
     │               │                  │                    │                   │
     │               │ ┌────────────────┴────────────────────┴───────────────────┐
     │               │ │         Phase 1: ブラウザ検索（常に実行）                │
     │               │ │  ┌─────────────────────────────────────────────────────┐│
     │               │ │  │ search_serp(query)                                  ││
     │               │ │  │   → SERP items                                      ││
     │               │ │  │   → 識別子抽出 (DOI/PMID/ArXiv/URL)                 ││
     │               │ │  └─────────────────────────────────────────────────────┘│
     │               │ └────────────────┬────────────────────────────────────────┘
     │               │                  │
     │               │ ┌────────────────┴────────────────────────────────────────┐
     │               │ │         Phase 2: 学術API検索（アカデミッククエリ時）     │
     │               │ │  ┌─────────────────────────────────────────────────────┐│
     │               │ │  │ if _is_academic_query(query):                       ││
     │               │ │  │   → S2 + OpenAlex 並列検索                          ││
     │               │ │  │   → CanonicalIndex で重複排除                       ││
     │               │ │  └─────────────────────────────────────────────────────┘│
     │               │ └────────────────┬────────────────────────────────────────┘
     │               │                  │
     │               │ ┌────────────────┴────────────────────────────────────────┐
     │               │ │         Phase 3: 学術識別子があればAPI補完              │
     │               │ │  ┌─────────────────────────────────────────────────────┐│
     │               │ │  │ SERP内のDOI/PMID/ArXiv付きエントリに対して:         ││
     │               │ │  │   → S2/OpenAlex でメタデータ取得                    ││
     │               │ │  │   → abstract取得                                    ││
     │               │ │  │ ※ 非アカデミッククエリでも発動                      ││
     │               │ │  └─────────────────────────────────────────────────────┘│
     │               │ └────────────────┬────────────────────────────────────────┘
     │               │                  │
     │               │ ┌────────────────┴────────────────────────────────────────┐
     │               │ │         Phase 4: pages登録                              │
     │               │ │  ┌─────────────────────────────────────────────────────┐│
     │               │ │  │ abstractあり → pages/fragments保存                  ││
     │               │ │  │ abstractなし → ブラウザfetch候補に追加              ││
     │               │ │  └─────────────────────────────────────────────────────┘│
     │               │ └────────────────┬────────────────────────────────────────┘
     │               │                  │
     │               │ ┌────────────────┴────────────────────────────────────────┐
     │               │ │         Phase 5: 引用追跡（全学術論文に対して）         │
     │               │ │  ┌─────────────────────────────────────────────────────┐│
     │               │ │  │ 全papers（APIとブラウザ両方）に対して:               ││
     │               │ │  │   1. get_citation_graph(depth=1) [S2 + OpenAlex]    ││
     │               │ │  │   2. related_papers のabstract取得                  ││
     │               │ │  │   3. 関連性フィルタリング (B+C hybrid)              ││
     │               │ │  │      - is_influential: 0.5                          ││
     │               │ │  │      - embedding similarity: 0.3                    ││
     │               │ │  │      - NLI relevance: 0.2                           ││
     │               │ │  │   4. 上位10件をpagesに追加                          ││
     │               │ │  │   5. CITESエッジ作成                                ││
     │               │ │  └─────────────────────────────────────────────────────┘│
     │               │ └────────────────┬────────────────────────────────────────┘
     │               │                  │
     │               │ ┌────────────────┴────────────────────────────────────────┐
     │               │ │         Phase 6: ブラウザfetch（必要な場合）            │
     │               │ │  ┌─────────────────────────────────────────────────────┐│
     │               │ │  │ abstractなしエントリ / 非学術URL                     ││
     │               │ │  │   → Playwright fetch                                ││
     │               │ │  │   → コンテンツ抽出                                  ││
     │               │ │  │   → ページ内DOI/学術リンク抽出 → Phase 3へ          ││
     │               │ │  └─────────────────────────────────────────────────────┘│
     │               │ └────────────────┬────────────────────────────────────────┘
     │               │                  │
     │               │ ┌────────────────┴────────────────────────────────────────┐
     │               │ │         Phase 7: エビデンスグラフ構築                   │
     │               │ │  ┌─────────────────────────────────────────────────────┐│
     │               │ │  │ NLI評価 → SUPPORTS/REFUTES/NEUTRAL エッジ作成       ││
     │               │ │  │ エッジに source_trust_level/target_trust_level 付与 ││
     │               │ │  │ claim_confidence計算（独立ソース数ベース）          ││
     │               │ │  └─────────────────────────────────────────────────────┘│
     │               │ └────────────────┬────────────────────────────────────────┘
     │               │                  │
     │  SearchResult │<─────────────────┘
     │<──────────────│
     │               │
     │ get_status    │
     │──────────────>│
     │   status      │
     │<──────────────│
     │               │
     │ stop_task     │
     │──────────────>│
     │               │
     │ get_materials │
     │──────────────>│
     │   materials   │
     │<──────────────│
```

### 改善のポイント

| 観点 | 現状 | 改善後 |
|------|------|--------|
| ブラウザ検索 | アカデミッククエリ時のみ並列 | 常に実行（Phase 1） |
| 学術API補完 | アカデミッククエリ時のみ | DOI/PMID発見時に常に発動（Phase 3） |
| 引用追跡 | Top 5論文、S2のみ | 全学術論文、S2 + OpenAlex |
| 引用先論文 | pagesに追加されない | 関連性上位10件を追加 |
| 関連性判定 | なし | B+C hybrid |
| ページ内リンク | 無視 | DOI/学術リンク抽出 → Phase 3へ |

---

## 課題と問題点

### 課題1: 科学的論争と誤情報の混同

現在の設計は以下の2ケースを区別しない:

| ケース | 例 | 現在の処理 | あるべき処理 |
|--------|-----|-----------|-------------|
| **誤情報** | 怪しいブログが確立事実に矛盾 | BLOCKED | BLOCKED ✓ |
| **科学的論争** | PubMed論文AとBが対立する見解 | 片方がBLOCKED | 両方を保持、REFUTESエッジで対立関係を記録 |

**具体例**:
- 論文A (pubmed.gov): 「薬剤Xは有効」
- 論文B (pubmed.gov): 「薬剤Xに有意差なし」

両者ともACADEMIC信頼レベルであり、正当な科学的議論。
現状は後から発見された方が矛盾として処理されうる。
**あるべき姿**: 両者を保持し、REFUTESエッジ + 信頼レベル情報を記録。解釈は高推論AIに委ねる。

### 課題2: 対立関係の情報不足

現在のシステムでは:
- **Trust Level** (ドメインレベル): iso.org → PRIMARY
- **Confidence** (主張レベル): evidence_graph.get_claim_confidence()

しかし矛盾検出時に、対立関係の「出自」が記録されていない:
- REFUTESエッジに信頼レベル情報がない
- 高推論AIが「これは科学的論争か誤情報か」を判断する材料が不足

**注**: 信頼レベルはconfidence計算に使うべきではない（信頼度が主）。あくまで高推論AIへの参考情報としてエッジに付与する。

### 課題3: 引用追跡の不完全性

新理論が既存理論と対立した場合、引用文献がエビデンスグラフに含まれていないと「孤立ノード」となり、不当に低いconfidenceが算出される。

```
既存理論A (多くのエッジ、高confidence)
    │
    │ 対立
    ▼
新理論B (査読済み ACADEMIC)
    │
    └──引用──> C, D, E (Bの主張を支持する論文)
                ↓
          pagesテーブルになければスキップ
                ↓
          Bは孤立ノード → confidence低い
```

### 課題4: ユーザー制御の欠如

- ブロックされたドメインをユーザーが確認・復元できない
- エビデンスグラフ上でブロック理由が可視化されていない
- 手動での信頼レベル上書きができない

### 課題5: 透明性の不足

- なぜそのドメインがBLOCKEDになったか追跡困難
- 矛盾検出のログが不十分

---

## 関連する学術的フレームワーク

### NATO Admiralty Code

情報評価の標準フレームワーク。ソースの信頼性と情報の信憑性を分離して評価する。

| ソース信頼性 | 情報信憑性 |
|-------------|-----------|
| A: 完全に信頼できる | 1: 事実確認済み |
| B: 通常信頼できる | 2: おそらく真実 |
| C: かなり信頼できる | 3: 可能性あり |
| D: 通常信頼できない | 4: 疑わしい |
| E: 信頼できない | 5: 可能性低い |
| F: 判定不能 | 6: 判定不能 |

**参考**: [Kraven Security - Source Reliability](https://kravensecurity.com/source-reliability-and-information-credibility/)

### ~~GRADE Framework~~ [リジェクト]

> **リジェクト理由**: Lyraは学術論文に関してはアブストラクトのみを扱う設計（REQUIREMENTS.md §1.0「学術論文はAbstract Only」）であり、フルテキストを前提とするGRADEフレームワークとは相性が悪い。

### 統合信頼性モデル

信頼は層構造で形成される:
1. **Propensity to Trust**: 一般的な信頼傾向
2. **Medium Trust**: メディア（ウェブ、学術誌等）への信頼
3. **Source Trust**: 具体的なソースへの信頼
4. **Information Trust**: 個別情報への信頼

**参考**: [ACM - Propensity to Trust](https://dl.acm.org/doi/10.1177/0165551512459921)

### エビデンス統合

システマティックレビューでは、矛盾するエビデンスを **統合** して評価する:
- 矛盾の原因を分析（方法論、対象集団、測定方法の差異）
- 異質性（heterogeneity）を定量化
- メタ分析で効果サイズを統合

**参考**: [Cornell - Evidence Synthesis Guide](https://guides.library.cornell.edu/evidence-synthesis/intro)

---

## 改善提案

### 提案1: エッジへの信頼レベル情報追加

**設計原則**: 対立関係をエッジとして記録し、**解釈は高推論AIに委ねる**。

Lyraは「AがBを反論している」という**事実**をエッジで記録する。「これは科学的論争か誤情報か」という**解釈**は高推論AIの責務であり、Lyraは踏み込まない（Thinking-Working分離の原則）。

#### 1.1 スキーマ変更

```sql
-- migrations/003_add_trust_level_to_edges.sql
ALTER TABLE edges ADD COLUMN source_trust_level TEXT;
ALTER TABLE edges ADD COLUMN target_trust_level TEXT;

-- インデックス追加（対立関係の高速検索用）
CREATE INDEX IF NOT EXISTS idx_edges_trust_levels
    ON edges(relation, source_trust_level, target_trust_level);
```

#### 1.2 エッジ作成時の信頼レベル付与

```python
# evidence_graph.py: add_edge() の拡張
def add_edge(
    self,
    source_type: NodeType,
    source_id: str,
    target_type: NodeType,
    target_id: str,
    relation: RelationType,
    confidence: float | None = None,
    nli_label: str | None = None,
    nli_confidence: float | None = None,
    source_trust_level: str | None = None,  # 追加
    target_trust_level: str | None = None,  # 追加
    **attributes: Any,
) -> str:
    ...
```

#### 1.3 NLI評価時の呼び出し

```python
from src.utils.domain_policy import get_domain_trust_level

# REFUTESエッジ作成時に信頼レベルを付与
source_trust = get_domain_trust_level(source_domain)
target_trust = get_domain_trust_level(target_domain)

graph.add_edge(
    source_type=NodeType.FRAGMENT,
    source_id=fragment_id,
    target_type=NodeType.CLAIM,
    target_id=claim_id,
    relation=RelationType.REFUTES,
    nli_confidence=0.92,
    source_trust_level=source_trust.value,  # "academic"
    target_trust_level=target_trust.value,  # "unverified"
)
```

#### 1.4 高推論AIへの情報提供

エビデンスグラフのエクスポート時、高推論AIは以下の情報を受け取る：

```json
{
  "edges": [
    {
      "source": "fragment:abc123",
      "target": "claim:def456",
      "relation": "refutes",
      "nli_confidence": 0.92,
      "source_trust_level": "academic",
      "target_trust_level": "unverified"
    }
  ]
}
```

高推論AIはこれを見て：
- 両方 ACADEMIC → 「科学的論争」と判断
- ACADEMIC vs UNVERIFIED → 「誤情報の可能性」と判断

**Lyraは判断しない。事実を記録するのみ。**

#### 1.5 設計原則: 信頼度が主、ドメイン分類は従

**重要**: **信頼度（confidence）がエビデンス評価の主軸**。ドメイン分類は副次的。

| 概念 | 定義 | 重要度 |
|------|------|:------:|
| **confidence** (信頼度) | エビデンスの量・質に基づく主張の確からしさ | **主** |
| **TrustLevel** (ドメイン分類) | ドメインの事前分類 (PRIMARY〜BLOCKED) | 従 |

```python
# 信頼度計算（evidence_graph.py: calculate_claim_confidence）
# エビデンスの量と質で決まる（これが重要）
confidence = f(supporting_count, refuting_count, independent_sources)

# ドメイン分類は confidence 計算に寄与しない
# 高推論AIへの参考情報としてエッジに付与するのみ
```

#### 1.6 技術的根拠: なぜドメインを盲信しないか

**査読済み論文 ≠ 正しい情報**:

| 事実 | 含意 |
|------|------|
| 再現性危機（Replication Crisis） | 心理学研究の60%以上が再現不可能 |
| 論文撤回 | 年間数千件の査読済み論文が撤回 |
| プレプリント | arXiv等は査読なし |
| 低品質ジャーナル | ハゲタカジャーナル（predatory journals）の存在 |

**「ACADEMICドメインだから正しい」は技術的に誤り**。

```
単一論文 = 仮説
複数の独立ソースで裏付け = 蓋然性の高い主張
```

**設計への反映**:
- Nature論文でも裏付けなし → 低confidence（正しい動作）
- 無名ブログでも5つの独立ソースで裏付け → 高confidence（正しい動作）
- ドメイン分類は「出自のヒント」であり、信頼性の保証ではない
- エッジの`source_trust_level`/`target_trust_level`は高推論AIの参考情報

### 提案2: データソース戦略

#### 2.1 学術API（完全実装対象）

| API | 検索 | 引用取得 | 実装状況 |
|-----|:----:|:-------:|:-------:|
| **Semantic Scholar** | ✓ | ✓ | 完了 |
| **OpenAlex** | ✓ | 要実装 | 検索のみ |

**OpenAlex引用追跡を実装する根拠**:

学術研究によるカバレッジ比較（2024-2025）:

| 指標 | OpenAlex | Semantic Scholar |
|------|:--------:|:----------------:|
| カバレッジ（PCOS Case Study） | **98.6%** | 98.3% |
| メタデータ精度 | **高い** | 中程度 |
| 社会科学・人文学 | **優れている** | 弱い |
| 地理的・言語的バイアス | **少ない** | あり |
| `isInfluential` フラグ | なし | **あり** |

- [Analysis of Publication and Document Types (arXiv 2024)](https://arxiv.org/abs/2406.15154)
- [PCOS Guidelines Coverage Study (2025)](https://www.sciencedirect.com/science/article/pii/S0895435625001222)

S2単独では社会科学・人文学・非英語圏の論文カバレッジが不足する。両者を併用し、DOIベースで重複排除することで最大カバレッジを達成する。

**OpenAlex引用取得の実装**:
```python
async def get_references(self, paper_id: str) -> list[tuple[Paper, bool]]:
    """referenced_works フィールドから引用先を取得"""
    paper_data = await self.get_paper_with_references(paper_id)
    referenced_ids = paper_data.get("referenced_works", [])

    results = []
    for ref_id in referenced_ids[:20]:  # 上位20件
        ref_paper = await self.get_paper(ref_id)
        if ref_paper and ref_paper.abstract:
            results.append((ref_paper, False))  # OpenAlexはinfluentialフラグなし
    return results

async def get_citations(self, paper_id: str) -> list[tuple[Paper, bool]]:
    """filter=cites:{work_id} で被引用論文を取得"""
    ...
```

#### 2.2 補助API（現状維持）

| API | 役割 | 引用追跡 |
|-----|------|:-------:|
| Crossref | DOI解決 | 不要 |
| Unpaywall | OAリンク解決 | 不要 |
| arXiv | プレプリント検索 | S2経由で補完 |

#### 2.3 ブラウザ補完

- PubMed → ブラウザ検索 + S2/OpenAlexでメタデータ補完
- Google Scholar → ブラウザ検索
- 一般Webサイト → ブラウザfetch → ページ内DOI抽出

### 提案3: 引用追跡の完全実装

#### 3.1 引用先論文の自動追加

```python
async def process_citation_graph(
    paper: Paper,
    query: str,
    paper_to_page_map: dict[str, str],
) -> None:
    """引用グラフを取得し、関連性の高い論文をpagesに追加"""

    # 1. S2 + OpenAlex から引用グラフ取得
    s2_refs = await s2_client.get_references(paper.id)
    oa_refs = await oa_client.get_references(paper.id)

    # 重複排除して統合
    all_refs = deduplicate_by_doi(s2_refs + oa_refs)

    # 2. 関連性フィルタリング
    relevant_papers = await filter_relevant_citations(
        source_paper=paper,
        related_papers=all_refs,
        query=query,
        max_count=10,
    )

    # 3. pagesに追加
    for ref_paper, relevance_score in relevant_papers:
        if ref_paper.id not in paper_to_page_map:
            page_id = await persist_abstract_as_fragment(ref_paper)
            paper_to_page_map[ref_paper.id] = page_id

    # 4. CITESエッジ作成
    await add_academic_page_with_citations(
        page_id=paper_to_page_map[paper.id],
        citations=relevant_papers,
        paper_to_page_map=paper_to_page_map,
    )
```

#### 3.2 関連性フィルタリング（B+C hybrid）

```python
async def filter_relevant_citations(
    source_paper: Paper,
    related_papers: list[tuple[Paper, bool]],
    query: str,
    max_count: int = 10,
) -> list[tuple[Paper, float]]:
    """
    関連性でフィルタリング

    スコア配分:
    - is_influential (S2): 0.5
    - embedding similarity: 0.3
    - NLI relevance: 0.2
    """
    scored_papers = []

    for paper, is_influential in related_papers:
        if not paper.abstract:
            continue

        score = 0.0

        # A. is_influential (S2のみ、高い信頼性)
        if is_influential:
            score += 0.5

        # B. 埋め込み類似度
        embedding_sim = await compute_embedding_similarity(
            source_paper.abstract, paper.abstract
        )
        score += embedding_sim * 0.3

        # C. NLI（クエリとの関連性）
        nli_score = await compute_nli_relevance(query, paper.abstract)
        score += nli_score * 0.2

        scored_papers.append((paper, score))

    # スコア順にソート、上位max_count件
    scored_papers.sort(key=lambda x: x[1], reverse=True)
    return scored_papers[:max_count]
```

### 提案4: ユーザー制御インターフェース

#### 4.1 ブロック状態の可視化

既存MCPツール `get_status` を拡張:

```python
{
    ...
    "blocked_domains": [
        {
            "domain": "example.com",
            "blocked_at": "2024-01-15T10:30:00Z",
            "reason": "Contradiction with pubmed.gov (claim_id: abc123)",
            "contradicting_claims": ["claim:abc123"],
            "original_trust_level": "UNVERIFIED",
            "can_restore": true,
            "restore_via": "config/domains.yaml user_overrides"
        }
    ]
}
```

#### 4.2 信頼レベルのオーバーライド

`config/domains.yaml` に `user_overrides` セクション:

```yaml
user_overrides:
  - domain: "blocked-but-valid.org"
    trust_level: "low"
    reason: "Manual review completed - false positive"
    added_at: "2024-01-15"
```

**設計決定**: MCPツールは11ツール体制を維持。手動復元は設定ファイル編集で対応。

### 提案5: Wikipediaの扱い

**状態**: ✅ 実装済み

Wikipedia は `LOW` (0.40) として設定済み（`config/domains.yaml:108-113`）:

```yaml
- domain: "wikipedia.org"
  trust_level: "low"  # Downgraded: anyone can edit, quality varies by article
  qps: 0.5
  headful_ratio: 0
  max_requests_per_day: 500
  max_pages_per_day: 250
```

出典追跡機能は実装しない（通常ドメインとして扱う）。

### 提案6: ベイズ信頼度モデル

#### 6.1 設計思想

**無情報事前分布 + ベイズ更新**により、ドメイン分類に依存しない信頼度計算を実現する。

```
事前分布: Beta(1, 1) = 一様分布（「何も知らない」状態）
更新: エッジ（SUPPORTS/REFUTES）で逐次更新
事後分布: Beta(α, β) → confidence, uncertainty, controversy を導出
```

#### 6.2 計算アルゴリズム

```python
import math

def calculate_claim_confidence_bayesian(claim_id: str) -> dict:
    """ベイズ更新による信頼度計算

    無情報事前分布 Beta(1, 1) から開始し、
    各エッジのNLI信頼度で重み付けして更新する。
    """

    # 無情報事前分布: Beta(1, 1)
    alpha = 1.0  # 支持の擬似カウント
    beta = 1.0   # 反論の擬似カウント

    edges = get_edges_for_claim(claim_id)

    for edge in edges:
        weight = edge.nli_confidence  # NLIの確信度で重み付け

        if edge.relation == RelationType.SUPPORTS:
            alpha += weight
        elif edge.relation == RelationType.REFUTES:
            beta += weight
        # NEUTRAL は更新しない（情報なし）

    # 事後分布 Beta(α, β) から統計量を計算
    confidence = alpha / (alpha + beta)  # 期待値

    # 不確実性（標準偏差）
    variance = (alpha * beta) / ((alpha + beta)**2 * (alpha + beta + 1))
    uncertainty = math.sqrt(variance)

    # 論争度（αとβの両方が大きい場合に高い）
    total_evidence = alpha + beta - 2  # 事前分布を除いた実エビデンス量
    if total_evidence > 0:
        controversy = min(alpha - 1, beta - 1) / total_evidence
    else:
        controversy = 0.0

    return {
        "confidence": round(confidence, 3),
        "uncertainty": round(uncertainty, 3),
        "controversy": round(controversy, 3),
        "alpha": round(alpha, 2),
        "beta": round(beta, 2),
        "evidence_count": len(edges),
    }
```

#### 6.3 挙動の例

| 状態 | α | β | confidence | uncertainty | controversy | 解釈 |
|------|:-:|:-:|:----------:|:-----------:|:-----------:|------|
| エビデンスなし | 1.0 | 1.0 | 0.50 | 0.29 | 0.00 | 何も分からない |
| SUPPORTS ×1 (0.9) | 1.9 | 1.0 | 0.66 | 0.22 | 0.00 | やや支持寄り |
| SUPPORTS ×3 (0.9) | 3.7 | 1.0 | 0.79 | 0.13 | 0.00 | かなり支持 |
| SUPPORTS ×3, REFUTES ×1 | 3.7 | 1.9 | 0.66 | 0.14 | 0.24 | 支持だが論争あり |
| SUPPORTS ×5, REFUTES ×5 | 5.5 | 5.5 | 0.50 | 0.09 | 0.45 | 五分五分、論争的 |

#### 6.4 設計上の利点

| 観点 | 評価 |
|------|------|
| ドメイン分類に依存しない | ✓ 思想と完全に一貫 |
| エビデンス量が反映される | ✓ α+βの増加で uncertainty 低下 |
| 論争状態を表現できる | ✓ 両方大きいと controversy 高い |
| Lyraで計算可能 | ✓ NLI confidence とエッジ数のみ必要 |
| 数学的に厳密 | ✓ 再現性・検証可能 |
| 解釈が直感的 | ✓ 「50%で高uncertainty」=「分からない」 |

#### 6.5 現行実装との互換性

現行の `calculate_claim_confidence()` を置き換えるが、出力形式は互換性を維持：

```python
# 現行出力
{
    "confidence": 0.7,
    "supporting_count": 3,
    "refuting_count": 1,
    "verdict": "supported",
    "independent_sources": 2,
}

# 新出力（上位互換）
{
    "confidence": 0.66,           # ベイズ期待値
    "uncertainty": 0.14,          # 新規追加
    "controversy": 0.24,          # 新規追加
    "alpha": 3.7,                 # 新規追加
    "beta": 1.9,                  # 新規追加
    "supporting_count": 3,        # 互換性維持
    "refuting_count": 1,          # 互換性維持
    "verdict": "supported",       # 互換性維持
    "independent_sources": 2,     # 互換性維持
    "evidence_count": 4,          # 新規追加
}
```

---

## 実装ロードマップ

### Phase 1: 透明性の向上（低リスク・高価値）

目的: 判断根拠の可視化と監査可能性の確保

1. [ ] `get_status` への `blocked_domains` 情報追加
2. [ ] ブロック理由のログ強化（`cause_id` 連携）
3. [ ] エビデンスグラフに矛盾関係を明示的に保存
4. [ ] 不採用主張（`not_adopted`）のグラフ保持

### Phase 2: エッジへの信頼レベル情報追加（中リスク・高価値）【優先】

目的: 対立関係の解釈に必要な情報を高推論AIに提供する

**この Phase を先に実装する根拠**:
Phase 3（引用追跡）で追加される論文間の対立関係を、高推論AIが適切に解釈できるようにする。現行の`refuting_count > 0`で即BLOCKEDとなる問題も、エッジ情報に基づく判断基準の緩和で解決する。

1. [ ] スキーマ変更: `edges`テーブルに`source_trust_level`, `target_trust_level`カラム追加
2. [ ] `evidence_graph.py`: `add_edge()`にパラメータ追加
3. [ ] NLI評価時に信頼レベルを取得してエッジに付与
4. [ ] `_determine_verification_outcome`の改修: 即時BLOCKEDを緩和
5. [ ] `to_dict()`でエッジの信頼レベル情報をエクスポート

**テストケース**:
```python
def test_edge_contains_trust_levels():
    """REFUTESエッジにsource/target信頼レベルが含まれることを検証"""

def test_academic_refutes_unverified_not_blocked():
    """ACADEMIC→UNVERIFIED反論でも即BLOCKEDにならないことを検証"""

def test_evidence_graph_export_includes_trust():
    """to_dict()出力に信頼レベル情報が含まれることを検証"""
```

### Phase 3: 引用追跡の完全実装（中リスク・高価値）

目的: 孤立ノード問題を解決し、エビデンスグラフを充実

1. [ ] OpenAlex `get_references()` / `get_citations()` 実装
2. [ ] 引用先論文のpagesテーブル自動追加
3. [ ] 関連性フィルタリング（B+C hybrid）実装
4. [ ] AcademicProvider でS2/OpenAlex両方からの引用グラフ統合
5. [ ] 非アカデミッククエリでも学術識別子発見時にAPI補完

**テストケース**:
```python
def test_citation_tracking_adds_referenced_papers():
    """引用先論文がpagesに追加されることを検証"""

def test_new_theory_not_isolated():
    """新理論が孤立ノードにならないことを検証"""

def test_relevance_filtering_top_10():
    """関連性フィルタリングで上位10件が選択されることを検証"""
```

### Phase 4: ベイズ信頼度モデル（中リスク・高価値）

目的: 数学的に厳密な信頼度計算を導入し、不確実性と論争度を明示化

**この Phase を Phase 3 の後に実装する根拠**:
引用追跡（Phase 3）によりエビデンスグラフが充実した後にベイズモデルを導入することで、より正確なconfidence/uncertainty/controversy計算が可能になる。エビデンス量が少ない段階での導入は効果が限定的。

1. [ ] `calculate_claim_confidence_bayesian()` の実装
2. [ ] 現行 `calculate_claim_confidence()` との並行運用（A/Bテスト）
3. [ ] 出力スキーマの拡張（uncertainty, controversy, alpha, beta 追加）
4. [ ] MCPレスポンス（`get_materials`）への反映
5. [ ] 既存テストの更新と新規テスト追加

**テストケース**:
```python
def test_uninformative_prior():
    """エビデンスなしでconfidence=0.5, uncertainty=0.29を検証"""

def test_supports_increase_confidence():
    """SUPPORTSエッジ追加でconfidence上昇を検証"""

def test_controversy_detection():
    """SUPPORTS/REFUTES拮抗時にcontroversy上昇を検証"""

def test_uncertainty_decreases_with_evidence():
    """エビデンス増加でuncertainty低下を検証"""

def test_backward_compatibility():
    """既存フィールド（supporting_count等）が維持されることを検証"""
```

### Phase 5: ユーザー制御（中リスク・中価値）

目的: ブロック状態からの復活手段を提供

1. [ ] `get_status` 応答に `can_restore` フラグを追加
2. [ ] `config/domains.yaml` に `user_overrides` セクション追加
3. [ ] 設定ファイルのhot-reload対応確認

---

## VerificationStatus について

**決定**: 現行の3値（PENDING/VERIFIED/REJECTED）を維持。拡張しない。

```python
class VerificationStatus(str, Enum):
    """検証ステータス（変更なし）"""
    PENDING = "pending"      # 検証待ち（独立ソース不足）
    VERIFIED = "verified"    # 検証済み（十分な裏付けあり）
    REJECTED = "rejected"    # 棄却（矛盾検出/危険パターン）
```

**CONTESTED を追加しない理由**:

1. **Thinking-Working分離の原則**: 「対立している」という解釈は高推論AIの責務
2. **エッジ情報で十分**: REFUTESエッジ + 信頼レベル情報があれば、高推論AIは判断可能
3. **シンプルさ**: 状態の増加は複雑性を増す

対立関係はエッジ（REFUTES）として記録し、そのメタデータ（source_trust_level, target_trust_level）を提供することで、高推論AIに判断材料を与える。

---

## 設計決定事項

### 決定1: MCPツール体制

**決定**: 11ツール体制を維持。

### 決定2: 対立関係の扱い

**決定**: Lyraは対立関係を**事実として記録**し、**解釈は高推論AIに委ねる**。

| 要素 | Lyraの責務 | 高推論AIの責務 |
|------|-----------|---------------|
| 対立の検出 | REFUTESエッジを作成 | - |
| 信頼レベル情報 | エッジに付与 | 参照して判断 |
| 「科学的論争か誤情報か」 | **判断しない** | 判断する |
| BLOCKEDの決定 | 危険パターン検出時のみ | 推奨可能 |

**ContradictionType enum は導入しない**:
- Lyraが「MISINFORMATION」「CONTESTED」とラベル付けすることは解釈行為
- エッジ情報（relation + trust_levels）があれば高推論AIは自ら判断可能

### 決定3: 信頼度が主、ドメイン分類は従

**決定**: **信頼度（confidence）がエビデンス評価の主軸**。ドメイン分類（TrustLevel）は副次的な参考情報に過ぎない。

**根拠**: 査読済み論文 ≠ 正しい情報

- 再現性危機: 心理学研究の60%以上が再現不可能
- 年間数千件の論文が撤回される
- arXiv等のプレプリントは査読なし
- ハゲタカジャーナル（predatory journals）の存在

**「ACADEMICドメインだから正しい」は技術的に誤り。クソ論文はいくらでもある。**

```
# 信頼度 = エビデンスの量と質で決まる（これが重要）
confidence = f(supporting_count, refuting_count, independent_sources)

# 単一論文 = 仮説
# 複数の独立ソースで裏付け = 蓋然性の高い主張
```

**設計への反映**:
- Nature論文でも裏付けなし → 低confidence
- 無名ブログでも5つの独立ソースで裏付け → 高confidence
- TrustLevelは「出自のヒント」であり、信頼性の保証ではない

### 決定4: Wikipedia

**状態**: ✅ 実装済み

`LOW` (0.40) として設定済み（`config/domains.yaml`）。

### 決定5: 引用追跡の関連性フィルタリング

**決定**: B+C hybrid、上位10件

| 要素 | 重み | 備考 |
|------|:----:|------|
| is_influential (S2) | 0.5 | S2のみ |
| embedding similarity | 0.3 | S2 + OpenAlex |
| NLI relevance | 0.2 | S2 + OpenAlex |

### 決定6: データソース戦略

**決定**: S2 + OpenAlex を完全実装、他はブラウザ補完

- アカデミッククエリかどうかは優先度の違い
- 非アカデミッククエリでも学術識別子発見時にAPI補完

### 決定7: ベイズ信頼度モデル

**決定**: 無情報事前分布 Beta(1, 1) + ベイズ更新による信頼度計算を採用

**設計原則**:
- 事前分布にドメイン分類を使用しない（純粋エビデンス主義）
- NLI confidence で重み付けしたベイズ更新
- confidence, uncertainty, controversy の3値を出力

**技術的根拠**:
- 数学的に厳密で再現可能
- 「分からない」状態（高uncertainty）を明示的に表現可能
- 論争状態（高controversy）を検出可能
- Lyraが取得する情報（NLI confidence, エッジ数）のみで計算可能

**実装タイミング**: Phase 4（引用追跡の後）

---

## 関連ドキュメント

- [REQUIREMENTS.md §4.4.1](REQUIREMENTS.md) - L6 Source Verification Flow
- [REQUIREMENTS.md §3.1.3](REQUIREMENTS.md) - 学術API統合戦略
- `src/filter/source_verification.py` - 現行実装
- `src/filter/evidence_graph.py` - エビデンスグラフ
- `src/search/academic_provider.py` - 学術API統合
- `src/research/pipeline.py` - 検索パイプライン

## 参考文献

- [NATO Admiralty Code](https://kravensecurity.com/source-reliability-and-information-credibility/)
- [Cornell Evidence Synthesis Guide](https://guides.library.cornell.edu/evidence-synthesis/intro)
- [Unifying Framework of Credibility Assessment](https://deepblue.lib.umich.edu/bitstream/handle/2027.42/106422/Hilligoss_Rieh_IPM2008%20Developing%20a%20unifying.pdf)
