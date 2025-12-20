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
| `TRUSTED` | 信頼メディア・ナレッジベース (wikipedia.org) | 0.75 |
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

### 提案2: 信頼度スコアの導入

現在の Trust Level（ドメインレベル）に加え、主張レベルの Confidence Score を明示的に分離:

```python
@dataclass
class ClaimAssessment:
    claim_id: str
    source_trust_level: TrustLevel        # ドメインの信頼レベル
    source_confidence: float              # ソース自体への信頼度 (0.0-1.0)
    claim_confidence: float               # 主張の確実性 (0.0-1.0)
    evidence_quality: EvidenceQuality     # high/moderate/low/very_low (GRADE準拠)
    contradiction_status: ContradictionStatus  # none/contested/refuted
```

### 提案3: ユーザー制御インターフェース

#### 3.1 ブロック状態の可視化

MCPツール `get_blocked_domains` を追加:

```python
def get_blocked_domains() -> list[BlockedDomainInfo]:
    """ブロックされたドメイン一覧を取得"""
    return [
        {
            "domain": "example.com",
            "blocked_at": "2024-01-15T10:30:00Z",
            "reason": "Contradiction with pubmed.gov (claim_id: abc123)",
            "contradicting_claims": ["claim:abc123", "claim:def456"],
            "original_trust_level": "UNVERIFIED",
            "can_restore": True,
        }
    ]
```

#### 3.2 手動復元機能

MCPツール `restore_domain` を追加:

```python
def restore_domain(domain: str, new_trust_level: TrustLevel = TrustLevel.LOW) -> RestoreResult:
    """ブロックされたドメインを復元"""
    # ユーザー判断による復元を許可
    # 復元履歴を記録（監査用）
```

#### 3.3 信頼レベルのオーバーライド

`config/domains.yaml` に `user_overrides` セクションを追加:

```yaml
user_overrides:
  - domain: "controversial-but-valid.org"
    trust_level: "trusted"
    reason: "Manually verified as legitimate academic source"
    added_at: "2024-01-15"
```

### 提案4: エビデンスグラフ上での可視化

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

#### 4.2 MCPツール拡張

`get_evidence_graph` の返却値に矛盾情報を追加:

```python
{
    "claims": [...],
    "contradictions": [
        {
            "id": "contradiction:001",
            "type": "scientific_debate",
            "claims": ["claim:abc", "claim:def"],
            "trust_levels": ["ACADEMIC", "ACADEMIC"],
            "resolution_status": "unresolved",
            "user_note": null
        }
    ]
}
```

### 提案5: GRADE準拠のエビデンス品質評価

主張ごとにGRADE基準でエビデンス品質を評価:

| 品質レベル | 条件 |
|-----------|------|
| High | ≥3 ACADEMIC/GOVERNMENT 源、矛盾なし |
| Moderate | 2 信頼源、または軽度の矛盾あり |
| Low | 1 信頼源、または中程度の矛盾 |
| Very Low | UNVERIFIED のみ、または重大な矛盾 |

```python
def assess_evidence_quality(claim_id: str) -> EvidenceQuality:
    evidence = graph.get_all_evidence(claim_id)

    # Start from baseline based on source types
    if any(e.trust_level >= ACADEMIC for e in evidence.supports):
        quality = EvidenceQuality.HIGH
    else:
        quality = EvidenceQuality.LOW

    # Downgrade for inconsistency
    if evidence.contradictions:
        quality = downgrade(quality, reason="inconsistency")

    # Downgrade for indirectness, imprecision, etc.
    ...

    return quality
```

---

## 実装ロードマップ

### Phase 1: 透明性の向上（低リスク）

1. [ ] `get_blocked_domains` MCPツール追加
2. [ ] ブロック理由のログ強化
3. [ ] エビデンスグラフに矛盾関係を明示的に保存

### Phase 2: 科学的論争の区別（中リスク）

1. [ ] `ContradictionType` enum 追加
2. [ ] 矛盾検出時に両者の信頼レベルを比較
3. [ ] ACADEMIC同士の矛盾は "contested" として保持
4. [ ] `verdict: contested` の場合はBLOCKEDにしない

### Phase 3: ユーザー制御（中リスク）

1. [ ] `restore_domain` MCPツール追加
2. [ ] `config/domains.yaml` に `user_overrides` セクション追加
3. [ ] 復元履歴の監査ログ

### Phase 4: GRADE準拠（高工数）

1. [ ] `EvidenceQuality` enum と評価ロジック
2. [ ] MCPレスポンスに品質レベルを追加
3. [ ] Cursor AIへの品質情報伝達

---

## 関連ドキュメント

- [REQUIREMENTS.md §4.4.1](REQUIREMENTS.md) - L6 Source Verification Flow
- [REQUIREMENTS.md §4.5](REQUIREMENTS.md) - 品質保証と評価指標
- `src/filter/source_verification.py` - 現行実装
- `src/filter/evidence_graph.py` - エビデンスグラフ

## 参考文献

- [NATO Admiralty Code](https://kravensecurity.com/source-reliability-and-information-credibility/)
- [GRADE Handbook](https://gradepro.org/handbook)
- [Cornell Evidence Synthesis Guide](https://guides.library.cornell.edu/evidence-synthesis/intro)
- [CDC ACIP GRADE Handbook](https://www.cdc.gov/acip-grade-handbook/hcp/chapter-7-grade-criteria-determining-certainty-of-evidence/index.html)
- [Unifying Framework of Credibility Assessment](https://deepblue.lib.umich.edu/bitstream/handle/2027.42/106422/Hilligoss_Rieh_IPM2008%20Developing%20a%20unifying.pdf)
