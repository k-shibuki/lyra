# Trust Level System Design

このドキュメントでは、Lyraの信頼レベル（Trust Level）システムの現状、課題、および改善提案を記述する。

## 目次

1. [現状の設計](#現状の設計)
2. [課題と問題点](#課題と問題点)
3. [関連する学術的フレームワーク](#関連する学術的フレームワーク)
4. [改善提案](#改善提案)
5. [実装ロードマップ](#実装ロードマップ)

---

## 現状の設計

### Trust Level 定義

ソースのドメインに対して以下の信頼レベルを割り当てる（`src/utils/domain_policy.py`）:

| レベル | 説明 | 信頼スコア |
|--------|------|-----------|
| `PRIMARY` | 標準化団体・レジストリ (iso.org, ietf.org) | 1.0 |
| `GOVERNMENT` | 政府機関 (.go.jp, .gov) | 0.95 |
| `ACADEMIC` | 学術機関 (arxiv.org, pubmed.gov) | 0.90 |
| `TRUSTED` | 信頼メディア・ナレッジベース (専門誌、百科事典等) | 0.75 |
| `LOW` | L6検証により昇格（UNVERIFIED→LOW） | 0.40 |
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

### 課題3: ユーザー制御の欠如

- ブロックされたドメインをユーザーが確認・復元できない
- エビデンスグラフ上でブロック理由が可視化されていない
- 手動での信頼レベル上書きができない

### 課題4: 透明性の不足

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

### GRADE Framework

医学的エビデンスの確実性評価フレームワーク。

- **Certainty of Evidence**: 効果推定値への信頼度
- **Inconsistency（非一貫性）**: 研究間の結果のばらつき
- 矛盾する結果は **ダウングレード要因** だが、即座に除外ではない

**参考**: [CDC ACIP GRADE Handbook](https://www.cdc.gov/acip-grade-handbook/hcp/chapter-7-grade-criteria-determining-certainty-of-evidence/index.html)

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

### 提案1: 矛盾の種類を区別する

```python
class ContradictionType(Enum):
    MISINFORMATION = "misinformation"      # 低信頼源が高信頼源と矛盾
    SCIENTIFIC_DEBATE = "scientific_debate" # 同等信頼源間の対立
    SUPERSEDED = "superseded"              # 古い情報が新情報で更新
    METHODOLOGY_DIFFERENCE = "methodology" # 方法論の差異による異なる結論
```

**処理方針**:
| 種類 | 判定条件 | 処理 |
|------|---------|------|
| MISINFORMATION | UNVERIFIED/LOW が TRUSTED+ と矛盾 | 低信頼側をBLOCKED |
| SCIENTIFIC_DEBATE | ACADEMIC 同士が矛盾 | 両方を "contested" として保持 |
| SUPERSEDED | 古い情報と新しい情報が矛盾 | 古い方を "superseded" マーク |
| METHODOLOGY_DIFFERENCE | メタデータから判別 | 両方を保持、注釈付与 |

#### 1.1 矛盾分類ロジックの詳細

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

# 「高信頼」の閾値（TRUSTED以上）
# TRUSTEDだからこそ別の視点として両方見ることが必要
HIGH_TRUST_THRESHOLD = 3  # TRUSTED, ACADEMIC, GOVERNMENT, PRIMARY

# SUPERSEDED判定の時間差閾値（デフォルト: 365日）
# ドメインポリシーで上書き可能
DEFAULT_SUPERSEDED_DAYS = 365

def classify_contradiction(
    claim1_trust: TrustLevel,
    claim2_trust: TrustLevel,
    claim1_date: datetime | None,
    claim2_date: datetime | None,
    claim1_domain: str | None = None,
    claim2_domain: str | None = None,
) -> ContradictionType:
    """矛盾の種類を判定する

    Args:
        claim1_trust: 主張1のソース信頼レベル
        claim2_trust: 主張2のソース信頼レベル
        claim1_date: 主張1の発行/取得日時
        claim2_date: 主張2の発行/取得日時
        claim1_domain: 主張1のドメイン（ポリシー参照用）
        claim2_domain: 主張2のドメイン（ポリシー参照用）

    Returns:
        矛盾の種類
    """
    idx1 = TRUST_ORDER.index(claim1_trust)
    idx2 = TRUST_ORDER.index(claim2_trust)

    both_high_trust = idx1 >= HIGH_TRUST_THRESHOLD and idx2 >= HIGH_TRUST_THRESHOLD
    trust_gap = abs(idx1 - idx2)

    # Case 1: 両者とも高信頼（TRUSTED以上）→ 両方の視点を保持
    if both_high_trust:
        # 時間差が大きい場合は情報更新の可能性
        if claim1_date and claim2_date:
            # ドメインポリシーから閾値を取得（なければデフォルト）
            superseded_days = get_superseded_threshold(claim1_domain, claim2_domain)
            time_diff_days = abs((claim1_date - claim2_date).days)
            if time_diff_days > superseded_days:
                return ContradictionType.SUPERSEDED
        return ContradictionType.SCIENTIFIC_DEBATE

    # Case 2: 信頼レベルに大きな差（2段階以上）→ 誤情報の可能性
    if trust_gap >= 2:
        return ContradictionType.MISINFORMATION

    # Case 3: 同程度の低〜中信頼 → 方法論の差異
    # 両方を保持し、異なる視点として扱う（PENDINGではない）
    return ContradictionType.METHODOLOGY_DIFFERENCE


def get_superseded_threshold(domain1: str | None, domain2: str | None) -> int:
    """SUPERSEDED判定の時間差閾値を取得

    ドメインポリシーで上書き可能。分野によって適切な閾値が異なる:
    - 医学/薬学: 730日（2年） - ガイドライン更新サイクルが長い
    - IT/技術: 180日（6ヶ月） - 技術変化が速い
    - 法律/規制: 365日（1年） - 法改正サイクル
    - デフォルト: 365日
    """
    # ドメインポリシーから取得（実装時に詳細化）
    # config/domains.yaml の superseded_threshold_days を参照
    return DEFAULT_SUPERSEDED_DAYS
```

#### 1.2 矛盾種類別の処理

**設計原則**: 異なる意見を包摂したエビデンスグラフを構築する。矛盾は即座に排除するのではなく、両方の視点を保持し、Cursor AIとユーザーが判断できるようにする。

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
            # 唯一の「片方を排除」ケース
            if claim1.trust_level_idx < claim2.trust_level_idx:
                return (VerificationStatus.REJECTED, VerificationStatus.VERIFIED)
            else:
                return (VerificationStatus.VERIFIED, VerificationStatus.REJECTED)

        case ContradictionType.SCIENTIFIC_DEBATE:
            # 両方を "contested" として保持
            # 高信頼同士の論争は両方の視点が必要
            return (VerificationStatus.CONTESTED, VerificationStatus.CONTESTED)

        case ContradictionType.SUPERSEDED:
            # 古い方を "superseded" マーク、新しい方は維持
            # ただし古い方も参照可能な状態で保持（削除しない）
            if claim1.date < claim2.date:
                return (VerificationStatus.SUPERSEDED, VerificationStatus.VERIFIED)
            else:
                return (VerificationStatus.VERIFIED, VerificationStatus.SUPERSEDED)

        case ContradictionType.METHODOLOGY_DIFFERENCE:
            # 両方を "contested" として保持（PENDINGではない）
            # 低〜中信頼でも異なる視点として価値がある
            return (VerificationStatus.CONTESTED, VerificationStatus.CONTESTED)
```

**重要**: `METHODOLOGY_DIFFERENCE` も `CONTESTED` として両方保持する。`PENDING` は「検証待ち」を意味するが、方法論の差異は「検証が足りない」のではなく「異なるアプローチ」を表すため、両方の視点を明示的に保持する。

### 提案2: 信頼度スコアの導入

**設計原則**: ドメインの信頼レベルは個別主張の信頼度に**優先しない**。ドメインは参考情報に過ぎない。

> **例**: arXivは `ACADEMIC` だが未査読論文が含まれる。ドメインが高信頼でも、個別主張は独立したエビデンスで検証すべき。

```python
@dataclass
class ClaimAssessment:
    claim_id: str

    # ソースレベル（ドメイン単位）- 参考情報
    source_trust_level: TrustLevel        # ドメインの信頼レベル (PRIMARY〜BLOCKED)
    # 注意: source_trust_level は claim_confidence の「初期値のヒント」に過ぎない

    # 主張レベル（個別の主張単位）- これが本質
    claim_confidence: float               # 主張の確実性 (0.0-1.0)
    verification_status: VerificationStatus  # verified/pending/rejected/contested/superseded

    # 矛盾状態（提案1連携）
    contradiction_status: ContradictionStatus  # none/contested/refuted
    contradiction_type: ContradictionType | None  # 矛盾の種類（矛盾がある場合）

    # 復活情報（提案4連携）
    recovery_info: ClaimRecoveryInfo | None  # 不採用の場合の復活条件
```

**重要**: `source_trust_level` はあくまで「このドメインは通常信頼できる」という**ヒント**。最終的な `claim_confidence` は独立エビデンスの数と質で決まる。

#### 2.1 claim_confidence の計算

`claim_confidence` は**独立エビデンスの数と質**で算出する。ドメイン信頼レベルは参考情報:

```python
def calculate_claim_confidence(
    claim_id: str,
    evidence_graph: EvidenceGraph,
) -> float:
    """主張の確実性スコアを計算

    設計原則: 独立エビデンスの数と質が最重要。ドメインは参考程度。

    Returns:
        0.0〜1.0のスコア（1.0が最も確実）
    """
    evidence = evidence_graph.get_all_evidence(claim_id)

    # 基礎スコア: 独立ソース数に基づく（最重要）
    independent_sources = count_independent_sources(evidence["supports"])
    base_score = min(0.8, independent_sources * 0.27)  # 3件の独立ソースで0.8

    # 矛盾による減点
    refute_count = len(evidence["refutes"])
    contradiction_penalty = min(0.5, refute_count * 0.15)

    # ドメイン信頼レベルによる加点（参考程度、最大0.2）
    # arXivのような未査読サイトも含まれるため、過度に重視しない
    high_trust_count = sum(
        1 for e in evidence["supports"]
        if e.get("trust_level") in ("academic", "government", "primary")
    )
    trust_hint = min(0.2, high_trust_count * 0.07)  # 最大0.2の加点

    # 最終スコア: base(0.8) + trust_hint(0.2) = 1.0
    confidence = base_score + trust_hint - contradiction_penalty
    return max(0.0, min(1.0, confidence))
```

> **注意**: `trust_hint` は最大0.2。独立ソース3件が必要条件であり、ドメインはあくまで補足。

### 提案3: ユーザー制御インターフェース

#### 3.1 ブロック状態の可視化

既存MCPツール `get_status` を拡張し、`blocked_domains` セクションを追加:

```python
# get_status の応答に追加
{
    ...
    "blocked_domains": [
        {
            "domain": "example.com",
            "blocked_at": "2024-01-15T10:30:00Z",
            "reason": "Contradiction with pubmed.gov (claim_id: abc123)",
            "contradicting_claims": ["claim:abc123", "claim:def456"],
            "original_trust_level": "UNVERIFIED",
            "can_restore": true,
            "restore_via": "config/domains.yaml user_overrides"
        }
    ]
}
```

#### 3.2 手動復元・上書き機能

**設計決定**: MCPツールは11ツール体制を維持。手動復元は**設定ファイル編集**で対応。

> **理由**: 信頼レベルの上書きは頻繁に行う操作ではなく、慎重な判断が必要。設定ファイル編集＋git履歴での監査が適切。

#### 3.3 信頼レベルのオーバーライド（設定ファイル）

`config/domains.yaml` に `user_overrides` セクションを追加:

```yaml
user_overrides:
  # ブロックされたドメインの復元
  - domain: "blocked-but-valid.org"
    trust_level: "low"
    reason: "Manual review completed - false positive"
    added_at: "2024-01-15"

  # 信頼レベルの上書き
  - domain: "controversial-but-valid.org"
    trust_level: "trusted"
    reason: "Manually verified as legitimate academic source"
    added_at: "2024-01-15"

# 分野別のSUPERSEDED閾値
superseded_thresholds:
  - domain_pattern: "*.nih.gov"
    days: 730  # 医学系は2年
  - domain_pattern: "*.github.io"
    days: 180  # 技術系は6ヶ月

# Wikipediaは出典追跡モード（ソースとしてカウントしない）
wikipedia_mode: "follow_citations"  # ソースとしてカウントせず、出典を追跡
```

**運用フロー**:
1. `get_status` で `blocked_domains` を確認
2. 誤ブロックと判断したら `config/domains.yaml` を編集
3. Lyraはhot-reloadをサポート（再起動不要）
4. 監査ログはgit履歴で追跡

**利点**:
- MCPツール11体制を維持（認知負荷を増やさない）
- 設定変更の履歴がgitで追跡可能（監査性）
- 慎重な判断を促す（ワンクリック復元より安全）

#### 3.4 Wikipediaの扱い

> **設計決定**: Wikipediaは**エビデンスソースとしてカウントしない**。

**理由**:
- 誰でも編集可能であり、一時的に誤情報が含まれる可能性がある
- 個別記事ごとに品質が大きく異なる
- Wikipediaの価値は「出典へのポインタ」にある

**実装方針**:

1. **ソースとしてカウントしない**
   - Wikipedia由来の主張は `claim_confidence` 計算時に独立ソースとしてカウントしない
   - エビデンスグラフには記録するが、`is_wikipedia: true` フラグを付与

2. **出典追跡を行う（中レベル実装）**
   - Wikipedia記事の参考文献セクションからURLを抽出
   - 抽出した出典URLを追加の検索対象として自動追加
   - 出典が高信頼ソースであれば、そちらをエビデンスとして採用

```python
def process_wikipedia_page(page: Page, task_id: str) -> list[str]:
    """Wikipedia記事から出典URLを抽出し、追加探索対象として返す

    実装レベル: 中（URL抽出＋検索対象追加）
    - 最小: URL抽出のみ
    - 中: URL抽出＋検索対象に自動追加 ← 採用
    - 最大: 脚注番号と本文の対応も追跡（工数大）

    Returns:
        追跡すべき出典URLのリスト
    """
    # 参考文献セクションからURLを抽出
    citations = extract_wikipedia_citations(page.content)

    # 高優先度の出典（学術論文、政府サイト等）をフィルタ
    priority_sources = [
        url for url in citations
        if is_likely_primary_source(url)
    ]

    # 検索対象キューに追加
    add_to_fetch_queue(task_id, priority_sources, priority="high")

    return priority_sources
```

3. **表示時の注記**
   - Wikipedia由来の主張には `source_type: "wikipedia_derived"` を付与
   - 出典追跡が完了した場合は元ソースのURLを明示

### 提案4: エビデンスグラフ上での可視化と復活機会の保証

#### 4.1 矛盾関係の明示

```
┌──────────────┐         REFUTES         ┌──────────────┐
│ Claim A      │◄────────────────────────│ Claim B      │
│ "Drug X works"│                         │ "Drug X fails"│
│ (pubmed.gov) │                         │ (pubmed.gov) │
│ trust: ACAD  │                         │ trust: ACAD  │
│ status: ──── │                         │ status: ──── │
│  contested   │                         │  contested   │
└──────────────┘                         └──────────────┘
        │                                        │
        └────────────────┬───────────────────────┘
                         ▼
              ┌─────────────────────┐
              │ Contradiction Node   │
              │ type: SCIENTIFIC_DEBATE│
              │ resolution: pending  │
              └─────────────────────┘
```

#### 4.2 不採用・ブロック状態の可視化

採用されなかった（REJECTED）、またはブロックされた（BLOCKED）主張も、エビデンスグラフに**明示的に保持**する。これにより：

1. **判断根拠の透明性**: なぜ採用されなかったかをCursor AIが把握できる
2. **復活の機会**: 新しいエビデンスで判断が覆る可能性を常に保持
3. **監査可能性**: 調査プロセス全体の追跡が可能

```
┌──────────────────────────────────────────────────────────┐
│                    Evidence Graph                         │
├──────────────────────────────────────────────────────────┤
│  [ADOPTED]                                                │
│  ┌────────────┐   ┌────────────┐   ┌────────────┐        │
│  │ Claim A    │   │ Claim B    │   │ Claim C    │        │
│  │ verified   │   │ contested  │   │ verified   │        │
│  └────────────┘   └────────────┘   └────────────┘        │
│                                                           │
│  [NOT ADOPTED - Visible for Review]                       │
│  ┌────────────┐   ┌────────────┐   ┌────────────┐        │
│  │ Claim D    │   │ Claim E    │   │ Claim F    │        │
│  │ rejected   │   │ blocked    │   │ pending    │        │
│  │ reason:    │   │ reason:    │   │ reason:    │        │
│  │ contradict │   │ misinfo    │   │ unverified │        │
│  │ recoverable│   │ recoverable│   │ needs_more │        │
│  └────────────┘   └────────────┘   └────────────┘        │
└──────────────────────────────────────────────────────────┘
```

#### 4.3 復活条件の明示

不採用・ブロック状態の主張には、**復活条件**を明示的に付与する：

| 状態 | 復活条件 | 復活方法 |
|------|---------|---------|
| `rejected` (矛盾検出) | 同一task_idで再調査時に新情報が発見された場合 | 再調査 |
| `blocked` (誤情報判定) | `config/domains.yaml` の `user_overrides` で復元 | 設定ファイル編集 |
| `pending` (未検証) | 追加の独立ソースで裏付け | 自動昇格 |
| `superseded` (情報更新) | 同一task_idで再調査時に状況が変化した場合 | 再調査 |

##### 4.3.1 復活メカニズム

**設計原則**: 自動バックグラウンド処理は行わない。復活は以下の2つの方法に限定：

1. **同一task_idでの再調査**
   - ユーザーが同じtask_idで `search` を再実行
   - 新しいエビデンスが発見されれば、過去の判定を再評価
   - 矛盾元が更新/撤回されていれば、rejected主張が復活候補に

2. **設定ファイルでの手動復元**
   - `config/domains.yaml` の `user_overrides` を編集
   - Lyraはhot-reloadをサポートしており、再起動不要
   - 監査ログは設定ファイルのgit履歴で追跡

```python
@dataclass
class ClaimRecoveryInfo:
    """不採用主張の復活情報"""
    claim_id: str
    current_status: VerificationStatus
    rejection_reason: str
    rejected_at: datetime

    # 復活条件
    recovery_conditions: list[str]

    # 復活のための追加情報
    contradicting_claims: list[str]  # これらが無効化されれば復活
    required_independent_sources: int  # これだけのソースがあれば復活
```

#### 4.4 MCPツール拡張

`get_status` および `get_materials` の返却値に不採用情報を追加。

**CONTESTED主張の表示形式**: シンプルに両方を並列で返す。矛盾の解釈・判断はCursor AI等のクライアントに委ねる。

```python
{
    "claims": [
        # 通常の主張
        {"id": "c1", "text": "...", "status": "verified", "claim_confidence": 0.85},
        # CONTESTED: 両方を並列で返し、contradicts で相互参照
        {"id": "c2", "text": "Drug X is effective", "status": "contested",
         "claim_confidence": 0.7, "contradicts": ["c3"]},
        {"id": "c3", "text": "Drug X shows no effect", "status": "contested",
         "claim_confidence": 0.7, "contradicts": ["c2"]}
    ],
    "not_adopted": [
        {
            "claim_id": "claim:xyz",
            "text": "不採用となった主張テキスト",
            "source_domain": "suspicious-blog.com",
            "source_trust_level": "UNVERIFIED",
            "status": "blocked",
            "reason": "Contradiction with pubmed.gov (claim:abc)",
            "rejected_at": "2024-01-15T10:30:00Z",
            "recovery": {
                "is_recoverable": true,
                "conditions": [
                    "Manual review via restore_domain",
                    "Or: 2 additional independent sources supporting this claim"
                ],
                "blocking_claims": ["claim:abc"]
            }
        }
    ],
    "blocked_domains": [
        {
            "domain": "suspicious-blog.com",
            "blocked_at": "2024-01-15T10:30:00Z",
            "reason": "High rejection rate (40%)",
            "affected_claims": ["claim:xyz", "claim:uvw"],
            "can_restore": true,
            "restore_via": "resolve_auth or manual override"
        }
    ]
}
```

### ~~提案5: GRADE準拠のエビデンス品質評価~~ [リジェクト]

> **リジェクト理由**: Lyraは学術論文に関してはアブストラクトのみを扱う設計（§1.0「学術論文はAbstract Only」）であり、フルテキストを前提とするGRADEフレームワークとは相性が悪い。GRADEの詳細評価（indirectness, imprecision, publication bias等）にはフルテキストの解析が必要であり、アブストラクト限定では適切な評価ができない。
>
> 代替として、提案2の `ClaimAssessment` における `claim_confidence` スコアで簡易的な品質指標を提供する。

---

## 実装ロードマップ

### Phase 1: 透明性の向上（低リスク・高価値）【最優先】

目的: 判断根拠の可視化と監査可能性の確保

1. [ ] `get_status` への `blocked_domains` 情報追加（既存MCPツール拡張）
2. [ ] ブロック理由のログ強化（`cause_id` 連携）
3. [ ] エビデンスグラフに矛盾関係を明示的に保存
4. [ ] 不採用主張（`not_adopted`）のグラフ保持

**成果物**:
- `get_status` 応答に `blocked_domains`, `not_adopted` セクション追加
- 構造化ログに rejection 理由と cause_id を記録

### Phase 2: 科学的論争の区別（中リスク・高価値）

目的: 誤情報と正当な科学的論争を区別し、不当なブロックを防止

1. [ ] `ContradictionType` enum 追加
2. [ ] `classify_contradiction()` 関数の実装
   - 入力: 両主張の信頼レベル、日付、ドメイン
   - 出力: MISINFORMATION | SCIENTIFIC_DEBATE | SUPERSEDED | METHODOLOGY_DIFFERENCE
3. [ ] `_determine_verification_outcome` の改修
   - ACADEMIC同士の矛盾 → `contested` として両方保持
   - UNVERIFIED vs ACADEMIC → UNVERIFIED側のみブロック
4. [ ] 復活条件（`ClaimRecoveryInfo`）の実装
5. [ ] テストケースの先行実装

**テストケース例**:
```python
def test_academic_vs_academic_is_scientific_debate():
    """PubMed論文AとBが対立 → SCIENTIFIC_DEBATE、両方保持"""

def test_unverified_vs_academic_is_misinformation():
    """怪しいブログがPubMed論文と矛盾 → MISINFORMATION、ブログ側ブロック"""

def test_contested_claims_not_blocked():
    """SCIENTIFIC_DEBATEの両主張がBLOCKEDにならないことを検証"""

def test_recovery_conditions_populated():
    """ブロック時に復活条件が設定されることを検証"""
```

### Phase 3: ユーザー制御（中リスク・中価値）

目的: ブロック状態からの復活手段を提供

1. [ ] `get_status` 応答に `can_restore` フラグと復活条件を追加
2. [ ] `config/domains.yaml` に `user_overrides` セクション追加
   ```yaml
   user_overrides:
     - domain: "example.org"
       trust_level: "trusted"
       reason: "Manually verified"
       added_at: "2024-01-15"
   superseded_thresholds:
     - domain_pattern: "*.nih.gov"
       days: 730  # 医学系は2年
   wikipedia_mode: "follow_citations"
   ```
3. [ ] 設定ファイルのhot-reload対応確認
4. [ ] Wikipedia出典追跡機能の実装

**設計決定**:
- MCPツールは**11ツール体制を維持**
- 手動復元は `config/domains.yaml` 編集で対応
- 監査ログはgit履歴で追跡（設定ファイル変更のコミット）

### Phase 4: [削除] ~~GRADE準拠~~

> リジェクト済み。提案5のリジェクト理由を参照。

---

## VerificationStatus の拡張

現行の `VerificationStatus` を拡張し、矛盾状態を表現可能にする:

```python
class VerificationStatus(str, Enum):
    """検証ステータス（拡張版）"""

    # 既存
    PENDING = "pending"      # 検証待ち（独立ソース不足）
    VERIFIED = "verified"    # 検証済み（十分な裏付けあり）
    REJECTED = "rejected"    # 棄却（矛盾検出/危険パターン）

    # 新規追加
    CONTESTED = "contested"  # 論争中（SCIENTIFIC_DEBATEの両主張）
    SUPERSEDED = "superseded"  # 更新済み（古い情報が新情報で置換）
```

**状態遷移図**:

```
                    ┌──────────────┐
                    │   PENDING    │
                    └──────┬───────┘
                           │
            ┌──────────────┼──────────────┐
            ▼              ▼              ▼
    ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
    │   VERIFIED   │ │   REJECTED   │ │  CONTESTED   │
    └──────────────┘ └──────────────┘ └──────────────┘
            │              │              │
            │              ▼              │
            │      ┌──────────────┐       │
            │      │   BLOCKED    │       │
            │      │   (domain)   │       │
            │      └──────────────┘       │
            │              │              │
            ▼              ▼              ▼
    ┌─────────────────────────────────────────────┐
    │              SUPERSEDED                      │
    │   (新しい情報により置き換えられた場合)         │
    └─────────────────────────────────────────────┘
```

---

## 5. 設計決定事項

### 5.1 MCPツール体制

**決定**: 11ツール体制を維持。手動復元ツールは追加しない。

**理由**: 手動復元が不要なようにツールを作り込む方が正しい設計。
- 誤ブロックを最小化する分類ロジック
- 再調査による自然な復活メカニズム
- 既存の `config/domains.yaml` での永続的オーバーライド

### 5.2 claim_confidence と domain 加算

**決定**: domain 加算は最大 0.2 まで。

| スコア要素 | 最大値 | 計算方法 |
|-----------|--------|----------|
| 独立エビデンス | 0.8 | `min(0.8, count * 0.27)` |
| ドメイン加算 | 0.2 | `min(0.2, high_trust_count * 0.07)` |
| 合計 | 1.0 | - |

### 5.3 Wikipedia 出典追跡

**決定**: 中レベル実装（URL抽出＋検索対象追加）。

- 最小: URL抽出のみ（将来の参照用）
- **中**: URL抽出＋検索対象に自動追加 ← 採用
- 最大: 脚注番号と本文の対応も追跡（工数大）

### 5.4 CONTESTED 状態の表示

**決定**: 案A採用（両方を並列で返す）。

矛盾の解釈・判断は Cursor AI 等のクライアントに委ねる。
`contradicts` フィールドで相互参照を明示。

### 5.5 SUPERSEDED 主張の再評価

**決定**: 明示的な再評価フラグは不要。

**ユーザーの運用**:
1. しばらく期間をおいてから再調査
2. 別のクエリを指定して再調査
3. どちらも同じ `task_id` を使えばグラフが更新される

```python
# 例: 医療ガイドラインの再調査
# 2024年1月
search(task_id="medical-001", query="hypertension treatment")
# 2025年6月（別クエリ、同じtask_id）
search(task_id="medical-001", query="hypertension guidelines 2025")
# → 以前の主張が SUPERSEDED かどうか自動で再評価
```

---

## REQUIREMENTS.md への更新提案

本ドキュメントの改善を反映するため、以下のセクションを更新する必要がある:

### §4.4.1 L6 への追加

```markdown
**L6.1: 矛盾の種類判別**

矛盾検出時に、両者の信頼レベルを比較し、矛盾の種類を判別する:

| 種類 | 判定条件 | 処理 |
|------|---------|------|
| MISINFORMATION | 信頼レベル差≥2 | 低信頼側をBLOCKED |
| SCIENTIFIC_DEBATE | 両者ともTRUSTED以上 | 両方を "contested" として保持 |
| SUPERSEDED | 時間差1年以上（ドメインポリシーで設定可能）、両者とも高信頼 | 古い方を "superseded" マーク |
| METHODOLOGY_DIFFERENCE | 上記に該当しない | 両方を "contested" として保持 |

**設計原則**: 異なる意見を包摂したエビデンスグラフを構築する。誤情報以外は両方の視点を保持し、Cursor AIとユーザーが判断できるようにする。

**L6.2: 不採用主張の可視化**

REJECTED/BLOCKED となった主張もエビデンスグラフに保持し、復活条件を明示する。
これにより、判断根拠の透明性と監査可能性を確保する。

**L6.3: 復活メカニズム**

- 再調査による復活: 同一task_idで再調査時に新エビデンスが発見されれば再評価
- 手動復活: `config/domains.yaml` の `user_overrides` 編集（git履歴で監査）
```

### §7 への追加（受け入れ基準）

```markdown
- 矛盾分類の精度:
  - SCIENTIFIC_DEBATEの誤判定率（TRUSTED以上同士の矛盾を誤ってMISINFORMATIONと判定）≤5%
  - 不採用主張の復活条件表示率≥95%
- 復活機能:
  - 再調査による自然復活率（手動介入不要）≥95%
  - config/domains.yaml による永続オーバーライドの適用成功率≥99%
- 異なる視点の包摂:
  - CONTESTED状態の主張が適切に両方保持される率≥99%
  - METHODOLOGY_DIFFERENCEがPENDINGに誤分類される率≤1%
```

### Wikipediaの扱い（§3.3 信頼度スコアリング）

```markdown
- Wikipedia (wikipedia.org) は **エビデンスソースとしてカウントしない**
  - 理由: 誰でも編集可能、記事ごとに品質が異なる
  - Wikipediaの価値は「出典へのポインタ」にある
  - 出典追跡モード: 参考文献セクションからURLを抽出し、元ソースを検索対象に追加
  - config/domains.yaml: `wikipedia_mode: "follow_citations"`
```

---

## 関連ドキュメント

- [REQUIREMENTS.md §4.4.1](REQUIREMENTS.md) - L6 Source Verification Flow
- [REQUIREMENTS.md §4.5](REQUIREMENTS.md) - 品質保証と評価指標
- [REQUIREMENTS.md §3.2.1](REQUIREMENTS.md) - MCPツールIF仕様
- `src/filter/source_verification.py` - 現行実装
- `src/filter/evidence_graph.py` - エビデンスグラフ
- `src/mcp/response_meta.py` - MCP応答メタデータ

## 参考文献

- [NATO Admiralty Code](https://kravensecurity.com/source-reliability-and-information-credibility/)
- ~~[GRADE Handbook](https://gradepro.org/handbook)~~ (リジェクト - アブストラクト限定と非互換)
- [Cornell Evidence Synthesis Guide](https://guides.library.cornell.edu/evidence-synthesis/intro)
- ~~[CDC ACIP GRADE Handbook](https://www.cdc.gov/acip-grade-handbook/hcp/chapter-7-grade-criteria-determining-certainty-of-evidence/index.html)~~ (リジェクト)
- [Unifying Framework of Credibility Assessment](https://deepblue.lib.umich.edu/bitstream/handle/2027.42/106422/Hilligoss_Rieh_IPM2008%20Developing%20a%20unifying.pdf)
