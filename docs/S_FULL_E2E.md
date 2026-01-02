# S_FULL_E2E: フルE2Eケーススタディ設計

## 概要

本ドキュメントは、Lyraのケーススタディ設計である。

### 目的

1. **機能実証**: Lyraの全機能（検索→抽出→NLI→エビデンスグラフ→レポート素材）が統合動作することを実証
2. **比較評価**: 商用ツール（Google Deep Research、ChatGPT Deep Research）との定性的比較
3. **専門家評価**: 薬学博士（メタ回帰分析専門）によるGround Truth評価

### 参照ADR

- ADR-0002: Thinking-Working Separation（Cursor AIが思考、Lyraが作業）
- ADR-0005: Evidence Graph Structure（主張-断片-ページのグラフ構造）
- ADR-0010: Async Search Queue（非同期検索キュー）
- ADR-0012: Feedback Tool Design（ヒューマンフィードバック）

---

## 1. ケーススタディ設計

### 1.1 研究課題

**メインクエリ（英語）**:

```
What is the efficacy and safety of DPP-4 inhibitors as add-on therapy 
for type 2 diabetes patients receiving insulin therapy with HbA1c ≥7%?
```

### 1.2 クエリ選定の根拠

| 観点 | 根拠 |
|------|------|
| **専門性** | 評価者（K.S）がインクレチン関連薬（DPP-4阻害薬/GLP-1受容体作動薬）のメタ回帰分析で査読論文2本を出版済み |
| **複雑性** | 有効性（HbA1c低下）と安全性（低血糖リスク）の両面を含む多角的課題 |
| **エビデンスの存在** | PubMed、Cochrane、FDA/EMAに十分なエビデンスが存在 |
| **反証可能性** | 「インスリン投与下でもHbA1c≥7%」という条件により、議論の余地がある課題 |

### 1.3 評価基準

#### 1.3.1 情報品質（専門家評価）

| 指標 | 定義 | 評価方法 |
|------|------|----------|
| **正確性** | 医学的に正しい情報か | 薬学博士による査読 |
| **網羅性** | 重要なエビデンスを網羅しているか | 既知の主要RCT/メタアナリシスとの照合 |
| **最新性** | 2020年以降のエビデンスを含むか | 出典の発行年確認 |
| **一次資料比率** | 一次資料（原著論文、規制当局文書）の割合 | Lyraの `primary_source_ratio` 指標 |

#### 1.3.2 システム性能（定量評価）

| 指標 | 定義 | 測定方法 |
|------|------|----------|
| **収集ページ数** | 取得・処理したページ数 | `get_status` の `metrics.total_pages` |
| **有用断片数** | 抽出された関連断片数 | `get_status` の `metrics.total_fragments` |
| **収穫率** | 有用断片/取得ページ | `harvest_rate` |
| **所要時間** | タスク開始から完了まで | `metrics.elapsed_seconds` |
| **NLI精度** | エビデンス関係の正確性 | 専門家によるサンプル検証（30件、DBから決め打ち抽出） |

#### 1.3.3 比較評価（定性）

| 観点 | 評価項目 |
|------|----------|
| **透明性** | 情報源のURLと引用箇所が明示されているか |
| **検証可能性** | 主張の根拠を辿れるか |
| **プライバシー** | クエリがサーバーに送信されるか |
| **コスト** | 利用料金（Lyra: $0） |

---

## 2. 実験手順

### 2.1 事前準備

#### 2.1.1 環境構築

```bash
# 環境確認
make doctor

# Lyra環境の起動（コンテナビルドが未済なら先に make dev-build）
make dev-up

# Chrome CDPの起動
make chrome-start

# MCPサーバーの起動
make mcp
```

#### 2.1.2 商用ツールの準備

| ツール | 準備 |
|--------|------|
| **Google Deep Research** | Gemini Advanced（$20/月）のサブスクリプション |
| **ChatGPT Deep Research** | ChatGPT Pro（$200/月）のサブスクリプション |

### 2.2 実験プロトコル

#### 2.2.1 同一クエリの投入

**全ツールに同一の英語クエリを投入**:

```
What is the efficacy and safety of DPP-4 inhibitors as add-on therapy 
for type 2 diabetes patients receiving insulin therapy with HbA1c ≥7%?

Please provide:
1. Summary of clinical evidence (RCTs, meta-analyses)
2. Key efficacy metrics (HbA1c reduction, fasting glucose)
3. Safety profile (hypoglycemia risk, cardiovascular safety)
4. Regulatory status (FDA, EMA approvals)
5. Comparison with other add-on therapies (GLP-1 agonists, SGLT2 inhibitors)

Cite primary sources (original papers, FDA labels, clinical guidelines).
```

#### 2.2.2 Lyraの実行手順

**Step 1: タスク作成**

```
create_task(query="What is the efficacy and safety of DPP-4 inhibitors...")
→ task_id取得
```

**Step 2: サブクエリ設計（Cursor AI）**

Cursor AIがクエリを分解し、検索クエリを設計:

```
queue_searches(task_id, queries=[
  "DPP-4 inhibitors efficacy meta-analysis HbA1c",
  "DPP-4 inhibitors safety cardiovascular outcomes",
  "sitagliptin add-on therapy insulin-treated HbA1c 7 RCT",
  "DPP-4 inhibitors vs GLP-1 agonists comparison",
  "FDA DPP-4 inhibitors approval label",
  "EMA DPP-4 inhibitors EPAR",
  "DPP-4 inhibitors hypoglycemia risk systematic review"
])
```

**Step 3: 進捗監視**

```
get_status(task_id, wait=30)
→ 検索の進捗、収集ページ数、断片数を確認
```

**Step 4: 認証対応（必要に応じて）**

```
get_auth_queue()
→ CAPTCHAがあれば手動解決
resolve_auth(action="complete", domain="...")
```

**Step 5: エビデンス探索**

```
# 矛盾するエビデンスを確認
query_sql(sql="SELECT * FROM v_contradictions ORDER BY controversy_score DESC LIMIT 10")

# セマンティック検索で関連クレームを探索
vector_search(query="DPP-4 cardiovascular safety", target="claims", task_id=task_id)

# 完了時は get_status に evidence_summary が含まれる
get_status(task_id)
→ evidence_summary: {total_claims, total_fragments, supporting_edges, refuting_edges, ...}
```

**Step 6: レポート構成（Cursor AI）**

Cursor AIが `query_sql`/`vector_search` で取得した素材を統合してレポートを作成（ADR-0002）。

**Step 7: タスク完了**

```
stop_task(task_id, reason="completed")
```

#### 2.2.3 商用ツールの実行手順

| ツール | 手順 |
|--------|------|
| **Google Deep Research** | Gemini → 「Deep Research」モード → クエリ投入 → 生成完了まで待機 |
| **ChatGPT Deep Research** | ChatGPT Pro → 「Deep Research」モード → クエリ投入 → 生成完了まで待機 |

### 2.3 記録項目

#### 2.3.1 全ツール共通

| 項目 | 記録方法 |
|------|----------|
| 投入クエリ | テキストファイル |
| 開始時刻 | タイムスタンプ |
| 終了時刻 | タイムスタンプ |
| 生成されたレポート | PDFまたはMarkdown |
| 引用された情報源 | URLリスト |

#### 2.3.2 Lyra固有

| 項目 | 記録方法 |
|------|----------|
| Evidence Graph | `query_sql` でSQLクエリ（例: `SELECT * FROM edges WHERE ...`） |
| 検索クエリ履歴 | `get_status` の `searches` |
| メトリクス | `get_status` の `metrics`, `budget`, `evidence_summary` |
| NLI判定結果 | `query_sql` で edges テーブルをクエリ |
| 認証キュー履歴 | `query_sql` で intervention_queue テーブルをクエリ |

---

## 3. 評価方法

### 3.1 専門家評価（Ground Truth）

評価者: Shibuki Katsuya（薬学博士、メタ回帰分析専門）

#### 3.1.1 評価シート

| 評価項目 | Lyra | Google Deep Research | ChatGPT Deep Research |
|----------|------|---------------------|----------------------|
| **正確性** (1-5) | | | |
| **網羅性** (1-5) | | | |
| **最新性** (1-5) | | | |
| **一次資料比率** (%) | | | |
| **引用の検証可能性** (1-5) | | | |
| **総合評価** (1-5) | | | |

#### 3.1.2 NLI精度検証

1. **同一task_id** を対象に、DBから **決め打ちSQL** でレビュー対象エッジを30件抽出（同日比較の再現性を優先）
2. 専門家が各エッジを確認し、**訂正が必要な場合のみ** `feedback(edge_correct)` を実行（= DBには誤りだけが残る）
3. 分母は「抽出した30件」で固定
4. 分子は `nli_corrections`（抽出した30件に紐づくもの）の件数
5. 正解率の近似: `accuracy ≈ 1 - corrected/30`

補足: 「人手レビュー済み」をDBで追跡したい場合は、訂正不要のエッジにも `feedback(edge_correct)` を **同ラベルで**実行して `edges.edge_human_corrected=1` を付与する（運用コストと相談）。

```python
# NOTE: This is a conceptual snippet.
# Select 30 edges deterministically from DB (stable ordering) and review them.
```

（例）決め打ちSQL:

```sql
-- Deterministic sample of 30 Fragment->Claim edges for a task
SELECT
  e.id AS edge_id,
  e.nli_label,
  e.nli_edge_confidence,  -- NLI model output (calibrated)
  f.text_content AS premise,
  c.claim_text AS hypothesis
FROM edges e
JOIN claims c
  ON e.target_type = 'claim' AND e.target_id = c.id
LEFT JOIN fragments f
  ON e.source_type = 'fragment' AND e.source_id = f.id
WHERE c.task_id = ?
  AND e.relation IN ('supports', 'refutes', 'neutral')
ORDER BY e.created_at ASC, e.id ASC
LIMIT 30;
```

### 3.2 定量比較

| 指標 | Lyra | Google Deep Research | ChatGPT Deep Research |
|------|------|---------------------|----------------------|
| **引用数** | | | |
| **一次資料数** | | | |
| **所要時間** | | | |
| **コスト** | $0 | $20/月 | $200/月 |
| **クエリ送信先** | ローカル | Google | OpenAI |

### 3.3 定性評価

#### 3.3.1 透明性評価チェックリスト

| 項目 | Lyra | Google | ChatGPT |
|------|------|--------|---------|
| 情報源URLが明示されている | | | |
| 引用箇所が特定できる | | | |
| 検索クエリが確認できる | | | |
| 処理過程が追跡できる | | | |
| エビデンス関係が可視化されている | | | |

#### 3.3.2 再現性評価

同一クエリを1週間後に再実行し、結果の一貫性を確認。

---

## 4. 期待される結果と論文での主張

### 4.1 Lyraの想定される強み

| 観点 | 想定される結果 | 論文での主張 |
|------|---------------|-------------|
| **透明性** | 全ての情報源URLと引用箇所が追跡可能 | "Unlike black-box commercial tools, Lyra provides full traceability of evidence" |
| **プライバシー** | クエリがローカルで処理される | "Zero data transmission to external servers" |
| **コスト** | 運用コスト$0 | "Zero operational expenditure enables use in resource-constrained settings" |
| **検証可能性** | Evidence Graphで主張-根拠関係を可視化 | "Evidence graph structure enables systematic verification" |

### 4.2 Lyraの想定される限界

| 観点 | 想定される結果 | 論文での記載 |
|------|---------------|-------------|
| **網羅性** | 商用ツールより情報源が少ない可能性 | "Limitations" セクションで明記 |
| **処理速度** | 商用ツールより遅い可能性 | ローカル処理のトレードオフとして言及 |
| **NLI精度** | 専門領域で精度が低下する可能性 | "Future Work" でLoRAファインチューニングに言及 |

---

## 5. 実行スケジュール

| 日程 | タスク | 成果物 |
|------|--------|--------|
| Day 1 | 環境構築、商用ツール準備 | 実行環境 |
| Day 2 | 全ツールでクエリ実行 | 生レポート3件 |
| Day 3 | 専門家評価（正確性・網羅性） | 評価シート |
| Day 4 | NLI精度検証（30サンプル） | 精度レポート |
| Day 5 | 定量・定性比較表作成 | 比較表 |
| Day 6 | 論文セクション執筆（Validation） | ドラフト |
| Day 7 | レビュー・修正 | 最終版 |

---

## 6. 成果物

### 6.1 データセット

| ファイル | 内容 |
|----------|------|
| `case_study/input/query.txt` | 投入クエリ |
| `case_study/lyra/report.md` | Lyra生成レポート |
| `case_study/lyra/evidence_graph.json` | Evidence Graph |
| `case_study/lyra/metrics.json` | メトリクス |
| `case_study/google/report.pdf` | Google Deep Research出力 |
| `case_study/chatgpt/report.md` | ChatGPT Deep Research出力 |
| `case_study/evaluation/expert_review.xlsx` | 専門家評価シート |
| `case_study/evaluation/nli_accuracy.csv` | NLI精度検証結果 |

### 6.2 論文セクション

```
7. Validation
   7.1 Case Study: DPP-4 Inhibitors Research
       7.1.1 Research Question
       7.1.2 Experimental Setup
       7.1.3 Results
   7.2 Comparison with Commercial Tools
       7.2.1 Information Quality
       7.2.2 Transparency and Traceability
       7.2.3 Privacy and Cost
   7.3 Expert Evaluation
       7.3.1 Methodology
       7.3.2 Findings
   7.4 Limitations
```

---

## 7. リスクと対策

| リスク | 対策 |
|--------|------|
| CAPTCHAで検索がブロックされる | 複数検索エンジン（mojeek, brave等）を使用 |
| 商用ツールの仕様変更 | 実行時点の仕様を記録 |
| NLI精度が低い | Limitationsとして明記、LoRAを Future Work に |
| 情報源が古い | 検索クエリに年次制約を追加 |

---

## 更新履歴

| 日付 | 内容 |
|------|------|
| 2025-12-26 | 初版作成 |

