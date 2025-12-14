# Pydantic移行状況レポート

## 概要

コードベース全体での`dataclass`から`Pydantic BaseModel`への移行状況を調査した結果。

## 移行方針

- **モジュール間のデータ受け渡し**: Pydanticモデルを使用（型安全性・バリデーション）
- **内部実装**: dataclassも可（軽量・シンプル）
- **設定・設定ファイル**: Pydanticモデルを使用（バリデーション・ドキュメント化）

## モジュール別移行状況

### ✅ 完全移行済み

#### `src/crawler/profile_audit.py`
- **状態**: ✅ 完全移行済み
- **モデル**: `FingerprintData`, `DriftInfo`, `AuditResult` (BaseModel)
- **理由**: モジュール間のデータ受け渡しに使用

#### `src/utils/config.py`
- **状態**: ✅ 完全移行済み
- **モデル**: すべての設定クラス (BaseModel)
- **理由**: 設定ファイルのバリデーション・型安全性

#### `src/utils/domain_policy.py`
- **状態**: ✅ 部分移行済み
- **Pydantic**: `DefaultPolicySchema`, `AllowlistEntrySchema`, `GraylistEntrySchema`, `PolicyBoundsSchema`, `DomainPolicyConfigSchema` (BaseModel)
- **dataclass**: `DomainPolicy` (内部実装用)

#### `src/utils/schemas.py`
- **状態**: ✅ 完全移行済み
- **モデル**: `AuthSessionData`, `StartSessionRequest` (BaseModel)
- **理由**: モジュール間のデータ受け渡し

#### `src/search/engine_config.py`
- **状態**: ✅ 部分移行済み
- **Pydantic**: `EngineDefinitionSchema`, `OperatorMappingSchema` (BaseModel)
- **dataclass**: 内部実装用のクラス

#### `src/search/parser_config.py`
- **状態**: ✅ 完全移行済み
- **モデル**: `SelectorSchema`, `CaptchaPatternSchema`, `EngineParserSchema`, `ParserSettingsSchema` (BaseModel)
- **理由**: 設定ファイルのバリデーション

#### `src/ml_server/models.py`, `src/ml_server/schemas.py`
- **状態**: ✅ 完全移行済み
- **モデル**: すべてのAPIリクエスト/レスポンスモデル (BaseModel)
- **理由**: APIの型安全性・バリデーション

---

### 🟡 部分移行済み

#### `src/crawler/`
- **Pydantic**: `profile_audit.py`のみ
- **dataclass**: 18ファイルで使用
  - `session_transfer.py`: `CookieData`, `SessionData`, `TransferResult`
  - `browser_provider.py`: 複数のdataclass
  - `wayback.py`, `human_behavior.py`, `sec_fetch.py`, `stealth.py`, `undetected.py`, `dns_policy.py`, `browser_archive.py`, `bfs.py`, `crt_transparency.py`, `rdap_whois.py`, `robots.py`, `site_search.py`, `ipv6_manager.py`, `http3_policy.py`, `entity_integration.py`
- **推奨**: モジュール間のデータ受け渡しに使用される`session_transfer.py`を優先的に移行

#### `src/search/`
- **Pydantic**: `engine_config.py`, `parser_config.py`
- **dataclass**: 6ファイルで使用
  - `provider.py`: `SearchResult`, `SearchResponse`
  - `search_api.py`: 複数のdataclass
  - `parser_diagnostics.py`, `search_parsers.py`, `ab_test.py`, `browser_search_provider.py`
- **推奨**: `provider.py`の`SearchResult`, `SearchResponse`を優先的に移行（モジュール間のデータ受け渡し）

#### `src/utils/`
- **Pydantic**: `config.py`, `domain_policy.py`, `schemas.py`
- **dataclass**: 10ファイルで使用
  - `calibration.py`: `CalibrationSample`, `CalibrationParams`
  - `secure_logging.py`, `circuit_breaker.py`, `backoff.py`, `api_retry.py`, `notification_provider.py`, `lifecycle.py`, `metrics.py`, `replay.py`, `policy_engine.py`
- **推奨**: モジュール間のデータ受け渡しに使用されるものを優先的に移行

---

### 🔴 未移行（dataclassのみ）

#### `src/filter/`
- **状態**: 🔴 すべてdataclass
- **ファイル**: 7ファイル
  - `claim_decomposition.py`: `AtomicClaim`, `DecompositionResult`
  - `source_verification.py`, `llm_security.py`, `provider.py`, `claim_timeline.py`, `temporal_consistency.py`, `deduplication.py`
- **推奨**: モジュール間のデータ受け渡しに使用される`provider.py`のモデルを優先的に移行

#### `src/research/`
- **状態**: 🔴 すべてdataclass
- **ファイル**: 7ファイル
  - `state.py`: `SearchState`, `TaskState`, `ExplorationState`
  - `context.py`, `refutation.py`, `pipeline.py`, `ucb_allocator.py`, `executor.py`, `pivot.py`
- **推奨**: `state.py`の`SearchState`, `TaskState`, `ExplorationState`を優先的に移行（モジュール間のデータ受け渡し）

#### `src/storage/`
- **状態**: 🔴 すべてdataclass
- **ファイル**: `entity_kb.py`
- **モデル**: `NormalizedAddress`, `EntityRecord`, `EntityAlias`
- **推奨**: モジュール間のデータ受け渡しに使用される場合は移行

#### `src/scheduler/`
- **状態**: 🔴 すべてdataclass
- **ファイル**: `budget.py`
- **モデル**: `TaskBudget`
- **推奨**: モジュール間のデータ受け渡しに使用される場合は移行

#### `src/extractor/`
- **状態**: 🔴 すべてdataclass
- **ファイル**: `page_classifier.py`, `quality_analyzer.py`
- **推奨**: モジュール間のデータ受け渡しに使用される場合は移行

#### `src/mcp/`
- **状態**: 🔴 すべてdataclass
- **ファイル**: `response_meta.py`, `response_sanitizer.py`
- **推奨**: APIレスポンスの型安全性のため移行を検討

#### `src/report/`
- **状態**: 🔴 すべてdataclass
- **ファイル**: `chain_of_density.py`
- **推奨**: モジュール間のデータ受け渡しに使用される場合は移行

---

## 移行優先度

### 🔴 高優先度（モジュール間のデータ受け渡し）

1. **`src/crawler/session_transfer.py`**
   - `CookieData`, `SessionData`, `TransferResult`
   - BrowserFetcher ↔ HTTPFetcher間のデータ受け渡し

2. **`src/search/provider.py`**
   - `SearchResult`, `SearchResponse`
   - SearchProvider → ResearchPipeline間のデータ受け渡し

3. **`src/research/state.py`**
   - `SearchState`, `TaskState`, `ExplorationState`
   - ResearchPipeline → MCP Server間のデータ受け渡し

4. **`src/filter/provider.py`**
   - `LLMResponse`, `EmbeddingResponse`, `ModelInfo`
   - FilterProvider → ResearchPipeline間のデータ受け渡し

### 🟡 中優先度（設定・設定ファイル）

1. **`src/utils/calibration.py`**
   - `CalibrationSample`, `CalibrationParams`
   - 設定ファイルのバリデーション

2. **`src/scheduler/budget.py`**
   - `TaskBudget`
   - 設定との統合

### 🟢 低優先度（内部実装のみ）

- モジュール内部でのみ使用されるdataclassは移行不要
- パフォーマンスが重要な場合はdataclassのままでも可

---

## 移行統計

| モジュール | Pydantic | dataclass | 移行率 |
|----------|----------|-----------|--------|
| `crawler` | 1ファイル | 18ファイル | 5% |
| `search` | 2ファイル | 6ファイル | 25% |
| `filter` | 0ファイル | 7ファイル | 0% |
| `research` | 0ファイル | 7ファイル | 0% |
| `utils` | 3ファイル | 10ファイル | 23% |
| `storage` | 0ファイル | 1ファイル | 0% |
| `scheduler` | 0ファイル | 1ファイル | 0% |
| `extractor` | 0ファイル | 2ファイル | 0% |
| `mcp` | 0ファイル | 2ファイル | 0% |
| `ml_server` | 2ファイル | 0ファイル | 100% |
| `report` | 0ファイル | 1ファイル | 0% |
| **合計** | **8ファイル** | **55ファイル** | **13%** |

---

## 技術的なベストプラクティス

### Pydantic vs dataclass の使い分け

#### Pydantic BaseModel を使うべきケース

1. **モジュール間のデータ受け渡し（契約の明確化）**
   - ✅ 複数のモジュールでインポートされる
   - ✅ 関数の引数・戻り値として使用される
   - ✅ 型安全性とバリデーションが必要
   - ✅ エラーメッセージが重要（開発効率）

2. **設定・設定ファイル（バリデーション）**
   - ✅ YAML/JSONから読み込む設定
   - ✅ バリデーションルールが必要（範囲チェック、必須フィールド）
   - ✅ 設定のドキュメント化が必要

3. **APIリクエスト/レスポンス（型安全性）**
   - ✅ HTTP APIのリクエスト/レスポンス
   - ✅ MCPツールの引数/戻り値
   - ✅ JSONスキーマ生成が必要

4. **外部データの受け取り（信頼できない入力）**
   - ✅ ユーザー入力
   - ✅ 外部APIからのレスポンス
   - ✅ ファイルからの読み込み

#### dataclass を使うべきケース

1. **内部実装のみ（パフォーマンス重視）**
   - ✅ 単一モジュール内でのみ使用
   - ✅ 高頻度でインスタンス化される（パフォーマンスが重要）
   - ✅ バリデーション不要（既に検証済み）

2. **シンプルなデータ構造（軽量性）**
   - ✅ バリデーションルールが不要
   - ✅ 標準ライブラリのみで完結したい
   - ✅ 依存関係を最小化したい

3. **既存コードとの互換性**
   - ✅ 既存のdataclassが十分に機能している
   - ✅ 変更コストが高い

### パフォーマンス比較

| 項目 | dataclass | Pydantic BaseModel |
|------|-----------|-------------------|
| **インスタンス化速度** | ⚡ 高速（約10-50倍速） | 🐢 遅い（バリデーション実行） |
| **メモリ使用量** | 💾 少ない | 💾💾 多い（バリデーター情報） |
| **バリデーション** | ❌ なし | ✅ 自動バリデーション |
| **型安全性** | ⚠️ 限定的（型ヒントのみ） | ✅ 強い（実行時チェック） |
| **エラーメッセージ** | ❌ なし | ✅ 詳細なエラーメッセージ |
| **JSONスキーマ生成** | ❌ 手動実装が必要 | ✅ 自動生成 |
| **依存関係** | ✅ 標準ライブラリ | ❌ 外部依存（pydantic） |

### 実測例（参考）

```python
# dataclass: 約0.1μs/インスタンス化
# Pydantic: 約5-10μs/インスタンス化（バリデーションあり）
# Pydantic (validate=False): 約1-2μs/インスタンス化
```

**結論**: 高頻度でインスタンス化される内部実装では、dataclassの方が10-50倍高速。

### 推奨される使い分け

#### ✅ 推奨: モジュール間のデータ受け渡しはPydantic

```python
# ✅ Good: モジュール間のデータ受け渡し
class SearchResult(BaseModel):  # Pydantic
    url: str = Field(..., description="Result URL")
    title: str = Field(..., description="Result title")
    
# 理由: 型安全性、バリデーション、エラーメッセージが重要
```

#### ✅ 推奨: 内部実装はdataclass

```python
# ✅ Good: 内部実装のみ
@dataclass
class InternalState:  # dataclass
    counter: int = 0
    last_update: float = 0.0
    
# 理由: パフォーマンス、軽量性が重要
```

#### ⚠️ 注意: 混在は避ける

```python
# ⚠️ Avoid: 同じデータ構造でPydanticとdataclassを混在
class SearchResult(BaseModel):  # Pydantic
    ...

@dataclass
class SearchResult:  # dataclass - 同じ名前で混在は避ける
    ...
```

### 現在のコードベースでの評価

#### ✅ 適切な使い分け

1. **`src/utils/config.py`**: Pydantic ✅
   - 設定ファイルのバリデーションが必要
   - 複数のモジュールで使用される

2. **`src/crawler/profile_audit.py`**: Pydantic ✅
   - モジュール間のデータ受け渡し
   - バリデーションが必要（`ge=0`, `ge=0.0`など）

3. **`src/ml_server/models.py`**: Pydantic ✅
   - APIリクエスト/レスポンス
   - 型安全性が重要

#### ⚠️ 改善の余地がある使い分け

1. **`src/crawler/session_transfer.py`**: dataclass → Pydantic推奨
   - `CookieData`, `SessionData`, `TransferResult`はモジュール間で使用
   - バリデーションが必要（ドメインマッチング、有効期限チェック）

2. **`src/search/provider.py`**: dataclass → Pydantic推奨
   - `SearchResult`, `SearchResponse`はモジュール間で使用
   - 型安全性が重要

3. **`src/research/state.py`**: dataclass → Pydantic推奨
   - `SearchState`, `TaskState`, `ExplorationState`はモジュール間で使用
   - バリデーションが必要（範囲チェック、状態遷移）

#### ✅ 適切: 内部実装はdataclassのまま

1. **`src/crawler/human_behavior.py`**: dataclass ✅
   - 内部実装のみ
   - 高頻度でインスタンス化される可能性

2. **`src/filter/deduplication.py`**: dataclass ✅
   - 内部実装のみ
   - パフォーマンスが重要

## 移行ガイドライン

### 移行すべきケース

1. **モジュール間のデータ受け渡し**
   - 関数の引数・戻り値として使用される
   - 複数のモジュールでインポートされる
   - **推奨**: Pydantic（型安全性・バリデーション・エラーメッセージ）

2. **設定・設定ファイル**
   - YAML/JSONから読み込む設定
   - バリデーションが必要
   - **推奨**: Pydantic（バリデーション・ドキュメント化）

3. **APIリクエスト/レスポンス**
   - HTTP APIのリクエスト/レスポンス
   - MCPツールの引数/戻り値
   - **推奨**: Pydantic（型安全性・JSONスキーマ生成）

### 移行不要なケース

1. **内部実装のみ**
   - 単一モジュール内でのみ使用
   - パフォーマンスが重要な場合（高頻度インスタンス化）
   - **推奨**: dataclass（軽量・高速）

2. **既存のdataclassが十分**
   - バリデーション不要（既に検証済み）
   - シンプルなデータ構造
   - **推奨**: dataclass（標準ライブラリ・依存関係なし）

---

## 次のステップ

1. **高優先度モジュールの移行**
   - `session_transfer.py`の移行
   - `provider.py`（search, filter）の移行
   - `state.py`の移行

2. **移行後の検証**
   - デバッグスクリプトの実行
   - 型チェック（mypy）の確認
   - テストの実行

3. **ドキュメント更新**
   - シーケンス図の更新
   - APIドキュメントの更新

