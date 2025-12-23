# ADR-0011: LoRA Fine-tuning Strategy

## Date
2025-12-20

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

### MCPツール統合（計画）

**注**: 以下はPhase R実装時の計画。現在の`calibration_metrics`ツールは確率キャリブレーションの評価のみを行い、LoRA学習トリガーは未実装。

```python
# 将来: LoRA学習をトリガー（Phase R）
await call_tool("train_lora", {  # ツール名は未確定
    "source": "nli_corrections",
    "min_samples": 100
})

# calibration_rollbackで以前のアダプタに戻す
await call_tool("calibration_rollback", {
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

## Implementation Status

**Note**: 本ADRで記載されたLoRA学習機能は**Phase R（将来）** で実装予定である。
詳細なタスクリストは `docs/R_LORA.md` を参照。

### 現状（実装済み）
- `feedback(edge_correct)` でNLI訂正サンプルを `nli_corrections` テーブルに蓄積
- `calibration_metrics` ツールで確率キャリブレーション（Platt Scaling/Temperature Scaling）を評価可能
- `calibration_rollback` ツールでパラメータのロールバック可能

### 前提条件（Phase 6）
LoRA学習を開始するには、以下が必要：
- `nli_corrections` テーブルに100件以上のサンプル蓄積
- `feedback` ツールが運用されている状態

### 計画（未実装）
| タスク | 内容 | 状態 |
|--------|------|:----:|
| R.1.x | PEFT/LoRAライブラリ統合 | 未着手 |
| R.2.x | 学習スクリプト作成 | 未着手 |
| R.3.x | アダプタバージョン管理 | 未着手 |
| R.4.x | テスト・検証 | 未着手 |

## References
- `docs/R_LORA.md` - LoRAファインチューニング詳細設計
- `docs/P_EVIDENCE_SYSTEM.md` - Phase 6: NLI訂正サンプル蓄積
- `src/utils/calibration.py` - 確率キャリブレーション実装
- `src/storage/schema.sql` - `nli_corrections`, `calibration_evaluations`テーブル
- `src/mcp/server.py` - `calibration_metrics`, `calibration_rollback` MCPツール
- ADR-0012: Feedback Tool Design
