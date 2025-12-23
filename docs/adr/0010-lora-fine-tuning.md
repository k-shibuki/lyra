# ADR-0010: LoRA Fine-tuning Strategy

## Status
Accepted

## Date
2025-12-22

## Context

Lyraで使用するNLIモデル（Qwen2.5-3B）は、汎用的な事前学習モデルである。以下の課題がある：

| 課題 | 詳細 |
|------|------|
| ドメイン適応 | 学術論文・技術文書への特化が不十分 |
| 誤分類 | SUPPORTSをNEUTRALと判定する等のエラー |
| ユーザー固有 | 各ユーザーの調査ドメインに最適化されていない |

フルファインチューニングには以下の問題がある：
- 数十GBのGPUメモリが必要
- 数時間〜数日の学習時間
- モデル全体の保存が必要（数GB）

## Decision

**LoRA（Low-Rank Adaptation）によるパラメータ効率的なファインチューニングを採用する。**

### LoRAの選択理由

| 観点 | LoRA | フル FT |
|------|------|---------|
| メモリ | 数GB | 数十GB |
| 学習時間 | 数分〜数時間 | 数時間〜数日 |
| アダプタサイズ | 数MB | 数GB |
| 複数アダプタ | 可能 | 困難 |

### アーキテクチャ

```
ベースモデル（Qwen2.5-3B）
    │
    ├── LoRA Adapter: 一般NLI改善
    │
    ├── LoRA Adapter: 学術ドメイン
    │
    └── LoRA Adapter: ユーザー固有（フィードバックから学習）
```

### フィードバック駆動学習

ユーザーのフィードバック（ADR-0012参照）からLoRAアダプタを学習：

```python
# フィードバックデータの収集
feedback_data = [
    {
        "premise": "論文Aの主張...",
        "hypothesis": "ユーザーの仮説...",
        "correct_label": "SUPPORTS",  # ユーザー訂正
        "original_label": "NEUTRAL"   # モデル誤判定
    },
    ...
]

# LoRA学習（数十〜数百サンプルで効果あり）
adapter = train_lora(
    base_model="qwen2.5-3b",
    data=feedback_data,
    rank=8,
    alpha=16
)
```

### 学習パラメータ

| パラメータ | 値 | 理由 |
|------------|-----|------|
| rank (r) | 8 | メモリ効率と性能のバランス |
| alpha | 16 | r の2倍が推奨 |
| dropout | 0.05 | 過学習防止 |
| target_modules | q_proj, v_proj | Attentionレイヤーのみ |

### アダプタ管理

```
~/.lyra/
  └── adapters/
      ├── base_nli_v1.safetensors      # 基本NLI改善
      ├── academic_v1.safetensors       # 学術ドメイン
      └── user_feedback_v3.safetensors  # フィードバック学習
```

### MCPツール統合

```python
# calibrateツールでLoRA学習をトリガー
await call_tool("calibrate", {
    "task_id": "task_xxx",
    "source": "feedback",  # フィードバックから学習
    "min_samples": 50      # 最低サンプル数
})

# calibrate_rollbackで以前のアダプタに戻す
await call_tool("calibrate_rollback", {
    "task_id": "task_xxx",
    "version": "v2"
})
```

### 学習トリガー条件

| 条件 | 閾値 | 理由 |
|------|------|------|
| フィードバック蓄積 | 50件以上 | 統計的有意性 |
| 誤判定率 | 10%以上 | 改善の必要性 |
| ドメイン変更 | ユーザー指定 | 新ドメイン適応 |

## Consequences

### Positive
- **効率的**: 数MBのアダプタで性能改善
- **高速**: 数分〜数時間で学習完了
- **可逆**: ロールバックでいつでも元に戻せる
- **個人最適化**: ユーザーの調査ドメインに適応

### Negative
- **学習品質**: フィードバック品質に依存
- **複雑性**: アダプタ管理のオーバーヘッド
- **互換性**: Ollamaのアダプタサポートに依存

## Alternatives Considered

| Alternative | Pros | Cons | 判定 |
|-------------|------|------|------|
| フルファインチューニング | 最高性能 | リソース過大 | 却下 |
| プロンプトチューニング | 軽量 | 効果限定的 | 却下 |
| Adapter Tuning | LoRA類似 | LoRAより効率悪い | 却下 |
| QLoRA | 超軽量 | 品質低下リスク | 将来検討 |

## References
- `docs/R_LORA.md`（参照）
- `src/calibration/lora_trainer.py` - LoRA学習実装
- `src/calibration/adapter_manager.py` - アダプタ管理
- ADR-0012: Feedback Tool Design
