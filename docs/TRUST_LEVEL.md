# Trust Level System Design

このドキュメントでは、Lyraの信頼レベル（Trust Level）システムの現状、課題、および改善提案を記述する。

## 目次

1. [現状の設計](#現状の設計)
2. [処理フロー（シーケンス図）](#処理フローシーケンス図)
3. [課題と問題点](#課題と問題点)
4. [関連する学術的フレームワーク](#関連する学術的フレームワーク)
5. [改善提案](#改善提案)
6. [実装ロードマップ](#実装ロードマップ)

---

## 現状の設計

### Trust Level 定義

ソースのドメインに対して以下の信頼レベルを割り当てる（`src/utils/domain_policy.py`）:

| レベル | 説明 | 信頼スコア |
|--------|------|-----------|
| `PRIMARY` | 標準化団体・レジストリ (iso.org, ietf.org) | 1.0 |
| `GOVERNMENT` | 政府機関 (.go.jp, .gov) | 0.95 |
| `ACADEMIC` | 学術機関 (arxiv.org, pubmed.gov) | 0.90 |
| `TRUSTED` | 信頼メディア・ナレッジベース (専門誌等) | 0.75 |
| `LOW` | L6検証により昇格（UNVERIFIED→LOW）、または Wikipedia | 0.40 |
| `UNVERIFIED` | 未知のドメイン（デフォルト） | 0.30 |
| `BLOCKED` | 除外（矛盾検出/危険パターン） | 0.0 |

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
     │               │ │  │ NLI評価 → SUPPORTS/REFUTES/NEUTRAL                  ││
     │               │ │  │ 矛盾検出 → MISINFORMATION / CONTESTED               ││
     │               │ │  │ claim_confidence計算                                ││
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
| **科学的論争** | PubMed論文AとBが対立する見解 | 片方がBLOCKED | 両方を"contested"として保持 |

**具体例**:
- 論文A (pubmed.gov): 「薬剤Xは有効」
- 論文B (pubmed.gov): 「薬剤Xに有意差なし」

両者ともACADEMIC信頼レベルであり、正当な科学的議論。
現状は後から発見された方が矛盾として処理されうる。

### 課題2: 信頼レベルと信頼度の混同

現在のシステムでは:
- **Trust Level** (ドメインレベル): iso.org → PRIMARY
- **Confidence** (主張レベル): evidence_graph.get_claim_confidence()

しかし矛盾検出時に **相手の信頼レベル** を考慮していない。

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

### 提案1: 矛盾の種類を簡素化

**設計原則**: 対立関係をフラットに提示し、判断はLyraではしない。

```python
class ContradictionType(Enum):
    MISINFORMATION = "misinformation"  # 低信頼源が高信頼源と矛盾 → 低信頼側をブロック
    CONTESTED = "contested"            # それ以外 → 両方保持、対立関係を明示
```

**処理方針**:
| 種類 | 判定条件 | 処理 |
|------|---------|------|
| MISINFORMATION | 信頼レベル差≥2、かつ低信頼側がACADEMIC未満 | 低信頼側をBLOCKED |
| CONTESTED | 両者ともACADEMIC以上、または信頼レベル差<2 | 両方を "contested" として保持 |

#### 1.1 矛盾分類ロジック

```python
# 信頼レベルの序列（低い→高い）
TRUST_ORDER = [
    TrustLevel.BLOCKED,      # 0
    TrustLevel.UNVERIFIED,   # 1
    TrustLevel.LOW,          # 2
    TrustLevel.TRUSTED,      # 3
    TrustLevel.ACADEMIC,     # 4
    TrustLevel.GOVERNMENT,   # 5
    TrustLevel.PRIMARY,      # 6
]

# 「高信頼」の閾値（ACADEMIC以上）
# ACADEMIC以上同士の対立は両方の視点を保持すべき
HIGH_TRUST_THRESHOLD = 4  # ACADEMIC, GOVERNMENT, PRIMARY

def classify_contradiction(
    claim1_trust: TrustLevel,
    claim2_trust: TrustLevel,
) -> ContradictionType:
    """矛盾の種類を判定する

    設計原則: 対立関係をフラットに提示し、判断はLyraではしない。
    時間情報（どちらが新しいか）はメタデータとして提供するが、
    自動的に「古い方を無効」とはしない。
    """
    idx1 = TRUST_ORDER.index(claim1_trust)
    idx2 = TRUST_ORDER.index(claim2_trust)

    both_high_trust = idx1 >= HIGH_TRUST_THRESHOLD and idx2 >= HIGH_TRUST_THRESHOLD
    trust_gap = abs(idx1 - idx2)

    # Case 1: 両者ともACADEMIC以上 → 両方の視点を保持
    if both_high_trust:
        return ContradictionType.CONTESTED

    # Case 2: 信頼レベルに大きな差（2段階以上）→ 誤情報の可能性
    if trust_gap >= 2:
        return ContradictionType.MISINFORMATION

    # Case 3: それ以外 → 両方を保持
    return ContradictionType.CONTESTED
```

#### 1.2 矛盾種類別の処理

```python
def handle_contradiction(
    contradiction_type: ContradictionType,
    claim1: Claim,
    claim2: Claim,
) -> tuple[VerificationStatus, VerificationStatus]:
    """矛盾種類に応じた処理を決定

    原則: 誤情報以外は両方の視点を保持する
    """
    match contradiction_type:
        case ContradictionType.MISINFORMATION:
            # 低信頼側をブロック、高信頼側は維持
            if claim1.trust_level_idx < claim2.trust_level_idx:
                return (VerificationStatus.REJECTED, VerificationStatus.VERIFIED)
            else:
                return (VerificationStatus.VERIFIED, VerificationStatus.REJECTED)

        case ContradictionType.CONTESTED:
            # 両方を "contested" として保持
            return (VerificationStatus.CONTESTED, VerificationStatus.CONTESTED)
```

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

**決定**: Wikipedia は `LOW` (0.40) として扱う。

**理由**:
- 誰でも編集可能であり、一時的に誤情報が含まれる可能性
- 個別記事ごとに品質が大きく異なる
- 信頼できる内容であれば、他のソースからも裏付けが得られる（エッジが増える）

**実装**: `config/domains.yaml` を更新

```yaml
- domain: "wikipedia.org"
  trust_level: "low"  # trusted → low に変更
  qps: 0.5
```

出典追跡機能は実装しない（通常ドメインとして扱う）。

---

## 実装ロードマップ

### Phase 1: 透明性の向上（低リスク・高価値）

目的: 判断根拠の可視化と監査可能性の確保

1. [ ] `get_status` への `blocked_domains` 情報追加
2. [ ] ブロック理由のログ強化（`cause_id` 連携）
3. [ ] エビデンスグラフに矛盾関係を明示的に保存
4. [ ] 不採用主張（`not_adopted`）のグラフ保持

### Phase 2: 科学的論争の区別（中リスク・高価値）【優先】

目的: 誤情報と正当な科学的論争を区別

**この Phase を先に実装する根拠**:
Phase 3（引用追跡）で追加される論文が、現行の問題あるロジック（`refuting_count > 0` で即 BLOCKED）で処理されることを防ぐ。矛盾分類ロジックを先に整備することで、引用追跡で発見された対立関係が適切に処理される。

1. [ ] `ContradictionType` enum 追加（2種: MISINFORMATION, CONTESTED）
2. [ ] `classify_contradiction()` 関数の実装
3. [ ] `_determine_verification_outcome` の改修
4. [ ] HIGH_TRUST_THRESHOLD = 4 (ACADEMIC以上) の適用

**テストケース**:
```python
def test_academic_vs_academic_is_contested():
    """ACADEMIC同士の対立 → CONTESTED、両方保持"""

def test_unverified_vs_academic_is_misinformation():
    """UNVERIFIED vs ACADEMIC → MISINFORMATION、UNVERIFIED側ブロック"""
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

### Phase 4: ユーザー制御（中リスク・中価値）

目的: ブロック状態からの復活手段を提供

1. [ ] `get_status` 応答に `can_restore` フラグを追加
2. [ ] `config/domains.yaml` に `user_overrides` セクション追加
3. [ ] 設定ファイルのhot-reload対応確認

---

## VerificationStatus の拡張

現行の `VerificationStatus` を拡張:

```python
class VerificationStatus(str, Enum):
    """検証ステータス（拡張版）"""

    # 既存
    PENDING = "pending"      # 検証待ち（独立ソース不足）
    VERIFIED = "verified"    # 検証済み（十分な裏付けあり）
    REJECTED = "rejected"    # 棄却（矛盾検出/危険パターン）

    # 新規追加
    CONTESTED = "contested"  # 対立関係にある（両方保持）
```

**注**: `SUPERSEDED` は削除。時間情報はメタデータとして提供し、判断はLyraではしない。

---

## 設計決定事項

### 決定1: MCPツール体制

**決定**: 11ツール体制を維持。

### 決定2: HIGH_TRUST_THRESHOLD

**決定**: 4 (ACADEMIC以上)

| インデックス | レベル | 高信頼 |
|:-----------:|--------|:-----:|
| 0 | BLOCKED | - |
| 1 | UNVERIFIED | - |
| 2 | LOW | - |
| 3 | TRUSTED | - |
| 4 | ACADEMIC | ✓ |
| 5 | GOVERNMENT | ✓ |
| 6 | PRIMARY | ✓ |

### 決定3: ContradictionType

**決定**: 2種に簡素化

- `MISINFORMATION`: 低信頼源が高信頼源と矛盾 → 低信頼側ブロック
- `CONTESTED`: それ以外 → 両方保持、対立関係を明示

**SUPERSEDED, METHODOLOGY_DIFFERENCE を削除する根拠**:

1. **自動判定の困難性**: 「古い研究が覆された」かどうかを出版年だけで判断できない
   - 古い論文が正しく、新しい論文が誤っている場合がある
   - メタ分析が「覆す」のか「補足する」のかも曖昧

2. **責任分離の原則**: Lyraはエビデンスを収集・整理するツールであり、科学的判断を下すツールではない
   - Lyra: 「論文Aと論文Bは対立関係にある」（CONTESTED） + メタデータ提供
   - 高推論AI/操作者: メタデータ（出版年、引用数、方法論）を見て判断

時間情報や方法論の差異はメタデータとして提供し、判断は操作者である高推論AIに委ねる。

### 決定4: Wikipedia

**決定**: `LOW` (0.40)

TRUSTEDから降格。出典追跡機能は実装しない。

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
