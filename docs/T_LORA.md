# LoRA ファインチューニング設計書

> **Status**: DESIGN PROPOSAL（未実装）
>
> **Related ADRs**:
> - [ADR-0011: LoRA Fine-tuning Strategy](adr/0011-lora-fine-tuning.md) - LoRA採用決定、MCPツール化却下
> - [ADR-0012: Feedback Tool Design](adr/0012-feedback-tool-design.md) - `feedback(edge_correct)` による訂正サンプル蓄積

## 1. ドキュメントの位置づけ

本ドキュメントは、NLIモデルのLoRA（Low-Rank Adaptation）ファインチューニング機能の設計書である。

| ドキュメント | 役割 | 参照 |
|-------------|------|------|
| `docs/archive/P_EVIDENCE_SYSTEM.md` | エビデンス評価システム設計（アーカイブ） | Phase 6（決定17）で `edge_correct`→`nli_corrections` 蓄積、計測は `calibration_metrics` |
| **`docs/T_LORA.md`**（本文書） | **LoRAファインチューニング設計** | Phase S |
| `docs/archive/IMPLEMENTATION_PLAN.md` | 実装計画書（アーカイブ） | Phase R概要 |
| [ADR-0011](adr/0011-lora-fine-tuning.md) | LoRAファインチューニング戦略（ADR） | LoRA採用理由、MCPツール化却下 |
| [ADR-0012](adr/0012-feedback-tool-design.md) | フィードバックツール設計（ADR） | `feedback(edge_correct)` 設計 |

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
│  │  Model: nli-deberta-v3-small (GPU)               │  │
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
│  │  Base: nli-deberta-v3-small (GPU必須)            │  │
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
| GPU | **必須**（NVIDIA GPU + CUDA。CPUはサポートしない） | **同じ** |
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
| CPU-only学習 | 対象外（本プロジェクトはGPU必須） |

---

## 7. 実装設計

### 7.1 必要な変更

| コンポーネント | 変更内容 | 優先度 |
|---------------|---------|:------:|
| `src/ml_server/nli.py` | PEFT/LoRAライブラリでアダプタ読み込み対応 | 高 |
| `src/ml_server/main.py` | アダプタ管理エンドポイント追加 | 高 |
| `scripts/train_lora.py` | LoRA学習スクリプト（新規） | 高 |
| `config/settings.yaml` | アダプタパス設定 | 中 |
| `pyproject.toml` | `peft` ライブラリを ml extra に追加 | 高 |

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
            "cross-encoder/nli-deberta-v3-small"
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
    """DBからNLI訂正サンプルを取得（v1: 全訂正履歴を使用）"""
    conn = sqlite3.connect(db_path)
    cursor = conn.execute("""
        SELECT premise, hypothesis, correct_label 
        FROM nli_corrections
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
        "cross-encoder/nli-deberta-v3-small",
        num_labels=3  # supports, refutes, neutral
    )
    
    # LoRA設定
    lora_config = LoraConfig(
        task_type=TaskType.SEQ_CLS,
        r=8,                    # ランク（小さいほど軽量）
        lora_alpha=16,          # r の2倍が標準
        lora_dropout=0.1,       # 小モデルでは高めの正則化が有効
        target_modules=["query", "value"],  # DeBERTa-v3 の Attention レイヤー
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

### 7.5 MCPツール化の検討結果

**決定: MCPツール化は却下。スクリプト運用を採用。**

#### 却下理由

| 観点 | MCPツール | スクリプト |
|------|----------|-----------|
| **処理時間** | 数十分〜1時間（タイムアウトリスク） | 問題なし |
| **GPU占有** | 推論との競合 | 専有可能 |
| **手動確認** | 困難 | シャドー評価の結果を人間が確認 |
| **試行錯誤** | パラメータ固定 | ハイパラ調整が柔軟 |

#### 採用アーキテクチャ

```
┌─────────────────────────────────────────────────────────────────┐
│                      LoRA運用フロー                              │
├─────────────────────────────────────────────────────────────────┤
│  【スクリプト（計算処理）】                                        │
│    scripts/train_lora.py                                        │
│      ├─ nli_correctionsからデータ取得                            │
│      ├─ 品質フィルタ・バリデーション分割（§9.1-9.2）              │
│      ├─ LoRA学習                                                │
│      ├─ シャドー評価（§9.5）                                     │
│      └─ アダプタ保存                                             │
│                                                                   │
│  【手動確認】                                                     │
│    シャドー評価の結果を確認（2%以上劣化なら不採用）                │
│                                                                   │
│  【アダプタ適用】                                                 │
│    ML Server再起動 or /nli/adapter/load                          │
│                                                                   │
│  【効果確認（任意）】                                              │
│    calibration_metrics(get_stats) で精度監視                     │
└─────────────────────────────────────────────────────────────────┘
```

#### calibration_metricsとの関係

| 用途 | 担当 | 説明 |
|------|------|------|
| **学習実行** | `scripts/train_lora.py` | LoRA学習（オフライン） |
| **評価実行** | `scripts/evaluate_calibration.py` | Brier/ECE計算（オフライン） |
| **状態確認** | `calibration_metrics(get_stats)` | MCPツール（軽量） |
| **履歴参照** | `calibration_metrics(get_evaluations)` | MCPツール（軽量） |

**注**: `calibration_metrics`の`evaluate`および`get_diagram_data`アクションは、ADR-0010で削除済み。評価・可視化は`scripts/evaluate_calibration.py`で実施。

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

### 8.4 アダプタ切り替え時の排他制御

**方針**: `/nli/adapter/load` および `/nli/adapter/unload` 実行中は、新規推論リクエストを**ブロック（排他ロック）**する。

**実装:**
```python
# src/ml_server/nli.py
class NLIService:
    def __init__(self):
        self._model_lock = asyncio.Lock()  # モデル操作の排他制御
    
    async def predict(self, pairs: list) -> list:
        async with self._model_lock:
            return await self._predict_impl(pairs)
    
    async def load_adapter(self, adapter_path: str):
        async with self._model_lock:
            # モデル状態を変更（推論リクエストは待機）
            await self._load_adapter_impl(adapter_path)
```

**理由:**
- モデル状態の不整合を防止（load中に旧モデルと新モデルが混在するリスク）
- 推論結果の一貫性を保証
- シンプルな実装で安全性を確保

**トレードオフ:**
- load/unload中は推論がブロックされる（数秒〜数十秒）
- 運用上は「推論が少ない時間帯にload」を推奨

---

## 9. ML実験設計の詳細

### 9.1 nli_corrections の設計方針

**`nli_corrections` には訂正のみを記録する。**

- **記録条件**: `predicted_label != correct_label`（予測が間違っていた場合のみ）
- **記録しない**: 予測が正しかった場合（学習データの偏り防止）
- **理由**: 正解サンプルは元モデルが既に学習済みであり、訂正サンプルに集中することで効率的な学習が可能

### 9.1.1 訂正サンプルの品質フィルタ

学習効率を高めるため、高確信度で誤った明確なケースを優先：

```sql
-- 高確信度で誤った明確なケースのみ使用
SELECT * FROM nli_corrections
WHERE predicted_confidence > 0.8
```

**注**: `nli_corrections` は訂正のみを記録するため、`predicted_label != correct_label` のフィルタは不要（テーブル設計で保証）。

### 9.2 バリデーション分割

```python
from sklearn.model_selection import train_test_split

train, val = train_test_split(
    corrections,
    test_size=0.2,
    stratify=[c["correct_label"] for c in corrections],
    random_state=42
)
```

- **分割比率**: 80/20
- **層化**: ラベル別（supports/refutes/neutralの比率を維持）
- **リーク防止**: 同一ページ由来のサンプルは同一セットに配置
  - JOIN経路: `nli_corrections.edge_id → edges.source_id → fragments.page_id`

```sql
-- リーク防止用: サンプルごとのpage_id取得
SELECT nc.*, f.page_id
FROM nli_corrections nc
JOIN edges e ON nc.edge_id = e.id
JOIN fragments f ON e.source_id = f.id
WHERE e.source_type = 'fragment'
```

### 9.3 target_modulesの確認

T_LORA.md §7.3では `["query", "value"]` と記載。DeBERTa-v3の実際のモジュール名はPhase R実装時に確認すること：

```python
from transformers import AutoModel
model = AutoModel.from_pretrained("cross-encoder/nli-deberta-v3-small")
print([n for n, m in model.named_modules() if "Linear" in str(type(m))])
```

### 9.4 継続学習方針

#### v1方針（初期）: 全履歴で毎回学習

データ量が少ないうちは計算コストも小さいため、毎回全訂正履歴で学習し直す。

```sql
-- v1: 全サンプルを使用
SELECT premise, hypothesis, correct_label FROM nli_corrections
```

#### v2方針（将来）: 増分学習

訂正サンプルが数千件を超えた場合、増分学習に移行する。

```sql
-- v2: 未学習サンプルのみ使用
SELECT premise, hypothesis, correct_label 
FROM nli_corrections
WHERE trained_adapter_id IS NULL
   OR trained_adapter_id < ?  -- 現在のアダプタIDより小さい
```

**v2に必要なスキーマ（実装済み）**:

```sql
-- アダプタ管理テーブル（新規）
CREATE TABLE IF NOT EXISTS adapters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    version_name TEXT NOT NULL,           -- "v1", "v1.1", "v2" 等
    adapter_path TEXT NOT NULL,           -- "adapters/lora-v1/"
    base_model TEXT NOT NULL,             -- "cross-encoder/nli-deberta-v3-small"
    samples_used INTEGER NOT NULL,        -- 学習に使用したサンプル数
    brier_before REAL,                    -- 学習前Brierスコア
    brier_after REAL,                     -- 学習後Brierスコア
    shadow_accuracy REAL,                 -- シャドー評価精度
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    is_active BOOLEAN DEFAULT 0           -- 現在ML Serverで使用中か
);

-- nli_corrections に学習済みアダプタIDを追加
ALTER TABLE nli_corrections ADD COLUMN trained_adapter_id INTEGER 
    REFERENCES adapters(id);
-- NULL = 未学習、数値 = adapters.id
```

**使用例**:
```sql
-- v2増分学習: 未学習 or 古いアダプタで学習済みのサンプルのみ取得
SELECT nc.premise, nc.hypothesis, nc.correct_label
FROM nli_corrections nc
WHERE nc.trained_adapter_id IS NULL
   OR nc.trained_adapter_id < ?;  -- 現在のアダプタIDより小さい

-- 学習完了後: サンプルに学習済みフラグを設定
UPDATE nli_corrections 
SET trained_adapter_id = ? 
WHERE id IN (...);
```

| 方針 | トリガー条件 | 計算コスト | スキーマ変更 |
|------|-------------|-----------|-------------|
| v1 | サンプル数 < 1000 | 低 | 不要（adaptersテーブルは使用） |
| v2 | サンプル数 ≥ 1000 | 中 | `trained_adapter_id`を活用 |

### 9.5 シャドー推論（事前検証）

本番投入前にオフラインで新旧アダプタを比較し、劣化がないことを確認する：

```python
def shadow_evaluation(val_set, old_adapter, new_adapter):
    """新アダプタの事前評価。2%以上の劣化は不可。"""
    old_acc = accuracy(predict(val_set, old_adapter), val_set)
    new_acc = accuracy(predict(val_set, new_adapter), val_set)
    return {
        "old_accuracy": old_acc,
        "new_accuracy": new_acc,
        "recommend_deploy": new_acc >= old_acc - 0.02  # 2%劣化閾値
    }
```

---

## 10. 実装タスクリスト

### 10.1 Phase 1: 基盤実装

| タスク | 説明 | 状態 |
|--------|------|:----:|
| R.1.1 | `peft` ライブラリを `pyproject.toml` の ml extra に追加 | 未着手 |
| R.1.2 | `NLIService` にアダプタ読み込み機能を追加 | 未着手 |
| R.1.3 | アダプタ管理エンドポイント実装 | 未着手 |
| R.1.4 | 設定ファイル拡張（アダプタパス） | 未着手 |
| R.1.5 | アダプタload/unload時の排他制御実装（§8.4） | 未着手 |

### 10.2 Phase 2: 学習・評価スクリプト

**前提作業（R.2.1開始前に実施）:**
- [ ] `target_modules` の事前確認（DeBERTa-v3のLinear層名取得）
  ```python
  from transformers import AutoModel
  model = AutoModel.from_pretrained("cross-encoder/nli-deberta-v3-small")
  print([n for n, m in model.named_modules() if "Linear" in str(type(m))])
  ```
  → 結果に基づき §7.3 / §9.3 の `target_modules` を更新

| タスク | 説明 | 状態 |
|--------|------|:----:|
| R.2.1 | `scripts/train_lora.py` 作成 | 未着手 |
| R.2.2 | DB → Dataset 変換ロジック（§9.1-9.2） | 未着手 |
| R.2.3 | 検証セット分割・評価ロジック | 未着手 |
| R.2.4 | 学習ログ・メトリクス出力 | 未着手 |
| R.2.5 | `scripts/evaluate_calibration.py` 作成（※1） | 未着手 |

**※1**: ADR-0010で`calibration_metrics`から`evaluate`/`get_diagram_data`を削除済み。このスクリプトが評価機能を担う。

**※スキーマ変更**: `adapters`テーブルおよび`nli_corrections.trained_adapter_id`はADR-0010で追加済み。

### 10.3 Phase 3: 運用機能

| タスク | 説明 | 状態 |
|--------|------|:----:|
| R.3.1 | アダプタバージョン管理 | 未着手 |
| R.3.2 | ロールバック機能 | 未着手 |
| R.3.3 | 精度監視ダッシュボード（オプション） | 未着手 |

### 10.4 Phase 4: テスト・検証

| タスク | 説明 | 状態 |
|--------|------|:----:|
| R.4.1 | ユニットテスト（アダプタ読み込み） | 未着手 |
| R.4.2 | 統合テスト（学習→推論パイプライン） | 未着手 |
| R.4.3 | E2E検証（実データでの学習） | 未着手 |

---

## 11. 前提条件

| 要件 | 値 | 備考 |
|------|-----|------|
| 訂正サンプル数 | ≥100件 | 学習開始の最低ライン |
| GPU | 4GB以上 | LoRA学習時のみ必要 |
| ディスク空き | 1GB以上 | アダプタ・チェックポイント保存 |

---

## 12. リスクと対策

| リスク | 影響 | 対策 |
|--------|------|------|
| 過学習 | 汎化性能の低下 | 検証セット監視、早期停止 |
| 訂正サンプルの偏り | 特定ドメインのみ改善 | サンプリング戦略の調整 |
| ベースモデル更新への追従 | 将来のモデル更新で動作しない | バージョン固定、テスト自動化 |
| 学習時間の長期化 | 運用負荷 | GPU使用、バッチサイズ調整 |

---

## 13. `calibration_metrics`（計測）との関係

`feedback(edge_correct)` により蓄積される ground-truth は、用途が2つに分岐する（§決定17参照）:

- **LoRA（本ドキュメント）**: `nli_corrections` を教師データとして NLIモデルのラベル誤り自体を減らす
- **校正（計測）**: `scripts/evaluate_calibration.py` が同じ蓄積データを用いて Brier/ECE 等を算出し、改善・劣化の監査に使う

---

## 14. 関連ドキュメント

| ドキュメント | 関連 |
|-------------|------|
| `docs/archive/P_EVIDENCE_SYSTEM.md` | Phase 6: NLI訂正サンプル蓄積（アーカイブ） |
| `docs/archive/IMPLEMENTATION_PLAN.md` | Phase R 概要（アーカイブ） |
| `src/ml_server/nli.py` | NLIサービス実装 |
| `src/storage/schema.sql` | `nli_corrections` テーブル定義 |
