> **⚠️ ARCHIVED DOCUMENT**
>
> This document is an archived snapshot of the project's development history and is no longer maintained.
> Content reflects the state at the time of writing and may be inconsistent with the current codebase.
>
> **Archived**: 2025-12-27

# Phase Rb: プロンプトテンプレートのレビューと改善

**作成日:** 2025-12-27
**ステータス:** ✅ IMPLEMENTED（Phase 0-3 全完了）
**関連:** ADR-0006 (8-Layer Security Model), `config/prompts/*.j2`, `src/filter/llm_security.py`

---

## エグゼクティブサマリー

Lyraの **Jinja2プロンプトテンプレート（`config/prompts/*.j2`）** と **LLM出力のパース/バリデーション方式** をレビューし、以下の改善を実施した。

| Phase | 内容 | コミット |
|-------|------|----------|
| **Phase 0** | インラインプロンプトの外部化（3テンプレート） | `4a8ba68` |
| **Phase 1** | 全10テンプレートの英語化と品質改善 | `676d763` |
| **Phase 2** | LLM出力の型安全化（Pydantic + リトライ + DB記録） | `9730d6d`, `b6f0712` |
| **Phase 3** | プロンプトテストフレームワーク構築 | `dc40bec`, `a2c3ed3` |

---

## 設計判断

### 出力言語ポリシー

**決定**: プロンプト本体・LLM出力ともに **英語限定**

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
- **B. Extract Claims（ページ/断片からの主張抽出）**: `config/prompts/extract_claims.j2` の `"type"`
  - 目的: DB `claims.claim_type` とレポート生成の簡易分類（`fact|opinion|prediction`）

**決定**: 統合再設計は別フェーズとし、現状の分離を維持。

### ローカルLLM制約（ADR-0004）

**推奨:**
1. プロンプトは300-500トークン以内を目標
2. Few-shot例は1つに限定
3. 複雑なスキーマより単純な指示を優先

---

## 実装済みテンプレート一覧

| ファイル | 用途 | 評価 |
|------|---------|--------|
| `extract_facts.j2` | 客観的事実の抽出 | A |
| `extract_claims.j2` | 文脈付き主張の抽出 | A |
| `summarize.j2` | テキスト要約 | A |
| `translate.j2` | 翻訳 | A |
| `decompose.j2` | 原子主張への分解 | A |
| `detect_citation.j2` | 引用リンク vs ナビゲーションリンク判定 | A |
| `relevance_evaluation.j2` | 引用関連度 0-10 評価 | A（参照テンプレート） |
| `quality_assessment.j2` | コンテンツ品質評価 | A（Phase 0で外部化） |
| `initial_summary.j2` | CoD初期要約 | A（Phase 0で外部化） |
| `densify.j2` | CoD高密度化 | A（Phase 0で外部化） |

---

## Phase 2: LLM出力の型安全化アーキテクチャ

### アーキテクチャ概要

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
│  │              parse_and_validate()                        │  │
│  │  ┌─────────────┐  ┌──────────────┐  ┌────────────────┐   │  │
│  │  │ extract_json│─▶│ Pydantic     │─▶│ Retry (1x) or  │   │  │
│  │  │ (regex)     │  │ validation   │  │ DB error log   │   │  │
│  │  └─────────────┘  └──────────────┘  └────────────────┘   │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### モジュール間連動

| 呼び出し元 | スキーマ |
|-----------|---------|
| `src/filter/llm.py` | `ExtractedFact`, `ExtractedClaim` |
| `src/filter/claim_decomposition.py` | `DecomposedClaim` |
| `src/report/chain_of_density.py` | `DenseSummaryOutput`, `InitialSummaryOutput` |
| `src/extractor/quality_analyzer.py` | `QualityAssessmentOutput` |

### リトライ＆エラー記録ポリシー

1. **リトライ**: JSON抽出失敗またはスキーマ検証失敗時、最大1回までフォーマット修正リトライを実行
2. **1回リトライしても失敗した場合**:
   - DBに「エラーで値が取れなかった」ことを記録（`llm_extraction_errors`テーブル）
   - 処理は止めずに続行（次のパッセージ/タスクへ進む）
   - ログレベル: `WARNING`
3. **ADR-0004との整合性**: フォーマット修正リトライは「同じ機械的抽出タスクの再試行」であり、禁止されている「戦略的決定」には該当しない

### Pydanticスキーマ方針（寛容モード）

- 欠落フィールドはデフォルト値で補完
- 型不一致は変換を試みる（`str` → `float` 等）
- 変換不可の場合のみバリデーションエラー

---

## テスト実行方法

```bash
make test-prompts      # プロンプトテンプレートテストのみ
make test-llm-output   # LLM出力パースのテスト（Phase 2関連）
```

---

## 付録A: バリデーション関数リファレンス

### `validate_llm_output()` — セキュリティバリデーション

**場所:** `src/filter/llm_security.py`

**実行されるチェック:**
1. URL検出 (`http://`, `https://`, `ftp://`)
2. IPアドレス検出 (IPv4, IPv6)
3. プロンプト漏洩検出 (n-gramマッチング)
4. 出力切り詰め（期待最大の10倍）
5. フラグメントマスキング (`[REDACTED]`)

### `sanitize_llm_input()` — 入力前処理

**場所:** `src/filter/llm_security.py`

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
- [ ] **言語統一:** 全体で単一言語（英語）
- [ ] **最終指示:** 「Output X only:」で前置きを減らす
- [ ] **信頼度基準:** 信頼度を要求する場合はスケールを定義
- [ ] **バリデーション可能:** 出力をプログラム的にバリデーション可能

