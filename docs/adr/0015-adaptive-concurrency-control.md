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

### 2) リソース別の自動制御戦略

リソースごとにリスク特性が異なるため、自動制御の方針を分ける：

#### Academic API: 自動増減OK

`AcademicAPIRateLimiter`（ADR-0013）がリクエスト直前にグローバルQPS制限を強制するため、並列度を上げてもレート制限は確実に遵守される。

- **Decrease**: 429発生時に即座に `effective_max_parallel` を下げる
- **Increase**: 安定時間（例: 60秒）経過後に1段戻す（config上限まで）
- **リスク**: 低（レート制限で保護）

#### Browser SERP: 保守的に（自動増加なし）

bot検出・CAPTCHAはレート制限では防げない。エンジン側のヒューリスティクスに依存するため予測困難。

- **Decrease**: CAPTCHA/403率上昇時に `effective_max_tabs` を下げる
- **Increase**: **手動のみ**（config変更で段階的に上げる）
- **リスク**: 中〜高（bot検出でBANリスク）

> Note: ブラウザSERPは `max_tabs=1` で開始し、CAPTCHA率・成功率を観測しながら手動で上限を調整する運用を推奨。

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


