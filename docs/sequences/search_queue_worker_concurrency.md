# SearchQueueWorker 同時実行シーケンス図

## 概要

2つのワーカーが同時に検索を処理する際のリソース競合とレート制限の流れを示す。

## シーケンス図

```mermaid
sequenceDiagram
    autonumber
    participant W0 as Worker-0
    participant W1 as Worker-1
    participant DB as Database
    participant SP as SearchPipeline
    participant BSP as BrowserSearchProvider<br/>(Singleton)
    participant ASP0 as AcademicSearchProvider<br/>(Instance 0)
    participant ASP1 as AcademicSearchProvider<br/>(Instance 1)
    participant S2 as Semantic Scholar API
    participant OA as OpenAlex API

    Note over W0,W1: 2ワーカーが同時にジョブを取得

    W0->>DB: SELECT ... ORDER BY priority, queued_at
    W1->>DB: SELECT ... ORDER BY priority, queued_at
    DB-->>W0: Job A (query="AI safety")
    DB-->>W1: Job B (query="machine learning")

    W0->>DB: UPDATE state='running' WHERE state='queued' (CAS)
    W1->>DB: UPDATE state='running' WHERE state='queued' (CAS)
    
    Note over W0,W1: 両ワーカーがジョブを獲得

    par Worker-0: 検索実行
        W0->>SP: search_action(Job A)
        SP->>SP: AcademicSearchProvider() [新規インスタンス]
        activate ASP0
        
        par 並列検索 (asyncio.gather)
            SP->>BSP: search_serp("AI safety")
            Note over BSP: Semaphore(1) 待機
            activate BSP
            SP->>ASP0: search("AI safety")
        end
    and Worker-1: 検索実行
        W1->>SP: search_action(Job B)
        SP->>SP: AcademicSearchProvider() [新規インスタンス]
        activate ASP1
        
        par 並列検索 (asyncio.gather)
            SP->>BSP: search_serp("machine learning")
            Note over BSP: Worker-0がSemaphore保持中<br/>→ 待機
            SP->>ASP1: search("machine learning")
        end
    end

    rect rgb(255, 200, 200)
        Note over ASP0,OA: ⚠️ 問題: 学術APIにグローバルQPS制限なし
        par 同時API呼び出し (問題)
            ASP0->>S2: GET /paper/search?query=AI+safety
            ASP0->>OA: GET /works?search=AI+safety
            ASP1->>S2: GET /paper/search?query=machine+learning
            ASP1->>OA: GET /works?search=machine+learning
        end
        Note over S2: 同時4リクエスト!<br/>QPS超過の可能性
    end

    rect rgb(200, 255, 200)
        Note over BSP: ✅ ブラウザSERP: Semaphore(1)で直列化
        BSP-->>SP: SERP results (Worker-0)
        deactivate BSP
        activate BSP
        Note over BSP: Worker-1がSemaphore獲得
        BSP-->>SP: SERP results (Worker-1)
        deactivate BSP
    end

    S2-->>ASP0: results
    OA-->>ASP0: results
    S2-->>ASP1: results
    OA-->>ASP1: results
    
    deactivate ASP0
    deactivate ASP1

    SP-->>W0: SearchResult
    SP-->>W1: SearchResult

    W0->>DB: UPDATE state='completed'
    W1->>DB: UPDATE state='completed'
```

## 問題点

### 1. 学術API同時アクセス (❌ 問題)

- `AcademicSearchProvider` は各 `SearchPipeline.execute()` で新規インスタンス作成
- 各インスタンスは独自の `SemanticScholarClient` / `OpenAlexClient` を持つ
- **グローバルなQPS制限がない**
- 2ワーカー × 2 API = 最大4同時リクエスト

### 2. ブラウザSERP (✅ 問題なし)

- `get_browser_search_provider()` はシングルトンを返す
- `_rate_limiter = asyncio.Semaphore(1)` で同時1を保証
- 2ワーカーが同時に呼んでも直列化される

## 解決策

### Option A: 学術APIクライアントのシングルトン化

```python
# src/search/apis/base.py に追加
_clients: dict[str, BaseAcademicClient] = {}

def get_academic_client(name: str) -> BaseAcademicClient:
    if name not in _clients:
        if name == "semantic_scholar":
            _clients[name] = SemanticScholarClient()
        elif name == "openalex":
            _clients[name] = OpenAlexClient()
    return _clients[name]
```

### Option B: グローバルレートリミッター追加

```python
# src/search/apis/rate_limiter.py
class AcademicAPIRateLimiter:
    def __init__(self):
        self._locks: dict[str, asyncio.Lock] = {}
        self._last_request: dict[str, float] = {}
    
    async def acquire(self, api_name: str, min_interval: float = 0.1) -> None:
        # プロバイダー別にレート制限
```

### Option C: 現状維持（APIサーバー側制限に依存）

- Semantic Scholar / OpenAlex は寛容なレート制限（10+ req/s）
- 2ワーカー程度なら問題ない可能性
- ただし、スケール時に問題になる

## 推奨: Option B (グローバルレートリミッター)

- 既存コードへの影響が最小
- 将来のスケール対応も容易
- テストで検証可能

