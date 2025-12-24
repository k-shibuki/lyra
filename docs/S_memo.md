# S_LORA.md 設計メモ

> **作成日**: 2025-12-24
> **更新日**: 2025-12-24
> **結論**: 方向性は正しい。ADR-0011の誤記修正と、ML実験設計の詳細化が必要。

---

## 1. ADR-0011の誤記 ✅ 修正済み

~~ADR-0011に「NLIモデル（Qwen2.5-3B）」と記載があるが、**実装はDeBERTa**。~~

→ ADR-0011 を `DeBERTa-v3-xsmall/small` に修正済み。

---

## 2. ハイパラの統一 ✅ 完了

技術的根拠に基づき統一：

| パラメータ | 統一後の値 | 根拠 |
|-----------|:----------:|------|
| alpha | 16 | r=8 の2倍が標準（[Sebastian Raschka LoRA ガイド](https://magazine.sebastianraschka.com/p/practical-tips-for-finetuning-llms)） |
| dropout | 0.1 | 小モデル（70-140M params）では高めの正則化が有効（[QLoRA論文](https://arxiv.org/abs/2305.14314)） |
| 学習トリガー閾値 | 100件 | 3クラス分類で各クラス約33件の統計的安定性 |

---

## 3. S_LORA.mdに追記すべき内容

### 3.1 訂正サンプルの品質フィルタ

```sql
-- 高確信度で誤った明確なケースのみ使用
SELECT * FROM nli_corrections
WHERE original_confidence > 0.8
  AND original_label != correct_label
```

### 3.2 バリデーション分割

```python
from sklearn.model_selection import train_test_split

train, val = train_test_split(
    corrections,
    test_size=0.2,
    stratify=[c["correct_label"] for c in corrections],
    random_state=42
)
```

- 分割比率: 80/20
- 層化: ラベル別
- リーク防止: 同一 `page_id` は同一セットに

### 3.3 target_modulesの確認

S_LORA.mdでは `["query", "value"]` と記載。DeBERTa-v3の実際のモジュール名を確認し記載する。

```python
from transformers import AutoModel
model = AutoModel.from_pretrained("cross-encoder/nli-deberta-v3-xsmall")
print([n for n, _ in model.named_modules() if "Linear" in str(type(_))])
```

### 3.4 継続学習方針

**v1方針**: 毎回、全訂正履歴で学習し直す。

データ量が少ないうちは計算コストも小さいため、複雑な継続学習手法は不要。

### 3.5 シャドー推論（事前検証）

```python
def shadow_evaluation(val_set, old_adapter, new_adapter):
    old_acc = accuracy(predict(val_set, old_adapter), val_set)
    new_acc = accuracy(predict(val_set, new_adapter), val_set)
    return {
        "old_accuracy": old_acc,
        "new_accuracy": new_acc,
        "recommend_deploy": new_acc >= old_acc - 0.02
    }
```

本番投入前にオフラインで新旧比較。2%以上の劣化は不可。

---

## 4. 次セッションでのアクション

| 優先度 | タスク | 状態 |
|:------:|--------|:----:|
| 高 | ADR-0011の「Qwen2.5-3B」→「DeBERTa-v3」に修正 | ✅ |
| 高 | ハイパラ（alpha, dropout, 閾値）を統一 | ✅ |
| 中 | S_LORA.mdに§3の内容を追記 | ⏳ |
| 低 | target_modulesの実際の名前を確認 | ⏳ |
