# ADR-0015: Adaptive Concurrency Control (Config-driven + Safe Auto-Backoff)

## Date
2025-12-25

## Status
Proposed

## Context

Lyra は `SearchQueueWorker` により複数ジョブを並列処理する（ADR-0010）。一方で、検索パイプライン内の外部/共有リソースには異なる制約があり、ワーカー数や内部fan-outを増やすと次の問題が顕在化する：

- **学術API（Semantic Scholar / OpenAlex）**:
  - `AcademicSearchProvider` / citation graph で `asyncio.gather()` による並列呼び出しが起きる
  - `config/academic_apis.yaml` に rate_limit 設定はあるが、現実装は「超過後に429でバックオフ」中心で、**超過を予防する全ワーカー横断の制御が弱い**
- **ブラウザSERP（Playwright/CDP）**:
  - `BrowserSearchProvider` は歴史的に Page を共有しやすく、並列度を上げると **同一Pageの同時操作**が発生し得る
- **ワーカー並列**:
  - ワーカー数を増やすと、上記の外部制約にぶつかりやすい（特にAPIのQPSとブラウザ資源）

ユーザー要望として、並列度を **configで調整可能**にしたい。また、可能なら **自動で最適化**したい。

## Decision

**並列度は「configで上限を決める」ことを原則とし、自動最適化は安全側（主に“下げる”）に限定する。**

### 1) Config-driven upper bounds（上限は明示的に設定）

- **Worker**:
  - `search_queue.num_workers`（例: settings.yaml）
- **Academic APIs**:
  - `academic_apis.apis.<provider>.rate_limit.max_parallel`
  - `academic_apis.apis.<provider>.rate_limit.min_interval_seconds`
- **Browser SERP**:
  - `browser.serp_max_tabs`（TabPool上限）
  - エンジン別QPS/並列は `config/engines.yaml`（engine policy）

### 2) Safe auto-backoff（自動最適化は“下げる”中心）

自動最適化は「上限を超えて加速しない」ことを保証し、以下の入力シグナルで**一時的にeffective concurrencyを下げる**：

- **Academic API**:
  - 429（Rate Limited）発生率、連続429、レイテンシ悪化
- **Browser SERP**:
  - CAPTCHA率、403率、タイムアウト率

制御の形は AIMD（Additive Increase / Multiplicative Decrease）に近いが、**Increaseは慎重**にする：

- Decrease: 429/CAPTCHAが増えたら即座に `effective_max_parallel` / `effective_max_tabs` を下げる
- Increase: 安定時間（hysteresis）経過後に 1段だけ戻す（上限は超えない）

> Note: 「自動で上げる」ことは bot検出・BANリスクがあるため、運用上は“手動で上限を上げる”のを基本とし、Autoは補助に留める。

## Consequences

### Positive

1. **スケール可能性**: 上限をconfigで段階的に上げられる（Worker/API/SERP）
2. **安全性**: Autoが暴走して規約違反・CAPTCHA増大を招きにくい
3. **運用容易性**: 環境ごとに上限を切り替えられる（ローカル/CI/本番相当）

### Negative

1. **複雑性増加**: effective concurrency 状態の管理が必要
2. **観測依存**: 自動制御の品質はメトリクス精度に依存

## Implementation Notes

- 学術APIは「リトライ」ではなく「**リクエスト直前のグローバル制御（Acquire）**」を必須にする（ADR-0013）
- ブラウザSERPは TabPool(max_tabs=1) を先に導入し、Page競合を排除してから並列度を上げる（ADR-0014）
- Auto-backoff の観測シグナルは既存メトリクス（`HTTP_ERROR_429_RATE`, `CAPTCHA_RATE` 等）を再利用し、API/SERP側の計測点を追加する

## Related

- [ADR-0010: Async Search Queue Architecture](0010-async-search-queue.md)
- [ADR-0013: Worker Resource Contention Control](0013-worker-resource-contention.md) - 学術API
- [ADR-0014: Browser SERP Resource Control](0014-browser-serp-resource-control.md) - SERP
- `config/academic_apis.yaml`, `config/settings.yaml`, `config/engines.yaml`


