# DEBUG_E2E_03: Claim抽出パイプラインの品質分析

**日付**: 2025-12-31  
**ステータス**: 分析完了 → 改善提案あり  
**関連**: DEBUG_E2E_02.md（ベイズ更新バグ修正）

---

## 1. 症状（Symptom）

DEBUG_E2E_02でベイズ更新バグを修正後、パイプライン全体の品質を分析した結果、以下の傾向が確認された：

- 学術アブストラクトからは一律5件のClaimが抽出される
- 一般Webページからは1件のみ抽出されるケースが多い
- 低信頼Claimにはmarkdownリンクや見出しがそのまま混入

### 期待状態 vs 実際状態

| 指標 | 期待 | 実際 |
|-----|------|------|
| Claim抽出数 | ソース品質に比例 | 学術=5件固定、Web=1件が多い |
| llm_claim_confidence | 0.7以上が主流 | ✅ 95%が0.7以上 |
| 低信頼Claimの内容 | 抽象的・曖昧な主張 | 前処理失敗（リンク混入等） |

---

## 2. 根本原因分析

### 原因①: Claim数制限がpromptハードコード

**場所**: `config/prompts/extract_claims.j2:13`

```jinja2
Extract 1-5 verifiable claims from the text. Prioritize claims with numbers, dates, or proper nouns.
```

- コード側にvalidation/制限なし（LLMの出力をそのまま使用）
- LLMは指示に忠実に1〜5件を出力
- 学術アブストラクトのような情報密度の高いソースでも5件で打ち切り

**影響**: 長い学術論文アブストラクトから6件以上の重要Claimがあっても、5件で打ち切られる。

### 原因②: Fragment前処理の不足

**場所**: `src/extractor/content.py:145-153`

```python
# trafilatura で抽出
extracted = trafilatura.extract(
    html,
    include_comments=False,
    include_tables=True,
    include_links=True,  # ← markdownリンクが残る
    output_format="txt",
    favor_precision=True,
)
```

**問題点**:
1. `include_links=True` によりmarkdownリンク表記が残存
2. 見出しと本文の区別が曖昧
3. 短いfragment（20文字以上なら通過）のフィルタリングが緩い

**実例（低信頼Claimの混入パターン）**:

```
# conf=0.3 - markdownリンク混入
"November 2016, [The Boston Globe](https://www.bostonglobe.com/news/..."

# conf=0.3 - ニュースリリースの見出し+日付がそのまま
"［食領域］キリンビールと筑波大学が「健康に配慮した..."
```

### 原因③: llm_claim_confidenceの品質フィルタは適切

**検証結果**: LLMは適切に判断できている

```
llm_claim_confidence 分布:
  0.3-0.5:  5件 ( 4%)  ← 前処理失敗の残骸
  0.5-0.7:  1件 ( 1%)
  0.7-0.9: 28件 (21%)
  >=0.9:   99件 (74%)  ← 大部分が高信頼
```

**結論**: 品質閾値（0.7）は妥当。問題はLLM判断ではなく、入力データの品質。

---

## 3. データ分析結果

### Fragment→Claim抽出数の分布

| 抽出数 | Fragment数 | 主なソース |
|-------|-----------|-----------|
| 1件 | 17 (27%) | 一般Web、スクラップ |
| 2件 | 0 | - |
| 3件 | 0 | - |
| 4件 | 0 | - |
| 5件 | 46 (73%) | 学術アブストラクト、政府系サイト |

**観察**: 
- 二極化している（1件 or 5件のみ）
- LLMは「5件出せ」と言われると5件出す傾向
- 情報密度の低いソースでも無理に5件出そうとはしない（良い傾向）

### ソース品質と抽出数の関係

**5件抽出されたソース例**:
- `https://epi.ncc.go.jp/can_prev/evaluation/2604.html` - 国立がん研究センター
- `https://www.mhlw.go.jp/...` - 厚生労働省
- Semantic Scholar / arXiv 学術論文

**1件抽出されたソース例**:
- `https://forum.comses.net/...` - フォーラム投稿
- `https://nonprofitquarterly.org/...` - ニュース記事の断片
- `https://www.kirinholdings.com/...` - 企業プレスリリース

---

## 4. 改善提案

### P1: Fragment前処理の強化

**修正箇所**: `src/extractor/content.py`

```python
# 提案: リンク除去オプション
extracted = trafilatura.extract(
    html,
    include_links=False,  # ← リンクを除去
    ...
)

# または後処理でmarkdownリンクを除去
import re
extracted = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', extracted)
```

**期待効果**: 低信頼Claimの主因であるリンク混入を防止

### P2: Claim数制限の動的化

**修正箇所**: `config/prompts/extract_claims.j2`

**現行**:
```jinja2
Extract 1-5 verifiable claims from the text.
```

**提案A - ソースタイプ別**:
```jinja2
{% if source_type == 'academic' %}
Extract 3-10 verifiable claims from the text.
{% else %}
Extract 1-5 verifiable claims from the text.
{% endif %}
```

**提案B - 動的指示**:
```jinja2
Extract ALL verifiable claims from the text (typically 1-10).
Only include claims that are specific and can be fact-checked.
```

**トレードオフ**:
- A: 予測可能だが、ソースタイプ判定ロジックが必要
- B: 柔軟だが、LLMが大量出力するリスク（コスト・ノイズ増）

### P3: Fragment品質ゲートの追加

**新規追加**: `src/extractor/content.py` または `src/research/pipeline.py`

```python
def is_extractable_fragment(text: str) -> bool:
    """Claim抽出に適したFragmentか判定"""
    # 最小文字数
    if len(text.strip()) < 100:
        return False
    # markdown残骸チェック
    if re.search(r'\]\([^)]+\)', text):
        return False
    # 見出しのみのチェック
    if text.count('\n') < 2 and len(text) < 200:
        return False
    return True
```

---

## 5. ユーザーの問題意識への回答

### ①「5件以上抽出すべきケースも存在するのでは？」

**回答**: YES

- 長い学術アブストラクト（300語以上）には10件以上の検証可能なClaimが含まれうる
- 現在のpromptは一律「1-5件」でハードコード
- **改善案**: P2の動的化を適用

### ②「LLMが判断できているなら品質閾値はいらないのでは？」

**回答**: NO（閾値は維持すべき）

- llm_claim_confidenceは入力データ品質を反映している
- 低信頼（<0.7）の5件は全て前処理失敗の残骸
- **閾値0.7は妥当** - LLMは「これは質が低い」と正しく判断している
- **改善点**: 閾値で弾くのではなく、そもそも低品質入力をClaim抽出に渡さない（P1, P3）

### ③「スクラップと前処理不足はどこに問題がある？」

**回答**: 2箇所

1. **trafilatura設定**: `include_links=True` でmarkdownリンクが残存
2. **Fragmentフィルタ**: 20文字以上なら通過という緩い条件

**具体例**:
```
入力Fragment: "November 2016, [The Boston Globe](https://...)"
↓ そのままLLMへ
出力Claim: "November 2016, [The Boston Globe](https://..." (conf=0.3)
```

---

## 6. 検証手順

### 前処理改善の効果確認

```bash
# 改善前のmarkdownリンク混入Claim数
sqlite3 data/lyra.db "
SELECT COUNT(*) FROM claims 
WHERE claim_text LIKE '%](http%'
"

# 改善後（P1適用後）に再実行して比較
```

### Claim数制限緩和の効果確認

```bash
# 学術ソースからの抽出数分布（P2適用前後で比較）
sqlite3 data/lyra.db "
SELECT 
  COUNT(*) as claims_per_fragment
FROM edges 
WHERE source_type='fragment' AND target_type='claim'
GROUP BY source_id
ORDER BY claims_per_fragment DESC
LIMIT 10;
"
```

---

## 7. 結論

| 問題 | 原因 | 優先度 | 対応 |
|-----|------|-------|------|
| 低品質Claim | 前処理不足 | P1 | trafilatura設定 + 後処理 |
| 5件固定 | promptハードコード | P2 | 動的化 or 上限緩和 |
| 低品質Fragment通過 | ゲート不足 | P3 | 品質フィルタ追加 |

**ベイズ更新は正常動作中**（DEBUG_E2E_02で修正済み）。残課題はClaim抽出パイプラインの入力品質改善。

---

## 8. 参照

- `docs/debug/DEBUG_E2E_02.md` - ベイズ更新バグ修正
- `config/prompts/extract_claims.j2` - Claim抽出prompt
- `src/extractor/content.py` - Fragment抽出ロジック
- `src/report/generator.py:336` - llm_claim_confidence >= 0.7 フィルタ
