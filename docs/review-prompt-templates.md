# プロンプトテンプレートのレビューと改善提案

**作成日:** 2025-12-27
**更新日:** 2025-12-27（Phase 1-3明確化）
**ステータス:** 確定
**関連:** ADR-0006 (8-Layer Security Model), `config/prompts/*.j2`, `src/filter/llm_security.py`

---

## エグゼクティブサマリー

本ドキュメントでは、Lyraの **Jinja2プロンプトテンプレート（`config/prompts/*.j2`）** と、周辺に残存する **Pythonインラインプロンプト**、および **LLM出力のパース/バリデーション方式** をレビューし、すぐ実装できる改善案に落とし込む。主な所見:

1. **プロンプト品質:** A（優秀）からD（要改善）まで幅がある
2. **言語の不統一:** テンプレート間で日本語と英語が混在
3. **出力バリデーション:** セキュリティ面（ADR-0006）は堅牢だが、フォーマット強制は弱い
4. **リトライ機構:** フォールバックは存在するが、フィードバック付き構造化リトライはない
5. **⚠️ テンプレート外部化の不徹底:** 一部のプロンプトがPythonインラインで残っている（設計違反）

---

## 前提（本ドキュメントの実装方針）

本ドキュメントの改善案は、以下の前提で「そのまま実装に移せる」粒度にする。

- **DB方針**: **DBは作り直し前提**（`data/lyra.db` を破棄し、`src/storage/schema.sql` から再生成）。**後方互換性は一切不要**。
  - migration 機構（`schema_migrations` + `migrations/*.sql`）は既に存在するが、**本フェーズでは使用しない**（残す/消すは別フェーズの判断）。
  - 互換性維持のための分岐（旧フィールド名・旧JSON形式など）を **コードに残さない**。
- **LLM出力の扱い**: LLMは「JSON only」と指示しても前置き文字列やMarkdown code fenceを混ぜることがあるため、**JSON抽出は1箇所に集約**し、全コンポーネントで同じパーサーを使う。
- **ADR整合**:
  - **ADR-0006**: `validate_llm_output()` によるセキュリティ（漏洩検知/URL検知等）を維持。
  - ローカルLLM制約（トークン/処理比率）を維持。
- **出力言語**: プロンプト本体・LLM出力ともに **英語限定**（パフォーマンス最大化のため）。

## Part 1: プロンプトテンプレート一覧

### 1.1 Jinja2テンプレート (`config/prompts/*.j2`)

| ファイル | 用途 | 言語 | 評価 | 優先度 |
|------|---------|----------|--------|----------|
| `extract_facts.j2` | 客観的事実の抽出 | JP | C | High |
| `extract_claims.j2` | 文脈付き主張の抽出 | JP | C | High |
| `summarize.j2` | テキスト要約 | JP | D | Critical |
| `translate.j2` | 翻訳 | JP | D | Medium |
| `decompose.j2` | 原子主張への分解 | JP | B | Low |
| `detect_citation.j2` | 引用リンク vs ナビゲーションリンク判定 | JP | B | Low |
| `relevance_evaluation.j2` | 引用関連度 0-10 評価 | JP | A | - |

### 1.2 Python インラインプロンプト（⚠️ 外部化が必要）

> **設計違反:** `src/utils/prompt_manager.py` と `render_prompt()` により「LLM入力プロンプトは `config/prompts/*.j2` に外部化」という構造が既に実装されているが、以下のプロンプトがインラインで残っている。Phase 0 で外部化すべき。

| ファイル | 変数名 | 用途 | 言語 | 評価 | 外部化 | 改善案 |
|----------|----------|---------|----------|--------|--------|--------|
| `src/extractor/quality_analyzer.py` | `LLM_QUALITY_ASSESSMENT_PROMPT` | コンテンツ品質評価 | EN | B | ⚠️ 要外部化 | Part 2.9 |
| `src/extractor/quality_analyzer.py` | `LLM_QUALITY_ASSESSMENT_PROMPT_EN` | 上記と同等（EN版） | EN | B | ⚠️ 要外部化 | Part 2.9参照 |
| `src/report/chain_of_density.py` | `INITIAL_SUMMARY_PROMPT` | CoD初期要約 | EN | B | ⚠️ 要外部化 | Part 2.10 |
| `src/report/chain_of_density.py` | `DENSIFY_PROMPT` | CoD高密度化 | EN/JP混在 | C | ⚠️ 要外部化 | Part 2.8 |
| `src/filter/llm.py` | `EXTRACT_FACTS_INSTRUCTION` | 漏洩検出用 (※1) | EN | - | 維持OK | 対象外 |
| `src/filter/llm.py` | `EXTRACT_CLAIMS_INSTRUCTION` | 漏洩検出用 (※1) | EN | - | 維持OK | 対象外 |
| `src/filter/llm.py` | `SUMMARIZE_INSTRUCTION` | 漏洩検出用 (※1) | EN | - | 維持OK | 対象外 |
| `src/filter/llm.py` | `TRANSLATE_INSTRUCTION` | 漏洩検出用 (※1) | EN | - | 維持OK | 対象外 |
| `src/extractor/citation_detector.py` | `_DETECT_CITATION_INSTRUCTIONS` | バリデーション用 (※2) | JP | - | 維持OK | 対象外 |

**注記:**
- ※1: **漏洩検出用テンプレート** - LLM出力に対するn-gramマッチングで使用（ADR-0006 L4）。LLMへの入力ではなくセキュリティバリデーション用のため、外部化不要。
- ※2: **バリデーション用** - `validate_llm_output()` のシステムプロンプトとして使用。完全なプロンプトは `detect_citation.j2` にある。外部化不要。
- **⚠️ 要外部化**: `src/utils/prompt_manager.py` の設計方針（外部テンプレート化）に違反。`config/prompts/*.j2` へ移動が必要。

---

## Part 2: 個別プロンプトレビュー

### 2.1 `extract_facts.j2` — 評価: C

**現状:**
```
あなたは情報抽出の専門家です。以下のテキストから客観的な事実を抽出してください。

テキスト:
{{ text }}

抽出した事実をJSON配列形式で出力してください。各事実は以下の形式で:
{"fact": "事実の内容", "confidence": 0.0-1.0の信頼度}

事実のみを出力し、意見や推測は含めないでください。
```

**問題点:**
- 「事実」の定義がない（検証可能な記述？観察？）
- 信頼度スコアの基準がない
- 出力件数制限がない（トークン浪費リスク）
- Few-shot例がない
- エビデンスタイプの分類がない

**改善案:**
```jinja2
You are an expert in information extraction for academic research.

## Task
Extract verifiable factual statements from the text below.

## Definition of "Fact"
- Empirically verifiable claims (not opinions or predictions)
- Contains specific entities (names, numbers, dates, locations)
- Can be traced to a primary source

## Input
{{ text }}

## Output Requirements
- Return 3-10 most important facts as JSON array
- Each fact: {"fact": "...", "confidence": 0.0-1.0, "evidence_type": "statistic|citation|observation"}
- Confidence criteria:
  - 1.0: Directly stated with explicit source
  - 0.7-0.9: Stated clearly without source
  - 0.5-0.6: Implied or paraphrased
  - 0.3-0.4: Inferred from context

## Example
[{"fact": "DPP-4 inhibitors reduced HbA1c by 0.5-1.0%", "confidence": 0.9, "evidence_type": "statistic"}]

Output JSON array only:
```

---

### 2.2 `extract_claims.j2` — 評価: C

**現状:**
```
あなたは情報分析の専門家です。以下のテキストから主張を抽出してください。

リサーチクエスチョン: {{ context }}

テキスト:
{{ text }}

抽出した主張をJSON配列形式で出力してください。各主張は以下の形式で:
{"claim": "主張の内容", "type": "fact|opinion|prediction", "confidence": 0.0-1.0}
```

**問題点:**
- リサーチクエスチョン（`context`）の使い方が不明確
- 主張タイプの分類が単純すぎる（fact/opinion/prediction）
- クエリへの関連度スコアがない
- 粒度の指定がない

**改善案:**
```jinja2
You are a research analyst extracting claims relevant to a specific research question.

## Research Question
{{ context }}

## Source Text
{{ text }}

## Task
Extract claims that directly help answer the research question above.

## Claim Types
- fact: Verifiable statement about current/past state (can be checked)
- opinion: Value judgment or recommendation
- prediction: Future-oriented claim

## Output
JSON array with 1-5 most relevant claims:
{
  "claim": "claim text",
  "type": "fact|opinion|prediction",
  "relevance_to_query": 0.0-1.0,
  "confidence": 0.0-1.0
}

Prioritize claims that:
1. Directly address the research question
2. Contain specific, verifiable information
3. Are supported by evidence in the text

Output JSON array only:
```

---

### 2.3 `summarize.j2` — 評価: D（Critical）

**現状:**
```
以下のテキストを要約してください。重要なポイントを簡潔にまとめてください。

テキスト:
{{ text }}

要約:
```

**問題点:**
- 指示が極めて汎用的
- 出力長の指定がない
- 構造化出力がない
- 目的の指定がない
- エンティティ保持のガイダンスがない

**改善案:**
```jinja2
You are a research summarizer for evidence synthesis.

## Input Text
{{ text }}

## Task
Create a concise summary preserving key evidence.

## Requirements
- Length: {{ max_words | default(100) }} words maximum
- Focus: Claims, findings, and their supporting evidence
- Preserve: Specific numbers, dates, source attributions
- Exclude: Background context, methodology details (unless critical)

## Output Format
Summary text only (no JSON, no bullet lists, no headings):
```

---

### 2.4 `translate.j2` — 評価: D

**現状:**
```
以下のテキストを{{ target_lang }}に翻訳してください。

テキスト:
{{ text }}

翻訳:
```

**問題点:**
- 技術/医療用語の扱いがない
- 固有名詞のガイダンスがない
- 数値の精度要件がない

**改善案:**
```jinja2
You are a professional translator specializing in academic and medical texts.

## Source Text
{{ text }}

## Target Language
{{ target_lang }}

## Translation Guidelines
- Preserve technical/medical terminology accurately
- Keep proper nouns (drug names, study names) in original form
  - Add translation in parentheses if helpful: "sitagliptin (シタグリプチン)"
- Maintain numerical precision (doses, percentages, p-values)
- Preserve citation markers [1], [2], etc.
- Do not add or remove information

## Output
Translated text only (no explanations or notes):
```

---

### 2.5 `decompose.j2` — 評価: B（良好）

**長所:**
- 詳細なスキーマ定義
- Few-shot例が提供されている
- 明確な制約

**軽微な問題:**
- 日本語出力がハードコード
- `hints` フィールドが曖昧

**追加提案:**
```jinja2
{# 既存テンプレートへの追加 #}

## Additional Guidance for hints
hints should specify concrete source types:
- Good: "PubMed RCTs", "FDA approval documents", "Cochrane reviews"
- Bad: "search online", "check news"
```

> **注:** 出力言語は英語固定（Part 2.11参照）。`output_lang` パラメータは導入しない。

---

### 2.6 `detect_citation.j2` — 評価: B

**長所:**
- 明確なYES/NO出力
- 具体的な除外基準

**軽微な問題:**
- 学術引用パターンが不足

**追加提案:**
```jinja2
{# 既存基準への追加 #}

Academic citation indicators (high confidence):
- DOI links (doi.org/10.xxxx/...)
- PubMed links (pubmed.ncbi.nlm.nih.gov/...)
- arXiv links (arxiv.org/abs/...)
- Reference markers: [1], [2], (Smith et al., 2023)
- Academic phrases: "et al.", "Fig.", "Table", "Supplementary"
```

---

### 2.7 `relevance_evaluation.j2` — 評価: A（優秀）

**長所:**
- 明確な0-10スケールと具体的な基準
- SUPPORTS/REFUTES判定の明示的除外
- 「有用性」評価軸の明確な定義

**変更不要。** これが品質の参照テンプレート。

---

### 2.8 `DENSIFY_PROMPT` — 評価: C

**場所:** `src/report/chain_of_density.py`

**現状:**
```python
DENSIFY_PROMPT = """You are an expert in information compression. Improve the following summary to be more dense.

[Current Summary]
{current_summary}

[Original Information]
{original_content}

[Missing Entities]
{missing_entities}

[Requirements]
1. Include more important information while maintaining summary length
2. Include missing entities as much as possible
3. Preserve source information for each claim
4. Remove redundant expressions and increase information density
5. Maintain approximately 100-150 words

[Output Format]
...
JSON出力のみを返してください:"""  # ← 言語混在
```

**問題点:**
- 言語混在（英語本文 + 日本語フッター）
- 「学術研究支援」というコンテキストが不足
- Evidence Graphとの連携が考慮されていない
- エンティティの重要度基準がない
- 矛盾検出の指示がない

**改善案:**
```python
DENSIFY_PROMPT = """You are an expert in information compression for academic research synthesis.

## Purpose
Increase information density while preserving evidence quality for claim verification.

## Current Summary
{current_summary}

## Original Information
{original_content}

## Missing Entities (priority order)
{missing_entities}

## Requirements
1. **Density Increase**: Include more verifiable information without increasing length
2. **Entity Integration**: Incorporate missing entities, prioritizing:
   - Quantitative data (numbers, percentages, dates)
   - Named entities (researchers, institutions, studies)
   - Causal relationships
3. **Source Preservation**: Maintain source attribution for each claim
4. **Redundancy Removal**: Eliminate repetitive or vague expressions
5. **Length Constraint**: Maintain approximately 100-150 words
6. **Conflict Detection**: Note if new entities contradict existing claims

## Output Format
{{
  "summary": "densified summary text",
  "entities": ["entity1", "entity2", ...],
  "claims": [
    {{
      "text": "verifiable claim",
      "source_indices": [0, 1],
      "claim_type": "factual|causal|comparative|temporal|quantitative",
      "confidence": 0.0-1.0
    }}
  ],
  "density_metrics": {{
    "entities_added": <number>,
    "entities_total": <number>,
    "compression_ratio": <float>
  }},
  "conflicts": ["any contradictions with existing claims"]
}}

Return only JSON output:"""
```

**Jinja2テンプレート化時のファイル名:** `config/prompts/densify.j2`

---

### 2.9 `LLM_QUALITY_ASSESSMENT_PROMPT` — 評価: B

**場所:** `src/extractor/quality_analyzer.py`

**現状:**
```python
LLM_QUALITY_ASSESSMENT_PROMPT = """You are an expert in web content quality assessment...
Evaluation criteria:
- Does it have unique insights or analysis?
- Is it based on primary sources?
- Is the writing natural and human-like?
- Are ads or affiliate links excessive?
- Is the information accurate and trustworthy?
...
```

**長所:**
- 明確な評価基準5項目
- JSON出力フォーマット指定
- 日本語/英語版の両方が存在

**問題点:**
- 「Lyra特有のコンテキスト」が不足（学術研究支援という目的）
- `is_ai_generated` の判定基準が曖昧
- ドメイン固有の品質指標がない（学術ドメインへの適合度）

**改善案:**
```python
LLM_QUALITY_ASSESSMENT_PROMPT = """You are an expert in evaluating web content quality for academic research purposes.

## Context
This content will be used as evidence in a research synthesis system.
Prioritize academic credibility over general web quality.

## Text (first 2000 characters)
{text}

## Evaluation Criteria
1. **Source Authority**: Is this from a primary source, peer-reviewed publication, or authoritative institution?
2. **Evidence Quality**: Does it contain specific data, citations, or verifiable claims?
3. **Originality**: Is this original research/analysis vs. aggregated/summarized content?
4. **Objectivity**: Is the content neutral and evidence-based vs. opinion/promotional?
5. **Recency**: Is the information current and relevant?

## Output Format
{{
  "quality_score": 0.0-1.0,
  "is_ai_generated": true/false,
  "is_spam": true/false,
  "is_aggregator": true/false,
  "academic_relevance": 0.0-1.0,
  "evidence_density": "high|medium|low",
  "reason": "concise explanation"
}}

Respond in JSON only:"""
```

---

### 2.10 `INITIAL_SUMMARY_PROMPT` — 評価: B

**場所:** `src/report/chain_of_density.py`

**現状:**
```python
INITIAL_SUMMARY_PROMPT = """You are an expert in information summarization...
[Requirements]
1. Extract key facts and claims
2. Preserve source information corresponding to each claim
3. Create a summary of approximately 100-150 words
4. Include important entities (person names, organization names, dates, numbers)
...
```

**長所:**
- Chain-of-Densityの初期要約として適切
- ソース情報保持の要件あり
- エンティティ抽出の指示あり

**問題点:**
- 「学術研究支援」というコンテキストが不足
- Evidence Graphとの連携が考慮されていない
- クエリとの関連度を考慮していない

**改善案:**
```python
INITIAL_SUMMARY_PROMPT = """You are an expert in summarizing research materials for evidence synthesis.

## Purpose
This summary will be used in an evidence graph to support or refute research claims.
Focus on extractable, verifiable information.

## Input Information
{content}

## Research Context (if available)
{query_context}

## Requirements
1. Extract claims that can be independently verified
2. Preserve source attribution for each claim
3. Prioritize quantitative data (statistics, measurements, dates)
4. Create a summary of approximately 100-150 words
5. Flag conflicting or contradictory information

## Output Format
{{
  "summary": "summary text",
  "entities": ["entity1", "entity2", ...],
  "claims": [
    {{
      "text": "verifiable claim",
      "source_indices": [0, 1],
      "claim_type": "factual|causal|comparative|temporal|quantitative",
      "confidence": 0.0-1.0
    }}
  ],
  "conflicts": ["any contradictions noted"]
}}

Return only JSON output:"""
```

---

## Part 2.11: Lyra適合性の考慮事項

### 出力言語ポリシー

**方針**: プロンプト本体・LLM出力ともに **英語限定**

**理由:**
- ローカルLLM（Ollama/Qwen）は英語プロンプトの方が性能が良い
- 出力の一貫性とパース容易性を確保
- 日本語ユーザー向けの翻訳は別レイヤー（MCP Client側）で対応

**実装:**
- 全テンプレートを英語化（Phase 1で実施）
- `output_lang` パラメータは導入しない
- Few-shot例も英語で統一

### ClaimType整合性

**重要:** Lyraには「ClaimType」が複数の文脈で登場するため、混同しない。

- **A. Claim Decomposition（研究クエスチョン分解）**: `src/filter/claim_decomposition.py:ClaimType`
  - 目的: クエスチョンを *検証可能な原子主張* に分解する際の分類（`factual|causal|comparative|definitional|temporal|quantitative`）
  - これは **extract_claims の分類（DB保存/レポート分類）とは別概念**
- **B. Extract Claims（ページ/断片からの主張抽出）**: `config/prompts/extract_claims.j2` の `"type"`
  - 目的: DB `claims.claim_type` とレポート生成の簡易分類（例: `fact|opinion|prediction`）

**結論（Phase 1〜2の方針）**:

- `extract_claims.j2` は当面 **`type: "fact|opinion|prediction"` を維持**し、必要なら `relevance_to_query` 等を追加する。
- `claim_decomposition.py:ClaimType` に `predictive/normative` を無理に追加しない（統合再設計は別フェーズ）。

### ローカルLLM制約（ADR-0004）

**考慮事項:**
- Ollama使用によるトークン制限
- 複雑すぎるプロンプトは性能低下
- Few-shot例の追加はトークン消費増

**推奨:**
1. プロンプトは300-500トークン以内を目標
2. Few-shot例は1つに限定
3. 複雑なスキーマより単純な指示を優先

---

## Part 3: 出力バリデーション分析

### 3.1 現在のバリデーション機構

| レイヤー | 機構 | 場所 | カバレッジ |
|-------|-----------|----------|----------|
| **L2** | 入力サニタイゼーション | `llm_security.py:sanitize_llm_input()` | 全LLM入力 |
| **L3** | システムタグ保護 | `llm_security.py:generate_session_tag()` | システムプロンプト |
| **L4** | 出力バリデーション | `llm_security.py:validate_llm_output()` | 全LLM出力 |
| **L7** | レスポンスサニタイゼーション | `mcp/response_sanitizer.py` | MCPレスポンス |

### 3.2 JSON解析パターン

**現在のアプローチ（全箇所共通）:**
```python
# コードベース全体で使用されているパターン
try:
    json_match = re.search(r"\[.*\]", response, re.DOTALL)  # or r"\{.*\}"
    if json_match:
        parsed = json.loads(json_match.group())
    else:
        parsed = []  # or {}
except json.JSONDecodeError:
    parsed = fallback_value
```

**このパターンを使用しているファイル:**
- `src/filter/llm.py`
- `src/filter/claim_decomposition.py`
- `src/report/chain_of_density.py`
- `src/extractor/quality_analyzer.py`

### 3.3 数値スコアバリデーション

**0-10スコア (relevance_evaluation):**
```python
# src/search/citation_filter.py:_parse_llm_score_0_10()
def _parse_llm_score_0_10(text: str) -> int | None:
    m = _INT_RE.search(text.strip())
    if not m:
        return None
    n = int(m.group(1))
    return max(0, min(10, n))  # [0, 10]にクランプ
```

**0.0-1.0スコア (quality, confidence):**
```python
# 全体で使用されているクランプパターン
score = max(0.0, min(1.0, raw_score))
```

### 3.4 YES/NO正規化

```python
# src/extractor/citation_detector.py:_normalize_yes_no()
def _normalize_yes_no(text: str) -> str | None:
    cleaned = text.strip().upper()
    cleaned = re.sub(r"[^A-Z]", "", cleaned)
    if cleaned.startswith("YES"):
        return "YES"
    if cleaned.startswith("NO"):
        return "NO"
    return None
```

### 3.5 フォールバック機構

| コンポーネント | フォールバック戦略 | 場所 |
|-----------|------------------|----------|
| Claim Decomposition | ルールベースフォールバック | `claim_decomposition.py:_decompose_with_rules()` |
| Chain-of-Density | ルールベース圧縮 | `chain_of_density.py` |
| Quality Assessment | `None`を返し、ルールベースを使用 | `quality_analyzer.py` |
| Citation Detection | `is_citation=False`を返す | `citation_detector.py` |

---

## Part 4: ギャップと改善提案

### 4.1 不足: フィードバック付き構造化リトライ

**現状:** パース失敗時、即座にルールベースまたはデフォルト値にフォールバック。

**問題:** LLMが軽微なフォーマット問題で正しい回答を生成している可能性がある。

**提案: 修正プロンプト付きリトライ**

**提案: 実装時期（未定：Phase T以降）**


```python
# 提案するリトライ機構
async def parse_with_retry(
    response: str,
    expected_schema: dict,
    max_retries: int = 1,
) -> dict | None:
    """フォーマットエラー時にリトライ付きでLLMレスポンスをパース。"""

    for attempt in range(max_retries + 1):
        try:
            # 抽出を試行
            json_match = re.search(r"[\[{].*[\]}]", response, re.DOTALL)
            if json_match:
                parsed = json.loads(json_match.group())
                # スキーマに対してバリデーション
                if validate_schema(parsed, expected_schema):
                    return parsed

        except json.JSONDecodeError as e:
            if attempt < max_retries:
                # 修正プロンプトでリトライ
                response = await llm_call(
                    f"Your previous response had a JSON error: {e}\n"
                    f"Original response: {response[:500]}\n"
                    f"Please output valid JSON matching this schema: {expected_schema}"
                )
            else:
                return None

    return None
```

### 4.2 不足: スキーマバリデーション

**現状:** JSONはパースされるがスキーマはバリデーションされない。

**問題:** 欠落フィールド、型不一致が暗黙的に受け入れられる。

**提案: LLM出力用Pydanticモデルの追加**

```python
# src/filter/llm_schemas.py（新規ファイル）
from pydantic import BaseModel, Field, validator

class ExtractedFact(BaseModel):
    fact: str = Field(..., min_length=10)
    confidence: float = Field(..., ge=0.0, le=1.0)
    evidence_type: str = Field(default="observation")

    @validator("evidence_type")
    def validate_evidence_type(cls, v):
        allowed = {"statistic", "citation", "observation"}
        return v if v in allowed else "observation"

class ExtractedClaim(BaseModel):
    claim: str = Field(..., min_length=10)
    type: str = Field(default="factual")
    relevance_to_query: float = Field(default=0.5, ge=0.0, le=1.0)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
```

### 4.3 不足: 出力フォーマット強制

**現状:** プロンプトで「Output JSON only」と指示しているが強制されていない。

**問題:** LLMがJSON前に前置きテキストを追加することが多い。

**提案: 構造化出力モード**

```python
# サポートするAPI向け（例: OpenAI, Anthropic）
response = await client.messages.create(
    model="claude-3-5-sonnet-20241022",
    messages=[...],
    # JSON出力を強制
    response_format={"type": "json_object"}
)
```

### 4.4 ~~不足: 信頼度キャリブレーション~~ → NLI専用として既存実装あり

> **注意**: 信頼度キャリブレーションは `src/utils/calibration.py` に **NLI モデル専用** として実装済み。
> LLM 抽出 confidence との関係は [`docs/confidence-calibration-design.md`](./confidence-calibration-design.md) を参照。

**スコープ:**
- **対象**: `nli-confidence`（NLIモデル出力）
- **非対象**: `llm-confidence`（LLM自己報告）— 別設計で検討中

**既存実装:**
- Platt Scaling / Temperature Scaling
- Brier Score / ECE（Expected Calibration Error）評価
- 自動劣化検知 + ロールバック
- 増分再キャリブレーション（サンプル蓄積トリガー）

**MCPツール:**
- `calibration_metrics(get_stats)`: 現在のパラメータと履歴
- `calibration_metrics(get_evaluations)`: 評価履歴
- `calibration_rollback`: 以前のパラメータへロールバック

**参照:**
- ADR-0011 (LoRA Fine-tuning Strategy)
- [`docs/confidence-calibration-design.md`](./confidence-calibration-design.md) — 用語定義と設計提案

### 4.5 推奨: プロンプト構造の標準化

**提案するテンプレート構造:**

```jinja2
{# SECTION 1: ロールとコンテキスト #}
You are a {{ role }} for {{ purpose }}.

{# SECTION 2: タスク定義 #}
## Task
{{ task_description }}

{# SECTION 3: 入力 #}
## Input
{{ input_variable }}

{# SECTION 4: 制約（オプション） #}
{% if constraints %}
## Constraints
{% for c in constraints %}
- {{ c }}
{% endfor %}
{% endif %}

{# SECTION 5: 出力仕様 #}
## Output Format
{{ output_schema }}

{# SECTION 6: 例（オプション） #}
{% if examples %}
## Example
{{ examples }}
{% endif %}

{# SECTION 7: 最終指示 #}
Output {{ output_format }} only:
```

---

## Part 5: 実装ロードマップ

### Phase 0: アーキテクチャ整合性（完了）

> **問題:** `src/utils/prompt_manager.py` と `render_prompt()` により「LLM入力プロンプトは `config/prompts/*.j2` に外部化」という構造が既にあるが、インラインプロンプトが残っている。

| タスク | 移動元 | 移動先 |
|--------|--------|--------|
| Quality Assessment外部化 | `quality_analyzer.py` | `config/prompts/quality_assessment.j2` |
| Initial Summary外部化 | `chain_of_density.py` | `config/prompts/initial_summary.j2` |
| Densify外部化 | `chain_of_density.py` | `config/prompts/densify.j2` |

**新規テンプレート作成後の構成:**
```
config/prompts/
├── decompose.j2           # 既存
├── detect_citation.j2     # 既存
├── extract_claims.j2      # 既存
├── extract_facts.j2       # 既存
├── relevance_evaluation.j2 # 既存
├── summarize.j2           # 既存
├── translate.j2           # 既存
├── quality_assessment.j2  # 新規（質問 analyzer から移動）
├── initial_summary.j2     # 新規（CoD から移動）
└── densify.j2             # 新規（CoD から移動）
```

**Pythonコード変更例:**
```python
# Before (quality_analyzer.py)
LLM_QUALITY_ASSESSMENT_PROMPT = """You are an expert..."""
prompt = LLM_QUALITY_ASSESSMENT_PROMPT.format(text=text)

# After
from src.utils.prompt_manager import render_prompt
prompt = render_prompt("quality_assessment", text=text)
```

### Phase 1: プロンプト改善（全テンプレート英語化）

全10テンプレートを英語化し、Part 2の改善案を適用する。

| テンプレート | Part 2参照 | 変更内容 |
|-------------|-----------|---------|
| `summarize.j2` | 2.3 | 全面書き換え（評価D→改善案） |
| `extract_claims.j2` | 2.2 | 全面書き換え（評価C→改善案） |
| `extract_facts.j2` | 2.1 | 全面書き換え（評価C→改善案） |
| `translate.j2` | 2.4 | 全面書き換え（評価D→改善案） |
| `densify.j2` | 2.8 | 全面書き換え（英語化+改善案） |
| `initial_summary.j2` | 2.10 | 全面書き換え（改善案適用） |
| `quality_assessment.j2` | 2.9 | 全面書き換え（改善案適用） |
| `decompose.j2` | 2.5 | 軽微修正（hintsガイダンス追加、英語化） |
| `detect_citation.j2` | 2.6 | 軽微修正（学術引用パターン追加、英語化） |
| `relevance_evaluation.j2` | 2.7 | 英語化のみ（参照テンプレート） |

### Phase 2: LLM出力の型安全化（完了）

**スコープ:** LLM出力のみ対象。NLI/Embedding/Rerankerは既に `src/ml_server/schemas.py` でPydantic型安全のため対象外。

| タスク | ファイル | 内容 |
|--------|---------|------|
| JSON抽出共通化 | `src/filter/llm_output.py`（新規） | `extract_json()` + `parse_and_validate()`（スキーマ検証+リトライ+DB記録） |
| パーサー適用 | `llm.py`, `claim_decomposition.py`, `chain_of_density.py`, `quality_analyzer.py` | 既存の `re.search()` を置き換え |
| Pydanticスキーマ | `src/filter/llm_schemas.py`（新規） | `ExtractedFact`, `ExtractedClaim` 等 |
| フォーマット修正リトライ | `src/filter/llm_output.py` | 最大1回までリトライ、失敗時は `llm_extraction_errors` にDB記録（処理は続行） |

### Phase 3: プロンプトテストフレームワーク（完了）

> **注:** 英語化はPhase 1で完了。`output_lang` パラメータは導入しない（英語固定）。

| タスク | ファイル | 内容 |
|--------|---------|------|
| テストフレームワーク作成 | `tests/prompts/`（新規） | テンプレート構文検証、サンプル入出力テスト |

**実装済みファイル:**
- `tests/prompts/conftest.py` - 共有フィクスチャ（sample_inputs, json_output_templates）
- `tests/prompts/test_template_syntax.py` - 構文検証、英語のみチェック、完全性検証
- `tests/prompts/test_template_rendering.py` - レンダリングテスト、JSON形式検証、境界値テスト

**実行方法:**
```bash
make test-prompts      # プロンプトテンプレートテストのみ
make test-llm-output   # LLM出力パースのテスト（Phase 2関連）
```

### ~~Phase 4: 高度な機能~~（削除 - 実装済みまたは別設計）

> **注意**: 以下の機能はすべて既存実装済みまたは別設計文書で検討中のため、Phase 4は不要。

| 当初の提案 | 状態 | 参照 |
|------------|------|------|
| Confidence calibration（NLI） | ✅ 実装済み | `src/utils/calibration.py`, ADR-0011 |
| Confidence calibration（LLM） | 📝 別設計 | [`confidence-calibration-design.md`](./confidence-calibration-design.md) |
| A/Bテストフレームワーク | ✅ 実装済み | `src/search/ab_test.py`, ADR-0010 |
| プロンプトバージョニング | ✅ git管理で十分 | `config/prompts/*.j2` |

**MCPツール（既存、NLI専用）:**
- `calibration_metrics`: NLI統計取得、評価履歴
- `calibration_rollback`: NLIパラメータロールバック

**用語の明確化:** [`confidence-calibration-design.md`](./confidence-calibration-design.md) を参照

---

## Part 6: Phase 2 実装方針

**追加日:** 2025-12-27
**ステータス:** 確定

### 6.1 アーキテクチャ概要

```
┌─────────────────────────────────────────────────────────────────┐
│                    LLM出力パイプライン                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────┐    ┌──────────────┐    ┌──────────────────────┐  │
│  │ プロンプト │───▶│  LLM呼び出し │───▶│ セキュリティ         │  │
│  │ テンプレート│    │  (Provider)  │    │ バリデーション       │  │
│  └──────────┘    └──────────────┘    │ (validate_llm_output)│  │
│                                       └──────────┬───────────┘  │
│                                                  │              │
│                                                  ▼              │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │                    JSON抽出層                             │  │
│  │  ┌─────────────┐                                          │  │
│  │  │ extract_json│ ← src/filter/llm_output.py（共通化）     │  │
│  │  │ (regex)     │                                          │  │
│  │  └─────────────┘                                          │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                  │              │
│                                                  ▼              │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │                    既存フォールバック                     │  │
│  │              (ルールベース / デフォルト値)                │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

### 6.2 実装方針

#### スコープ

**対象:** LLM出力のみ

**対象外:** NLI / Embedding / Reranker
- これらは既に `src/ml_server/schemas.py` でPydanticスキーマによる型安全が実装済み
- 出力は数値・ラベル文字列であり、自由テキストではないためJSON抽出不要

#### JSON抽出共通化

`src/filter/llm_output.py` を新設し、JSON抽出ロジックを共通化する。

**実装:**

```python
# src/filter/llm_output.py
"""LLM出力からJSONを抽出する共通ユーティリティ。"""
import json
import re
from typing import Any


def extract_json(text: str, expect_array: bool = False) -> dict | list | None:
    """LLMレスポンスからJSONを抽出。Markdownコードブロック対応。

    Args:
        text: LLMレスポンステキスト
        expect_array: Trueの場合JSON配列を期待

    Returns:
        パースされたJSON、または抽出失敗時はNone
    """
    if not text:
        return None

    # 1. 直接パース
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass

    # 2. コードブロック内（優先）
    match = re.search(r"```(?:json)?\s*([\[\{].*?[\]\}])\s*```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # 3. 生JSON（貪欲マッチ）
    pattern = r"\[.*\]" if expect_array else r"\{.*\}"
    match = re.search(pattern, text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    return None
```

#### エッジケース処理ポリシー

| ケース | 処理 |
|--------|------|
| 複数JSONブロック | 最長マッチ（貪欲）を使用 |
| Markdownコードブロック | ` ```json...``` ` を優先的に抽出 |
| 抽出失敗時 | `None` を返す（フォールバックは呼び出し元の責任） |
| ネストしたJSON | 外側のブラケットを取得 |
| トランケートされたJSON | パース失敗 → `None` |

#### 置き換え対象

| ファイル | 現行パターン | 置き換え後 |
|----------|-------------|-----------|
| `llm.py` | `re.search(r"\[.*\]"...)` | `extract_json(response, expect_array=True)` |
| `claim_decomposition.py` | `_parse_llm_response()` 内のJSON抽出 | 同上 |
| `chain_of_density.py` | `_parse_llm_response()` 内のJSON抽出 | `extract_json(response)` |
| `quality_analyzer.py` | インラインJSONパース | `extract_json(response)` |

#### リトライ＆エラー記録ポリシー

1. **リトライ**: JSON抽出失敗またはスキーマ検証失敗時、最大1回までフォーマット修正リトライを実行
2. **1回リトライしても失敗した場合**:
   - DBに「エラーで値が取れなかった」ことを記録（`llm_extraction_errors`）
   - 処理は止めずに続行（次のパッセージ/タスクへ進む）
   - ログレベル: `WARNING`
3. **ADR-0004との整合性**: フォーマット修正リトライは「同じ機械的抽出タスクの再試行」であり、禁止されている「戦略的決定」には該当しない

#### Pydanticスキーマ方針（寛容モード）

- 欠落フィールドはデフォルト値で補完
- 型不一致は変換を試みる（`str` → `float` 等）
- 変換不可の場合のみバリデーションエラー

```python
# src/filter/llm_schemas.py
from pydantic import BaseModel, Field

class ExtractedFact(BaseModel):
    fact: str = Field(..., min_length=5)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    evidence_type: str = Field(default="observation")

class ExtractedClaim(BaseModel):
    claim: str = Field(..., min_length=5)
    type: str = Field(default="fact")
    relevance_to_query: float = Field(default=0.5, ge=0.0, le=1.0)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
```

#### DBスキーマ変更

**不要**。

- `relevance_to_query`: 抽出時フィルタリング用の一時値であり、メモリ内処理で十分
- `evidence_type`: extract_facts用でありclaimsテーブルと無関係

LLM出力フォーマットとDB保存フォーマットは分離可能。一時的なスコアはパース後にメモリ内で使用し、DBには既存カラムのみ保存する。

---

## 付録A: バリデーション関数リファレンス

### `validate_llm_output()` — メインエントリーポイント

**場所:** `src/filter/llm_security.py:validate_llm_output()`

```python
def validate_llm_output(
    text: str,
    expected_max_length: int | None = None,
    warn_on_suspicious: bool = True,
    system_prompt: str | None = None,
    mask_leakage: bool = True,
) -> OutputValidationResult:
```

**実行されるチェック:**
1. URL検出 (`http://`, `https://`, `ftp://`)
2. IPアドレス検出 (IPv4, IPv6)
3. プロンプト漏洩検出 (n-gramマッチング)
4. 出力切り詰め（期待最大の10倍）
5. フラグメントマスキング (`[REDACTED]`)

### `sanitize_llm_input()` — 入力前処理

**場所:** `src/filter/llm_security.py:sanitize_llm_input()`

**7ステッププロセス:**
1. Unicode NFKC正規化
2. HTMLエンティティデコード
3. ゼロ幅文字除去
4. 制御文字除去
5. LYRAタグパターン除去
6. 危険パターン検出
7. 長さ制限

---

## 付録B: プロンプト品質チェックリスト

プロンプトの作成・レビュー時にこのチェックリストを使用:

- [ ] **ロール定義:** 明確なペルソナ/専門性を指定
- [ ] **タスク明示:** 一文でのタスク説明
- [ ] **入力ラベル:** 入力データを明確に区切る
- [ ] **出力スキーマ:** 正確なフォーマット指定（JSON、プレーンテキスト）
- [ ] **制約列挙:** 長さ制限、件数制限、除外条件
- [ ] **例の提供:** 複雑なタスクには少なくとも1つのfew-shot例
- [ ] **言語統一:** 全体で単一言語
- [ ] **最終指示:** 「Output X only:」で前置きを減らす
- [ ] **信頼度基準:** 信頼度を要求する場合はスケールを定義
- [ ] **バリデーション可能:** 出力をプログラム的にバリデーション可能
