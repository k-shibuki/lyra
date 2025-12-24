# LoRA ファインチューニング設計書

> **Status**: DESIGN PROPOSAL（未実装）

## 1. ドキュメントの位置づけ

本ドキュメントは、NLIモデルのLoRA（Low-Rank Adaptation）ファインチューニング機能の設計書である。

| ドキュメント | 役割 | 参照 |
|-------------|------|------|
| `docs/P_EVIDENCE_SYSTEM.md` | エビデンス評価システム設計 | Phase 6（決定17）で `edge_correct`→`nli_corrections` 蓄積、計測は `calibration_metrics` |
| **`docs/R_LORA.md`**（本文書） | **LoRAファインチューニング設計** | Phase R |
| `docs/archive/IMPLEMENTATION_PLAN.md` | 実装計画書（アーカイブ） | Phase R概要 |

---

## 2. 背景と目的

### 2.1 問題

NLIモデル（DeBERTa-v3-xsmall/small）は事前学習済みモデルであり、Lyraの特定ドメイン（医薬品安全性、政策分析等）に対して最適化されていない。

**現状の課題**:
- NLIラベルの誤判定（supports/refutes/neutralの混同）
- ドメイン固有の表現への対応不足
- ユーザーによる訂正が蓄積されても、モデルに反映されない

### 2.2 解決策

**LoRA（Low-Rank Adaptation）** を使用して、蓄積された訂正サンプルからNLIモデルを軽量にファインチューニングする。

**LoRAの利点**:
- 元モデルのパラメータを凍結し、低ランク行列のみを学習
- 学習パラメータ数が1-2%に削減（70M → 0.1-1M）
- GPUメモリ使用量が半減（8-16GB → 4-8GB）
- 元モデルを壊さず、ロールバックが容易

---

## 3. LoRAの基本原理

### 3.1 通常のファインチューニング vs LoRA

```
【通常のファインチューニング】
元の重み行列 W (d × k)
    ↓ 全パラメータを更新
新しい重み行列 W' (d × k)  ← 同サイズの別モデルを保存

【LoRA】
元の重み行列 W (d × k)  ← 凍結
    +
低ランク行列 ΔW = B × A  (B: d × r, A: r × k, r << d, k)  ← これだけ学習
```

### 3.2 数学的な直感

```
元の重み行列: W ∈ ℝ^(d×k)
低ランク近似: ΔW ≈ B × A
  - B ∈ ℝ^(d×r)
  - A ∈ ℝ^(r×k)
  - r << min(d, k)  (ランク、通常 r=8 or 16)

パラメータ削減:
  - 元: d × k = 768 × 768 = 589,824
  - LoRA (r=8): d × r + r × k = 768 × 8 + 8 × 768 = 12,288
  - 削減率: 約 50分の1
```

### 3.3 図解

```
┌─────────────────────────────────────────────────────────┐
│                    通常のファインチューニング            │
│                                                          │
│   入力 ──→ [   W   ] ──→ 出力                           │
│            (全部更新)                                    │
│            70M params                                    │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│                         LoRA                             │
│                                                          │
│   入力 ──→ [   W   ] ──→ (+) ──→ 出力                   │
│            (凍結)         ↑                              │
│                     [ B × A ]                            │
│                     (これだけ学習)                        │
│                     ~0.1M params                         │
└─────────────────────────────────────────────────────────┘
```

---

## 4. メリット比較

| 観点 | 通常のファインチューニング | LoRA |
|------|---------------------------|------|
| **学習パラメータ数** | 70M (全部) | 0.1〜1M (1-2%) |
| **GPUメモリ** | 8-16GB | 4-8GB |
| **学習時間** | 数時間 | 数十分 |
| **保存サイズ** | 280MB (モデル全体) | 数MB (アダプタのみ) |
| **過学習リスク** | 高い | 低い |
| **ロールバック** | 別モデル管理 | アダプタを外すだけ |
| **複数バージョン** | ディスク圧迫 | 軽量に共存 |

---

## 5. Lyraへの適用

### 5.1 現状のアーキテクチャ

```
┌─────────────────────────────────────────────────────────┐
│                     ML Server (lyra-ml)                  │
│                                                          │
│  ┌──────────────────────────────────────────────────┐  │
│  │              NLI Model (DeBERTa-v3)              │  │
│  │                                                   │  │
│  │  Fast: nli-deberta-v3-xsmall (~70M params)       │  │
│  │  Slow: nli-deberta-v3-small (~140M params)       │  │
│  └──────────────────────────────────────────────────┘  │
│                           ↓                             │
│                     /nli エンドポイント                  │
└─────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────┐
│                    Lyra Main Server                      │
│                                                          │
│  src/filter/nli.py → ML Client → HTTP → ML Server       │
└─────────────────────────────────────────────────────────┘
```

### 5.2 LoRA適用後のアーキテクチャ

```
┌─────────────────────────────────────────────────────────┐
│                     ML Server (lyra-ml)                  │
│                                                          │
│  ┌──────────────────────────────────────────────────┐  │
│  │              NLI Model (DeBERTa-v3)              │  │
│  │                     +                             │  │
│  │               LoRA Adapter                        │  │
│  │                                                   │  │
│  │  Base: nli-deberta-v3-xsmall (凍結)              │  │
│  │  Adapter: lora-lyra-v1.bin (~2MB)                │  │
│  └──────────────────────────────────────────────────┘  │
│                           ↓                             │
│                     /nli エンドポイント                  │
│                                                          │
│  追加エンドポイント:                                     │
│  - POST /nli/adapter/load   (アダプタ読み込み)          │
│  - POST /nli/adapter/unload (アダプタ解除)              │
│  - GET  /nli/adapter/status (現在のアダプタ情報)        │
└─────────────────────────────────────────────────────────┘
```

---

## 6. ハードウェア要件

### 6.1 推論時（現状と変わらない）

| 項目 | 現状 | LoRA適用後 |
|------|------|-----------|
| GPU | オプション（CPUでも動作） | **同じ** |
| メモリ | 4-8GB | 4-8GB + 数MB |
| 変更点 | - | アダプタファイルの読み込みのみ |

**推論時のLoRAオーバーヘッドはほぼゼロ**。アダプタは元モデルにマージできる。

### 6.2 学習時（ファインチューニング実行時のみ）

| 項目 | 通常のファインチューニング | LoRA |
|------|---------------------------|------|
| GPU | **必須**（8GB以上推奨） | **必須**（4GB以上で可能） |
| メモリ | 16GB以上 | 8GB以上 |
| 時間 | 数時間 | 数十分〜1時間 |

**重要**: 学習は「訂正が溜まったときに1回だけ」実行するオフラインバッチ処理。通常運用時は不要。

### 6.3 Lyra環境での実現可能性

| 観点 | 評価 |
|------|------|
| RTX 4060 Laptop (8GB VRAM) | ✅ LoRA学習可能 |
| WSL2メモリ32GB | ✅ 十分 |
| CPU-only学習 | ⚠️ 可能だが時間がかかる（数時間〜） |

---

## 7. 実装設計

### 7.1 必要な変更

| コンポーネント | 変更内容 | 優先度 |
|---------------|---------|:------:|
| `src/ml_server/nli.py` | PEFT/LoRAライブラリでアダプタ読み込み対応 | 高 |
| `src/ml_server/main.py` | アダプタ管理エンドポイント追加 | 高 |
| `scripts/train_lora.py` | LoRA学習スクリプト（新規） | 高 |
| `config/settings.yaml` | アダプタパス設定 | 中 |
| `requirements-ml.txt` | `peft` ライブラリ追加 | 高 |

### 7.2 コード例：推論時のアダプタ読み込み

```python
# src/ml_server/nli.py
from peft import PeftModel

class NLIService:
    def __init__(self):
        self._base_model = None
        self._adapter_loaded = False
        self._adapter_path: str | None = None

    async def load_with_adapter(self, adapter_path: str | None = None):
        from transformers import AutoModelForSequenceClassification
        
        # ベースモデル読み込み
        self._base_model = AutoModelForSequenceClassification.from_pretrained(
            "cross-encoder/nli-deberta-v3-xsmall"
        )
        
        # アダプタがあれば適用
        if adapter_path:
            self._base_model = PeftModel.from_pretrained(
                self._base_model, 
                adapter_path
            )
            # 推論高速化のためマージ（オプション）
            self._base_model = self._base_model.merge_and_unload()
            self._adapter_loaded = True
            self._adapter_path = adapter_path

    async def unload_adapter(self):
        """アダプタを解除し、ベースモデルに戻す"""
        if self._adapter_loaded:
            # ベースモデルを再読み込み
            await self.load_with_adapter(adapter_path=None)
            self._adapter_loaded = False
            self._adapter_path = None
```

### 7.3 コード例：学習スクリプト

```python
# scripts/train_lora.py
from peft import LoraConfig, get_peft_model, TaskType
from transformers import Trainer, TrainingArguments, AutoModelForSequenceClassification
import sqlite3

def load_corrections_from_db(db_path: str) -> list[dict]:
    """DBからNLI訂正サンプルを取得"""
    conn = sqlite3.connect(db_path)
    cursor = conn.execute("""
        SELECT premise, hypothesis, correct_label 
        FROM nli_corrections
        WHERE used_for_training = 0
    """)
    corrections = [
        {"premise": row[0], "hypothesis": row[1], "label": row[2]}
        for row in cursor.fetchall()
    ]
    conn.close()
    return corrections

def main():
    # 訂正データをDBから取得
    corrections = load_corrections_from_db("data/lyra.db")
    if len(corrections) < 100:
        print(f"訂正サンプル不足: {len(corrections)}件（最低100件必要）")
        return
    
    # ベースモデル読み込み
    base_model = AutoModelForSequenceClassification.from_pretrained(
        "cross-encoder/nli-deberta-v3-xsmall",
        num_labels=3  # supports, refutes, neutral
    )
    
    # LoRA設定
    lora_config = LoraConfig(
        task_type=TaskType.SEQ_CLS,
        r=8,                    # ランク（小さいほど軽量）
        lora_alpha=32,
        lora_dropout=0.1,
        target_modules=["query", "value"],  # 適用する層
    )
    
    # ベースモデルにLoRAを適用
    model = get_peft_model(base_model, lora_config)
    print(f"学習パラメータ数: {model.print_trainable_parameters()}")
    
    # データセット準備（省略）
    train_dataset = prepare_dataset(corrections)
    
    # 学習
    trainer = Trainer(
        model=model,
        args=TrainingArguments(
            output_dir="./lora-output",
            num_train_epochs=3,
            per_device_train_batch_size=8,
            learning_rate=2e-4,
            warmup_steps=100,
            logging_steps=10,
            save_strategy="epoch",
        ),
        train_dataset=train_dataset,
    )
    trainer.train()
    
    # アダプタのみ保存（数MB）
    model.save_pretrained("./adapters/lora-lyra-v1")
    print("アダプタを保存しました: ./adapters/lora-lyra-v1")

if __name__ == "__main__":
    main()
```

### 7.4 APIエンドポイント設計

```yaml
# POST /nli/adapter/load
request:
  adapter_path: string  # アダプタディレクトリパス（オプション、省略時はデフォルト）
response:
  ok: boolean
  adapter_path: string | null
  message: string

# POST /nli/adapter/unload
response:
  ok: boolean
  message: string

# GET /nli/adapter/status
response:
  adapter_loaded: boolean
  adapter_path: string | null
  base_model: string
```

---

## 8. 運用フロー

### 8.1 全体フロー

```
Phase 6: 訂正履歴をDBに蓄積（nli_corrections テーブル）
    ↓
（数百件の訂正が溜まる）
    ↓
Phase R: LoRA学習を実行（オフラインバッチ）
    ↓
scripts/train_lora.py → adapters/lora-lyra-v1/
    ↓
ML Server再起動 or /nli/adapter/load
    ↓
以降の推論でアダプタ適用
    ↓
精度が悪化したら /nli/adapter/unload でロールバック
```

### 8.2 学習トリガー条件

| 条件 | 閾値 | 根拠 |
|------|------|------|
| 訂正サンプル数 | ≥100件 | 過学習防止の最低ライン |
| 訂正率 | ≥5% | 訂正が頻発している場合のみ学習 |
| 前回学習からの経過 | ≥7日 | 頻繁な再学習を防止 |

### 8.3 精度評価

| 指標 | 説明 | 閾値 |
|------|------|------|
| 検証セット精度 | ホールドアウトサンプルでの精度 | ≥0.85 |
| 訂正率の変化 | 学習前後での訂正率比較 | 減少傾向 |
| ベースラインとの比較 | アダプタなしモデルとの比較 | 改善または同等 |

---

## 9. 実装タスクリスト

### 9.1 Phase R.1: 基盤実装

| タスク | 説明 | 状態 |
|--------|------|:----:|
| R.1.1 | `peft` ライブラリを `requirements-ml.txt` に追加 | 未着手 |
| R.1.2 | `NLIService` にアダプタ読み込み機能を追加 | 未着手 |
| R.1.3 | アダプタ管理エンドポイント実装 | 未着手 |
| R.1.4 | 設定ファイル拡張（アダプタパス） | 未着手 |

### 9.2 Phase R.2: 学習スクリプト

| タスク | 説明 | 状態 |
|--------|------|:----:|
| R.2.1 | `scripts/train_lora.py` 作成 | 未着手 |
| R.2.2 | DB → Dataset 変換ロジック | 未着手 |
| R.2.3 | 検証セット分割・評価ロジック | 未着手 |
| R.2.4 | 学習ログ・メトリクス出力 | 未着手 |

### 9.3 Phase R.3: 運用機能

| タスク | 説明 | 状態 |
|--------|------|:----:|
| R.3.1 | アダプタバージョン管理 | 未着手 |
| R.3.2 | ロールバック機能 | 未着手 |
| R.3.3 | 精度監視ダッシュボード（オプション） | 未着手 |

### 9.4 Phase R.4: テスト・検証

| タスク | 説明 | 状態 |
|--------|------|:----:|
| R.4.1 | ユニットテスト（アダプタ読み込み） | 未着手 |
| R.4.2 | 統合テスト（学習→推論パイプライン） | 未着手 |
| R.4.3 | E2E検証（実データでの学習） | 未着手 |

---

## 10. 前提条件

### 10.1 Phase 6（P_EVIDENCE_SYSTEM.md）との依存関係

Phase Rを開始する前に、以下がPhase 6で完了している必要がある：

| 依存項目 | 説明 | Phase 6 タスク |
|----------|------|---------------|
| `nli_corrections` テーブル | 訂正サンプルの蓄積先（premise/hypothesisスナップショットを含み、学習の再現性を担保） | Task 6.7 |
| `feedback` ツール | 訂正入力のMCPインターフェース（3レベル対応） | Task 6.1 |
| `edge_correct` アクション | NLIラベル訂正の実装 | Task 6.4 |

### 10.2 最低要件

| 要件 | 値 | 備考 |
|------|-----|------|
| 訂正サンプル数 | ≥100件 | 学習開始の最低ライン |
| GPU | 4GB以上 | LoRA学習時のみ必要 |
| ディスク空き | 1GB以上 | アダプタ・チェックポイント保存 |

---

## 11. リスクと対策

| リスク | 影響 | 対策 |
|--------|------|------|
| 過学習 | 汎化性能の低下 | 検証セット監視、早期停止 |
| 訂正サンプルの偏り | 特定ドメインのみ改善 | サンプリング戦略の調整 |
| ベースモデル更新への追従 | 将来のモデル更新で動作しない | バージョン固定、テスト自動化 |
| 学習時間の長期化 | 運用負荷 | GPU使用、バッチサイズ調整 |

---

## 12. `calibration_metrics`（計測）との関係（Phase 6 → Phase R）

`feedback(edge_correct)` により蓄積される ground-truth は、用途が2つに分岐する（§決定17参照）:

- **LoRA（本ドキュメント）**: `nli_corrections` を教師データとして NLIモデルのラベル誤り自体を減らす
- **校正（計測）**: `calibration_metrics.evaluate` が同じ蓄積データを用いて Brier/ECE 等を算出し、改善・劣化の監査に使う

---

## 13. 関連ドキュメント

| ドキュメント | 関連 |
|-------------|------|
| `docs/P_EVIDENCE_SYSTEM.md` | Phase 6: NLI訂正サンプル蓄積 |
| `docs/archive/IMPLEMENTATION_PLAN.md` | Phase R 概要（アーカイブ） |
| `src/ml_server/nli.py` | NLIサービス実装 |
| `src/storage/schema.sql` | `nli_corrections` テーブル定義 |
