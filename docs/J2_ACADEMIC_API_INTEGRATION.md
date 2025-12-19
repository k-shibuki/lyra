# J.2 学術API統合 開発計画

## 調査日: 2025-12-16

本ドキュメントは、Phase J.2「学術API統合」の詳細設計・実装計画を記述する。

---

## 1. 目的と背景

### 1.1 目的

無料で利用可能な学術APIを統合し、以下を実現する：

1. **論文メタデータ取得**: タイトル、著者、抄録、発行年、DOI
2. **引用グラフ構築**: 論文間の引用関係をエビデンスグラフに反映
3. **一次資料優先**: §3.1の「学術・公的は直接ソースを優先」を強化
4. **OAリンク解決**: 無料で読める版へのアクセス

### 1.2 仕様書との整合性

| 仕様書参照 | 内容 | 本計画での対応 |
|-----------|------|---------------|
| §3.1 | 学術・公的は直接ソース（arXiv, PubMed等）を優先 | AcademicSearchProvider + BrowserSearchProvider 補完的実行 |
| §3.1.3 | OpenAlex/Semantic Scholar/Crossref/Unpaywall APIの利用 | 4つのAPIクライアント実装（arXiv含む） |
| §3.3.1 | エビデンスグラフ: supports/refutes/citesエッジ | 既存CITESエッジに `is_academic`, `is_influential` 属性追加 |
| §4.3.5 | 公式APIへのバックオフ付きリトライ | 既存`ACADEMIC_API_POLICY`を活用 |
| §5.1 | 学術: OpenAlex/Semantic Scholar/Crossref/Unpaywall | 外部依存として明記 |
| §7 | ソース階層: 一次資料 > 公的機関 > 学術 | `SourceTag.ACADEMIC` で信頼度計算に反映 |

### 1.3 Zero OpEx原則との適合

| API | 料金 | 認証 | Rate Limit | 適合 |
|-----|:----:|:----:|:----------:|:----:|
| **Semantic Scholar** | 無料 | API Key推奨 | 認証なし: 不明、認証あり: 1000/sec | ✅ |
| **OpenAlex** | 無料 | 不要 | 100k/day + 10/sec | ✅ |
| **Crossref** | 無料 | 不要 | polite pool（mailto推奨） | ✅ |
| **arXiv API** | 無料 | 不要 | 3秒間隔、最大30,000件 | ✅ |
| **Unpaywall** | 無料 | メール必須 | 100k/day | ✅ |

**API仕様調査日**: 2025-12-16

**補足**:
- Semantic Scholar: API Keyを取得することでrate limit向上。polite pool対応
- OpenAlex: `mailto=` パラメータでpolite pool入り（優先レスポンス）
- Crossref: `mailto=` パラメータでpolite pool入り
- arXiv: 結果は2,000件/回で取得、最大30,000件まで

---

## 2. アーキテクチャ設計

### 2.1 検索戦略: 補完的アプローチ

学術クエリに対して、**一般検索と学術API検索を並列実行**し、結果をマージする。

```
                         クエリ入力
                             │
                    ┌────────▼────────┐
                    │ 学術クエリ判定   │
                    │ (_is_academic)  │
                    └────────┬────────┘
                             │ 学術クエリの場合
            ┌────────────────┴────────────────┐
            │           並列実行               │
    ┌───────▼───────┐               ┌─────────▼─────────┐
    │BrowserSearch   │               │ AcademicSearch    │
    │Provider        │               │ Provider          │
    │(一般検索)       │               │(学術API)          │
    └───────┬───────┘               └─────────┬─────────┘
            │                                 │
            │ SERP結果                        │ Paper結果
            │                                 │
            └────────────────┬────────────────┘
                             │
                    ┌────────▼────────┐
                    │ 結果マージ       │
                    │ (DOI/URLで重複排除) │
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │ 統合SERP結果     │
                    │ + 引用グラフ取得  │
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │ 既存パイプライン  │
                    │ (fetch/extract)  │
                    └─────────────────┘
```

**設計ポイント**:
- 学術クエリでも一般検索は実行（arXiv/PubMed等のWebページも取得可能）
- 学術APIの結果は `SourceTag.ACADEMIC` としてマーク
- 重複排除: DOIがあればDOIで、なければURL/タイトルで照合
- 一般クエリの場合は従来通りBrowserSearchProviderのみ使用

### 2.2 AcademicSearchProvider 構成

```
┌─────────────────────────────────────────────────────────────────┐
│                    AcademicSearchProvider                        │
├─────────────────────────────────────────────────────────────────┤
│  複数の学術APIクライアントを統合し、統一インターフェースを提供      │
└─────────────────────────────────────────────────────────────────┘
                                      │
                    ┌─────────────────┼─────────────────┐
                    │                 │                 │
           ┌────────▼───────┐ ┌──────▼──────┐ ┌───────▼───────┐
           │ SemanticScholar │ │  OpenAlex   │ │   Crossref    │
           │    Client       │ │   Client    │ │    Client     │
           │ (引用グラフ主)   │ │ (大規模検索) │ │  (DOI解決)    │
           └────────┬────────┘ └──────┬──────┘ └───────┬───────┘
                    │                 │                 │
           ┌────────▼───────┐        │                 │
           │  ArxivClient   │        │                 │
           │ (プレプリント)  │        │                 │
           └────────────────┘        │                 │
                                     │                 │
                    ┌────────────────┴─────────────────┘
                    │
                    ▼
           ┌─────────────────┐
           │ EvidenceGraph   │
           │ (既存CITES拡張) │
           │ is_academic属性 │
           └─────────────────┘
```

### 2.3 モジュール構成

| ディレクトリ | ファイル | 役割 | 変更種別 |
|------------|---------|------|:--------:|
| `src/search/apis/` | `__init__.py` | APIクライアント共通エクスポート | 新規 |
| | `base.py` | `BaseAcademicClient` 抽象クラス | 新規 |
| | `semantic_scholar.py` | Semantic Scholar APIクライアント | 新規 |
| | `openalex.py` | OpenAlex APIクライアント | 新規 |
| | `crossref.py` | Crossref APIクライアント | 新規 |
| | `arxiv.py` | arXiv API クライアント | 新規 |
| `src/search/` | `academic_provider.py` | `AcademicSearchProvider` 統合プロバイダ | 新規 |
| `src/research/` | `pipeline.py` | 補完的検索のマージロジック追加 | 修正 |
| `src/filter/` | `evidence_graph.py` | CITESエッジに `is_academic`, `is_influential` 属性追加 | 修正 |
| `src/storage/` | `schema.sql` | pagesテーブルに `paper_metadata` カラム追加 | 修正 |
| `src/utils/` | `schemas.py` | `Paper`, `Citation`, `Author` Pydanticモデル追加 | 修正 |
| `config/` | `academic_apis.yaml` | API設定（エンドポイント、rate limit等） | 新規 |

### 2.4 既存資産の活用

以下は既存実装をそのまま活用（変更不要）:

| ファイル | 理由 |
|----------|------|
| `src/extractor/content.py` | PDF抽出機能（PyMuPDF + OCR）は実装済み |
| `src/crawler/fetcher.py` | PDF取得・保存は対応済み |
| `src/search/provider.py` | `BaseSearchProvider`, `SourceTag.ACADEMIC` 既存 |
| `src/utils/api_retry.py` | `ACADEMIC_API_POLICY` 定義済み |

---

## 3. データモデル

### 3.1 Pydanticモデル（`src/utils/schemas.py`）

```python
from pydantic import BaseModel, Field
from datetime import date
from typing import Optional

class Author(BaseModel):
    """論文著者."""
    name: str
    affiliation: str | None = None
    orcid: str | None = None

class Paper(BaseModel):
    """学術論文メタデータ."""
    id: str = Field(..., description="内部ID（provider:external_id形式）")
    title: str
    abstract: str | None = None
    authors: list[Author] = Field(default_factory=list)
    year: int | None = None
    published_date: date | None = None
    doi: str | None = None
    arxiv_id: str | None = None
    venue: str | None = None  # ジャーナル/会議名
    citation_count: int = 0
    reference_count: int = 0
    is_open_access: bool = False
    oa_url: str | None = None  # OA版URL
    pdf_url: str | None = None
    source_api: str  # "semantic_scholar", "openalex", "crossref", "arxiv"
    
    def to_search_result(self) -> "SearchResult":
        """SearchResult形式に変換."""
        from src.search.provider import SearchResult, SourceTag
        return SearchResult(
            title=self.title,
            url=self.oa_url or f"https://doi.org/{self.doi}" if self.doi else "",
            snippet=self.abstract[:500] if self.abstract else "",
            engine=self.source_api,
            rank=0,
            date=str(self.year) if self.year else None,
            source_tag=SourceTag.ACADEMIC,
        )

class Citation(BaseModel):
    """引用関係."""
    citing_paper_id: str
    cited_paper_id: str
    context: str | None = None  # 引用箇所のテキスト
    is_influential: bool = False  # Semantic Scholar独自

class AcademicSearchResult(BaseModel):
    """学術API検索結果."""
    papers: list[Paper]
    total_count: int
    next_cursor: str | None = None
    source_api: str
```

### 3.2 Paper/Page 統合設計（ハイブリッド方式）

**設計選択の根拠**:

| 選択肢 | 概要 | 利点 | 欠点 |
|--------|------|------|------|
| A: 統合 | Paper → Page に変換して保存 | 既存パイプラインをそのまま使用 | 学術メタデータ（著者、引用数）が失われる |
| B: 分離 | papers テーブルを別に作成 | 学術固有データを保持可能 | 二重管理、クエリ複雑化 |
| **C: ハイブリッド** | Page + paper_metadata JSON | 既存構造を維持しつつメタデータ保持 | **採用** |

**採用設計（ハイブリッド方式）**:
- `pages` テーブルに `paper_metadata` カラムを追加（JSON）
- 学術論文は `pages.page_type = 'academic_paper'` でマーク
- `paper_metadata` には DOI, 著者, 引用数, venue 等を格納
- エビデンスグラフでは `NodeType.PAGE` を使用（`NodeType.PAPER` は追加しない）

### 3.3 エビデンスグラフ拡張（`src/filter/evidence_graph.py`）

```python
# 既存のNodeType/RelationTypeは変更なし
class NodeType(str, Enum):
    CLAIM = "claim"
    FRAGMENT = "fragment"
    PAGE = "page"  # 学術論文もPAGEとして扱う

class RelationType(str, Enum):
    SUPPORTS = "supports"
    REFUTES = "refutes"
    CITES = "cites"  # 既存のCITESを拡張（属性追加）
    NEUTRAL = "neutral"
```

**CITESエッジへの属性追加**:
```python
# add_edge() 呼び出し時に追加属性を指定
graph.add_edge(
    source_type=NodeType.PAGE,
    source_id=citing_page_id,
    target_type=NodeType.PAGE,
    target_id=cited_page_id,
    relation=RelationType.CITES,
    is_academic=True,       # NEW: 学術引用フラグ
    is_influential=True,    # NEW: Semantic Scholar の influential citation
    citation_context=None,  # NEW: 引用箇所のテキスト（オプション）
)
```

**設計根拠**:
- `NodeType.PAPER` / `RelationType.ACADEMIC_CITES` を新規追加する案は廃止
- 既存の引用ループ検出・整合性レポート機能をそのまま活用可能
- `is_academic` 属性で学術引用とWeb引用を区別

### 3.4 DBスキーマ拡張（`src/storage/schema.sql`）

```sql
-- pages テーブルへのカラム追加（マイグレーション）
ALTER TABLE pages ADD COLUMN paper_metadata TEXT;
-- paper_metadata JSON構造:
-- {
--   "doi": "10.1234/example",
--   "authors": [{"name": "John Doe", "orcid": "0000-0001-2345-6789"}],
--   "year": 2024,
--   "venue": "Nature",
--   "citation_count": 42,
--   "reference_count": 25,
--   "is_open_access": true,
--   "source_api": "semantic_scholar"
-- }

-- edges テーブルへのカラム追加（マイグレーション）
ALTER TABLE edges ADD COLUMN is_academic INTEGER DEFAULT 0;
ALTER TABLE edges ADD COLUMN is_influential INTEGER DEFAULT 0;
ALTER TABLE edges ADD COLUMN citation_context TEXT;
```

**page_type の新規値**:
```
academic_paper  -- 学術論文（PDF/HTML問わず）
```

---

## 4. APIクライアント詳細設計

### 4.1 基底クラス（`src/search/apis/base.py`）

```python
from abc import ABC, abstractmethod
from typing import Any
from src.utils.api_retry import retry_api_call, ACADEMIC_API_POLICY
from src.utils.logging import get_logger

logger = get_logger(__name__)

class BaseAcademicClient(ABC):
    """学術APIクライアント基底クラス."""
    
    def __init__(self, name: str):
        self.name = name
        self._session: httpx.AsyncClient | None = None
    
    async def _get_session(self) -> httpx.AsyncClient:
        """HTTPセッションを取得（遅延初期化）."""
        if self._session is None:
            self._session = httpx.AsyncClient(
                timeout=30.0,
                headers={"User-Agent": "Lyra/1.0 (research tool; mailto:lyra@example.com)"}
            )
        return self._session
    
    @abstractmethod
    async def search(self, query: str, limit: int = 10) -> AcademicSearchResult:
        """論文検索."""
        pass
    
    @abstractmethod
    async def get_paper(self, paper_id: str) -> Paper | None:
        """論文メタデータ取得."""
        pass
    
    @abstractmethod
    async def get_references(self, paper_id: str) -> list[Paper]:
        """参考文献（この論文が引用している論文）を取得."""
        pass
    
    @abstractmethod
    async def get_citations(self, paper_id: str) -> list[Paper]:
        """被引用（この論文を引用している論文）を取得."""
        pass
    
    async def close(self) -> None:
        """セッションをクローズ."""
        if self._session:
            await self._session.aclose()
            self._session = None
```

### 4.2 Semantic Scholar（`src/search/apis/semantic_scholar.py`）

**API仕様**:
- ベースURL: `https://api.semanticscholar.org/graph/v1`
- Rate Limit: 100 requests / 5 min（認証なし）
- 引用グラフ: ✅ 完全対応（references, citations, influential citations）

```python
class SemanticScholarClient(BaseAcademicClient):
    BASE_URL = "https://api.semanticscholar.org/graph/v1"
    FIELDS = "paperId,title,abstract,year,authors,citationCount,referenceCount,isOpenAccess,openAccessPdf,venue,externalIds"
    
    async def search(self, query: str, limit: int = 10) -> AcademicSearchResult:
        session = await self._get_session()
        
        @retry_api_call(policy=ACADEMIC_API_POLICY)
        async def _search():
            response = await session.get(
                f"{self.BASE_URL}/paper/search",
                params={"query": query, "limit": limit, "fields": self.FIELDS}
            )
            response.raise_for_status()
            return response.json()
        
        data = await _search()
        papers = [self._parse_paper(p) for p in data.get("data", [])]
        return AcademicSearchResult(
            papers=papers,
            total_count=data.get("total", 0),
            next_cursor=data.get("next"),
            source_api="semantic_scholar"
        )
    
    async def get_references(self, paper_id: str) -> list[Paper]:
        """参考文献を取得（influential citation含む）."""
        session = await self._get_session()
        response = await session.get(
            f"{self.BASE_URL}/paper/{paper_id}/references",
            params={"fields": self.FIELDS + ",isInfluential"}
        )
        response.raise_for_status()
        data = response.json()
        return [
            (self._parse_paper(ref["citedPaper"]), ref.get("isInfluential", False))
            for ref in data.get("data", [])
            if ref.get("citedPaper")
        ]
    
    async def get_citations(self, paper_id: str) -> list[Paper]:
        """被引用を取得."""
        session = await self._get_session()
        response = await session.get(
            f"{self.BASE_URL}/paper/{paper_id}/citations",
            params={"fields": self.FIELDS + ",isInfluential"}
        )
        response.raise_for_status()
        data = response.json()
        return [
            (self._parse_paper(cit["citingPaper"]), cit.get("isInfluential", False))
            for cit in data.get("data", [])
            if cit.get("citingPaper")
        ]
    
    def _parse_paper(self, data: dict) -> Paper:
        """API応答をPaperモデルに変換."""
        external_ids = data.get("externalIds", {})
        oa_pdf = data.get("openAccessPdf", {})
        return Paper(
            id=f"s2:{data['paperId']}",
            title=data.get("title", ""),
            abstract=data.get("abstract"),
            authors=[Author(name=a.get("name", "")) for a in data.get("authors", [])],
            year=data.get("year"),
            doi=external_ids.get("DOI"),
            arxiv_id=external_ids.get("ArXiv"),
            venue=data.get("venue"),
            citation_count=data.get("citationCount", 0),
            reference_count=data.get("referenceCount", 0),
            is_open_access=data.get("isOpenAccess", False),
            oa_url=oa_pdf.get("url") if oa_pdf else None,
            source_api="semantic_scholar"
        )
```

### 4.3 OpenAlex（`src/search/apis/openalex.py`）

**API仕様**:
- ベースURL: `https://api.openalex.org`
- Rate Limit: 100,000 requests / day（polite pool推奨）
- 引用グラフ: ✅ 対応（referenced_works, cited_by_count）

```python
class OpenAlexClient(BaseAcademicClient):
    BASE_URL = "https://api.openalex.org"
    
    async def search(self, query: str, limit: int = 10) -> AcademicSearchResult:
        session = await self._get_session()
        response = await session.get(
            f"{self.BASE_URL}/works",
            params={
                "search": query,
                "per-page": limit,
                "select": "id,title,abstract_inverted_index,publication_year,authorships,doi,cited_by_count,referenced_works_count,open_access,primary_location"
            }
        )
        response.raise_for_status()
        data = response.json()
        papers = [self._parse_paper(w) for w in data.get("results", [])]
        return AcademicSearchResult(
            papers=papers,
            total_count=data.get("meta", {}).get("count", 0),
            source_api="openalex"
        )
    
    def _parse_paper(self, data: dict) -> Paper:
        # abstract_inverted_index → plain text変換
        abstract = self._reconstruct_abstract(data.get("abstract_inverted_index"))
        oa = data.get("open_access", {})
        location = data.get("primary_location", {}) or {}
        
        return Paper(
            id=f"openalex:{data['id'].split('/')[-1]}",
            title=data.get("title", ""),
            abstract=abstract,
            authors=[
                Author(name=a.get("author", {}).get("display_name", ""))
                for a in data.get("authorships", [])
            ],
            year=data.get("publication_year"),
            doi=data.get("doi", "").replace("https://doi.org/", "") if data.get("doi") else None,
            venue=location.get("source", {}).get("display_name") if location.get("source") else None,
            citation_count=data.get("cited_by_count", 0),
            reference_count=data.get("referenced_works_count", 0),
            is_open_access=oa.get("is_oa", False),
            oa_url=oa.get("oa_url"),
            source_api="openalex"
        )
    
    def _reconstruct_abstract(self, inverted_index: dict | None) -> str | None:
        """OpenAlexの逆インデックス形式から平文を復元."""
        if not inverted_index:
            return None
        words = {}
        for word, positions in inverted_index.items():
            for pos in positions:
                words[pos] = word
        return " ".join(words[i] for i in sorted(words.keys()))
```

### 4.4 Crossref（`src/search/apis/crossref.py`）

**API仕様**:
- ベースURL: `https://api.crossref.org`
- Rate Limit: polite pool（User-Agentにメール設定で優遇）
- 引用グラフ: △ 参考文献のみ（被引用は別API）

```python
class CrossrefClient(BaseAcademicClient):
    BASE_URL = "https://api.crossref.org"
    
    async def search(self, query: str, limit: int = 10) -> AcademicSearchResult:
        session = await self._get_session()
        response = await session.get(
            f"{self.BASE_URL}/works",
            params={"query": query, "rows": limit}
        )
        response.raise_for_status()
        data = response.json()
        items = data.get("message", {}).get("items", [])
        papers = [self._parse_paper(item) for item in items]
        return AcademicSearchResult(
            papers=papers,
            total_count=data.get("message", {}).get("total-results", 0),
            source_api="crossref"
        )
    
    async def get_paper_by_doi(self, doi: str) -> Paper | None:
        """DOIから論文メタデータを取得."""
        session = await self._get_session()
        response = await session.get(f"{self.BASE_URL}/works/{doi}")
        if response.status_code == 404:
            return None
        response.raise_for_status()
        data = response.json()
        return self._parse_paper(data.get("message", {}))
```

### 4.5 arXiv（`src/search/apis/arxiv.py`）

**API仕様**:
- ベースURL: `http://export.arxiv.org/api/query`
- Rate Limit: 3秒間隔推奨
- 引用グラフ: ❌ なし（Semantic Scholarで補完）

```python
class ArxivClient(BaseAcademicClient):
    BASE_URL = "http://export.arxiv.org/api/query"
    
    async def search(self, query: str, limit: int = 10) -> AcademicSearchResult:
        session = await self._get_session()
        response = await session.get(
            self.BASE_URL,
            params={
                "search_query": f"all:{query}",
                "start": 0,
                "max_results": limit,
                "sortBy": "relevance",
                "sortOrder": "descending"
            }
        )
        response.raise_for_status()
        
        # Atom XML解析
        papers = self._parse_atom_feed(response.text)
        return AcademicSearchResult(
            papers=papers,
            total_count=len(papers),
            source_api="arxiv"
        )
```

---

## 5. 統合プロバイダ設計

### 5.1 AcademicSearchProvider（`src/search/academic_provider.py`）

```python
class AcademicSearchProvider(BaseSearchProvider):
    """学術API統合プロバイダ.
    
    複数の学術APIを統合し、統一インターフェースで検索・引用グラフ取得を提供。
    """
    
    def __init__(self):
        super().__init__("academic")
        self._clients: dict[str, BaseAcademicClient] = {}
        self._default_apis = ["semantic_scholar", "openalex"]  # デフォルトで使用するAPI
    
    async def _get_client(self, api_name: str) -> BaseAcademicClient:
        """クライアントを取得（遅延初期化）."""
        if api_name not in self._clients:
            if api_name == "semantic_scholar":
                self._clients[api_name] = SemanticScholarClient()
            elif api_name == "openalex":
                self._clients[api_name] = OpenAlexClient()
            elif api_name == "crossref":
                self._clients[api_name] = CrossrefClient()
            elif api_name == "arxiv":
                self._clients[api_name] = ArxivClient()
            else:
                raise ValueError(f"Unknown API: {api_name}")
        return self._clients[api_name]
    
    async def search(
        self,
        query: str,
        options: SearchOptions | None = None,
    ) -> SearchResponse:
        """学術論文を検索.
        
        複数APIを並列で呼び出し、結果をマージ・重複排除する。
        """
        apis_to_use = (options.engines if options and options.engines 
                       else self._default_apis)
        
        # 並列検索
        tasks = []
        for api_name in apis_to_use:
            client = await self._get_client(api_name)
            tasks.append(client.search(query, limit=options.limit if options else 10))
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 結果マージ・重複排除（DOIベース）
        all_papers: dict[str, Paper] = {}
        for result in results:
            if isinstance(result, Exception):
                logger.warning("API search failed", error=str(result))
                continue
            for paper in result.papers:
                key = paper.doi or paper.id
                if key not in all_papers:
                    all_papers[key] = paper
        
        # SearchResponse形式に変換
        search_results = [
            paper.to_search_result() 
            for paper in all_papers.values()
        ]
        
        return SearchResponse(
            results=search_results,
            query=query,
            provider=self.name,
            total_count=len(search_results),
        )
    
    async def get_citation_graph(
        self,
        paper_id: str,
        depth: int = 1,
        direction: str = "both",  # "references", "citations", "both"
    ) -> tuple[list[Paper], list[Citation]]:
        """引用グラフを取得.
        
        Args:
            paper_id: 起点論文ID
            depth: 探索深度（1=直接引用のみ、2=引用の引用まで）
            direction: 探索方向
            
        Returns:
            (papers, citations) タプル
        """
        # Semantic Scholarを優先（引用グラフが最も充実）
        client = await self._get_client("semantic_scholar")
        
        papers: dict[str, Paper] = {}
        citations: list[Citation] = []
        to_explore = [(paper_id, 0)]  # (paper_id, current_depth)
        explored = set()
        
        while to_explore:
            current_id, current_depth = to_explore.pop(0)
            if current_id in explored or current_depth >= depth:
                continue
            explored.add(current_id)
            
            # 参考文献取得
            if direction in ("references", "both"):
                refs = await client.get_references(current_id)
                for ref_paper, is_influential in refs:
                    papers[ref_paper.id] = ref_paper
                    citations.append(Citation(
                        citing_paper_id=current_id,
                        cited_paper_id=ref_paper.id,
                        is_influential=is_influential
                    ))
                    if current_depth + 1 < depth:
                        to_explore.append((ref_paper.id, current_depth + 1))
            
            # 被引用取得
            if direction in ("citations", "both"):
                cits = await client.get_citations(current_id)
                for cit_paper, is_influential in cits:
                    papers[cit_paper.id] = cit_paper
                    citations.append(Citation(
                        citing_paper_id=cit_paper.id,
                        cited_paper_id=current_id,
                        is_influential=is_influential
                    ))
                    if current_depth + 1 < depth:
                        to_explore.append((cit_paper.id, current_depth + 1))
        
        return list(papers.values()), citations
```

---

## 6. パイプライン統合

### 6.1 補完的検索パイプライン

**変更ファイル**: `src/research/pipeline.py`

学術クエリの場合、一般検索と学術API検索を**並列実行**し、結果をマージする。

```python
async def _execute_complementary_search(
    self,
    query: str,
    options: SearchOptions,
) -> list[dict]:
    """補完的検索: 一般検索 + 学術API検索を並列実行."""
    
    tasks = []
    
    # 1. 一般検索（常に実行）
    tasks.append(self._execute_browser_search(query, options))
    
    # 2. 学術API検索（学術クエリの場合のみ）
    if self._is_academic_query(query) or options.academic:
        from src.search.academic_provider import get_academic_provider
        academic_provider = get_academic_provider()
        tasks.append(academic_provider.search(query, options))
    
    # 並列実行
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # 結果マージ・重複排除
    merged = self._merge_search_results(results)
    
    return merged

def _merge_search_results(
    self,
    results: list[SearchResponse | Exception],
) -> list[dict]:
    """検索結果をマージし、DOI/URLで重複排除."""
    seen_keys: set[str] = set()
    merged: list[dict] = []
    
    for result in results:
        if isinstance(result, Exception):
            logger.warning("Search failed", error=str(result))
            continue
        
        for item in result.results:
            # 重複キー: DOI > URL > タイトル
            key = item.doi or item.url or item.title
            if key not in seen_keys:
                seen_keys.add(key)
                merged.append(item.to_dict())
    
    return merged
```

### 6.2 学術クエリ判定

```python
def _is_academic_query(self, query: str) -> bool:
    """学術クエリかどうかを判定.
    
    判定基準:
    1. キーワード: "論文", "paper", "研究", "study", "arXiv", "DOI"
    2. サイト指定: site:arxiv.org, site:pubmed
    3. DOI形式: 10.xxxx/... パターン
    4. 明示的オプション: options.academic=True
    """
    import re
    
    query_lower = query.lower()
    
    # キーワード判定
    academic_keywords = [
        "論文", "paper", "研究", "study", "学術", "journal",
        "arxiv", "pubmed", "doi:", "citation", "引用"
    ]
    if any(kw in query_lower for kw in academic_keywords):
        return True
    
    # サイト指定判定
    academic_sites = ["arxiv.org", "pubmed", "scholar.google", "jstage"]
    if any(f"site:{site}" in query_lower for site in academic_sites):
        return True
    
    # DOI形式判定
    if re.search(r"10\.\d{4,}/", query):
        return True
    
    return False
```

### 6.3 学術論文のコンテンツ戦略: Abstract Only

学術論文は**抄録（Abstract）とメタデータのみ**を自動取得し、フルテキストは参照先（DOI/OA URL）として提示する。

#### 6.3.1 設計思想

Lancetは**コンテキストエンジニアリングの一部**であり、すべてを自動処理することが目的ではない。

| 役割 | 自動化（Lancet） | 人間/Cursor AI |
|------|:----------------:|:--------------:|
| **論文発見** | ✅ | - |
| **メタデータ取得** | ✅ | - |
| **抄録によるエビデンス** | ✅ | - |
| **引用グラフ構築** | ✅ | - |
| **フルテキスト参照先提示** | ✅ | - |
| **フルテキストの詳細解釈** | - | ✅ |

**設計根拠**:
1. **学術APIから高品質な抄録が取得可能**: PDFパースによる誤りがない
2. **PDF本文の自動処理は複雑**: 段組み、図表、数式、OCR問題
3. **フルテキストの解釈には専門知識が必要**: 人間が読むべき
4. **信頼性の高いサジェストが重要**: 「どの論文を読むべきか」を正確に示す

#### 6.3.2 データフロー

```
学術API検索
    │
    ▼
Paper {
    title, authors, year, venue,
    abstract,        ← Fragmentとして保存
    doi,             ← 参照先として提示
    oa_url,          ← OA版へのリンク
    citation_count,
    ...
}
    │
    ▼
┌─────────────────────────────────────────────────────┐
│ 抄録をFragmentに保存                                 │
│ - fragment_type: "abstract"                         │
│ - source_tag: SourceTag.ACADEMIC                    │
│ - DOI/OA URLを参照先として付与                       │
└─────────────────────────────────────────────────────┘
    │
    ▼
エビデンスグラフに追加
（引用関係も含む）
```

#### 6.3.3 PDF取得が発生するケース

**なし**（設計上排除）

PDF取得・抽出は本設計のスコープ外とする。将来的に必要になった場合は、既存の `src/extractor/content.py` を活用可能。

#### 6.3.4 フルテキストが必要な場合のワークフロー

1. **Lancetの出力**: 「詳細は以下の論文を参照: [DOI: 10.xxxx/...]」
2. **ユーザーのアクション**: PDFをダウンロードしてCursor AIに添付
3. **Cursor AIのアクション**: フルテキストを解釈し、レポートに反映

**この分業により**:
- Lancetは「信頼性の高い論文発見」に専念
- 専門的な解釈は人間/Cursor AIが担当
- PDFパースの複雑な問題を回避

#### 6.3.5 実装コード

```python
async def _process_paper_content(
    self,
    paper: Paper,
) -> list[Fragment]:
    """論文コンテンツを処理.
    
    Abstract Only戦略: 抄録のみをFragmentとして保存し、
    フルテキストへの参照（DOI/OA URL）を付与する。
    
    Args:
        paper: 論文メタデータ
        
    Returns:
        fragments: 抄録を含むFragmentリスト
    """
    fragments = []
    
    if paper.abstract:
        # 参照先を構築
        reference_url = paper.oa_url or (f"https://doi.org/{paper.doi}" if paper.doi else None)
        
        fragments.append(Fragment(
            text_content=paper.abstract,
            fragment_type="abstract",
            heading_context="Abstract",
            source_url=reference_url,
            metadata={
                "doi": paper.doi,
                "oa_url": paper.oa_url,
                "citation_count": paper.citation_count,
                "year": paper.year,
                "venue": paper.venue,
                "note": "フルテキストは参照先URLで確認可能",
            },
        ))
    
    return fragments
```

### 6.4 引用グラフ取得（検索時）

検索結果の上位N件に対して、Semantic Scholar APIで引用グラフを取得する。

```python
async def _fetch_citation_graph(
    self,
    papers: list[Paper],
    top_n: int = 5,
    depth: int = 1,
) -> tuple[list[Paper], list[Citation]]:
    """検索結果の上位論文に対して引用グラフを取得.
    
    Args:
        papers: 検索結果の論文リスト
        top_n: 引用グラフを取得する論文数
        depth: 引用グラフの深度（1=直接引用のみ）
        
    Returns:
        (related_papers, citations) タプル
    """
    from src.search.academic_provider import get_academic_provider
    
    provider = get_academic_provider()
    all_papers = []
    all_citations = []
    
    for paper in papers[:top_n]:
        try:
            related, citations = await provider.get_citation_graph(
                paper_id=paper.id,
                depth=depth,
                direction="both",
            )
            all_papers.extend(related)
            all_citations.extend(citations)
        except Exception as e:
            logger.warning("Citation graph fetch failed", paper_id=paper.id, error=str(e))
    
    return all_papers, all_citations
```

### 6.5 エビデンスグラフ連携

**変更ファイル**: `src/filter/evidence_graph.py`

```python
async def add_academic_page_with_citations(
    self,
    page_id: str,
    paper_metadata: dict,
    citations: list[Citation],
) -> None:
    """学術論文ページと引用関係をグラフに追加.
    
    Args:
        page_id: ページID（pagesテーブルのID）
        paper_metadata: 論文メタデータ（JSON）
        citations: 引用関係リスト
    """
    # ページノードが存在することを確認
    page_node = self._make_node_id(NodeType.PAGE, page_id)
    if not self._graph.has_node(page_node):
        self.add_node(NodeType.PAGE, page_id)
    
    # ページノードに学術メタデータを追加
    self._graph.nodes[page_node].update({
        "is_academic": True,
        "doi": paper_metadata.get("doi"),
        "citation_count": paper_metadata.get("citation_count", 0),
        "year": paper_metadata.get("year"),
    })
    
    # 引用エッジを追加（既存のCITESを使用、属性追加）
    for citation in citations:
        cited_page_id = citation.cited_paper_id
        
        # 被引用ページノードが存在しなければ追加
        cited_node = self._make_node_id(NodeType.PAGE, cited_page_id)
        if not self._graph.has_node(cited_node):
            self.add_node(NodeType.PAGE, cited_page_id)
        
        # CITESエッジを追加（学術属性付き）
        self.add_edge(
            NodeType.PAGE, page_id,
            NodeType.PAGE, cited_page_id,
            RelationType.CITES,
            is_academic=True,
            is_influential=citation.is_influential,
            citation_context=citation.context,
        )
```

---

## 7. 追加検討事項

### 7.1 Abstract Only 戦略の根拠

**§6.3の設計選択を裏付ける技術的根拠**:

| 観点 | フルテキスト自動処理 | Abstract Only |
|------|:-------------------:|:-------------:|
| **データ品質** | PDF構造依存で不安定 | APIから高品質な構造化データ |
| **実装複雑度** | 高（段組み、図表、数式） | 低（API呼び出しのみ） |
| **処理時間** | PDF取得＋抽出で遅い | 軽量 |
| **エラー率** | OCR誤り、構造解析失敗 | ほぼゼロ |
| **Zero OpEx適合** | Vision API依存の恐れ | 完全適合 |

**フルテキストが必要な場面の対応**:
- DOI/OA URL を参照先として明示
- ユーザーがCursor AIにPDFを添付して解釈を依頼
- Lancetは「何を読むべきか」を信頼性高くサジェスト

### 7.2 Rate Limit 対策

| 対策 | 内容 |
|------|------|
| `ACADEMIC_API_POLICY` | 既存の `src/utils/api_retry.py` を適用（max_retries=5, backoff 1-120秒） |
| polite pool | OpenAlex/Crossref には `mailto=` パラメータを付与 |
| 引用グラフバッチ化 | 複数論文の引用グラフをまとめて取得 |
| キャッシュ | DOI → Paper メタデータを24時間キャッシュ |
| 上位N件制限 | 引用グラフ取得は検索結果上位5件に限定 |

### 7.3 学術クエリ判定の改善

現行の `_is_academic_query()` を以下に拡張:

| 判定基準 | 例 |
|----------|-----|
| キーワード検出 | "論文", "paper", "研究", "study", "arXiv", "DOI" |
| サイト指定 | `site:arxiv.org`, `site:pubmed`, `site:jstage` |
| DOI形式検出 | `10.xxxx/...` パターン |
| 明示的指定 | `options.academic=True`（Cursor AIからの指定） |

### 7.4 コードベース影響範囲サマリ

**変更が必要なファイル**:

| ファイル | 変更内容 |
|----------|----------|
| `src/search/apis/` | 新規: 学術APIクライアント群 |
| `src/search/academic_provider.py` | 新規: AcademicSearchProvider |
| `src/utils/schemas.py` | 追加: Paper, Author, Citation モデル |
| `src/research/pipeline.py` | 修正: 補完的検索のマージロジック |
| `src/storage/schema.sql` | 修正: `paper_metadata` カラム追加 |
| `src/filter/evidence_graph.py` | 修正: CITESエッジに属性追加 |
| `config/academic_apis.yaml` | 新規: API設定 |

**既存のまま活用するファイル**:

| ファイル | 理由 |
|----------|------|
| `src/extractor/content.py` | PDF抽出機能（PyMuPDF + OCR）は実装済み |
| `src/crawler/fetcher.py` | PDF取得・保存は対応済み |
| `src/search/provider.py` | `BaseSearchProvider`, `SourceTag.ACADEMIC` 既存 |
| `src/utils/api_retry.py` | `ACADEMIC_API_POLICY` 定義済み |

---

## 8. 設定ファイル

### 8.1 `config/academic_apis.yaml`

```yaml
# 学術API設定
apis:
  semantic_scholar:
    enabled: true
    base_url: "https://api.semanticscholar.org/graph/v1"
    rate_limit:
      requests_per_interval: 100
      interval_seconds: 300  # 5分
    timeout_seconds: 30
    priority: 1  # 最優先（引用グラフが最も充実）
    
  openalex:
    enabled: true
    base_url: "https://api.openalex.org"
    rate_limit:
      requests_per_day: 100000
    timeout_seconds: 30
    priority: 2
    headers:
      User-Agent: "Lyra/1.0 (research tool; mailto:lyra@example.com)"
    
  crossref:
    enabled: true
    base_url: "https://api.crossref.org"
    rate_limit:
      polite_pool: true  # User-Agentにメール設定で優遇
    timeout_seconds: 30
    priority: 3
    headers:
      User-Agent: "Lyra/1.0 (research tool; mailto:lyra@example.com)"
    
  arxiv:
    enabled: true
    base_url: "http://export.arxiv.org/api/query"
    rate_limit:
      min_interval_seconds: 3
    timeout_seconds: 30
    priority: 4  # プレプリント専用
    
  unpaywall:
    enabled: true
    base_url: "https://api.unpaywall.org/v2"
    rate_limit:
      requests_per_day: 100000
    timeout_seconds: 30
    priority: 5  # OAリンク解決専用
    email: "lyra@example.com"  # 必須

# デフォルト設定
defaults:
  search_apis: ["semantic_scholar", "openalex"]
  citation_graph_api: "semantic_scholar"
  max_citation_depth: 2
  max_papers_per_search: 50
```

---

## 9. テスト計画

### 9.1 テスト観点表

| Case ID | Input / Precondition | Perspective | Expected Result | Notes |
|---------|---------------------|-------------|-----------------|-------|
| TC-N-01 | 有効なクエリ "transformer attention" | 正常系 | 論文リスト返却 | - |
| TC-N-02 | 日本語クエリ "深層学習 医療" | 正常系 | 論文リスト返却 | - |
| TC-N-03 | DOIで検索 "10.1038/nature12373" | 正常系 | 該当論文返却 | - |
| TC-A-01 | 空クエリ "" | 異常系 | バリデーションエラー | - |
| TC-A-02 | API接続タイムアウト | 異常系 | リトライ後エラー返却 | ACADEMIC_API_POLICY |
| TC-A-03 | Rate Limit超過 (429) | 異常系 | バックオフ後リトライ | - |
| TC-B-01 | limit=0 | 境界値 | 空リスト返却 | - |
| TC-B-02 | limit=100 (最大) | 境界値 | 100件以下返却 | API制限 |
| TC-B-03 | depth=0 (引用グラフ) | 境界値 | 起点論文のみ | - |
| TC-I-01 | Semantic Scholar → OpenAlex フォールバック | 統合 | 2つのAPIから結果マージ | - |
| TC-I-02 | 引用グラフ → エビデンスグラフ | 統合 | PAPER/ACADEMIC_CITESノード追加 | - |

### 9.2 テストファイル構成

| ファイル | 内容 | 件数目安 |
|---------|------|:--------:|
| `tests/test_semantic_scholar.py` | SemanticScholarClient | 15 |
| `tests/test_openalex.py` | OpenAlexClient | 15 |
| `tests/test_crossref.py` | CrossrefClient | 10 |
| `tests/test_arxiv.py` | ArxivClient | 10 |
| `tests/test_academic_provider.py` | AcademicSearchProvider | 20 |
| `tests/test_evidence_graph_academic.py` | 学術拡張 | 15 |

### 9.3 E2E検証スクリプト

**`tests/scripts/debug_academic_api_flow.py`**

```python
"""
E2E検証: 学術API統合フロー

Usage:
    source .venv/bin/activate
    python tests/scripts/debug_academic_api_flow.py

検証項目:
1. Semantic Scholar検索
2. OpenAlex検索
3. 引用グラフ取得
4. エビデンスグラフ統合
5. 主張への学術的支持計算
"""
```

---

## 10. 実装タスクリスト

### 10.1 Phase 1: 基盤（Week 1）

- [ ] `src/utils/schemas.py`: `Paper`, `Citation`, `Author`, `AcademicSearchResult` モデル追加
- [ ] `src/search/apis/base.py`: `BaseAcademicClient` 抽象クラス
- [ ] `src/search/apis/semantic_scholar.py`: Semantic Scholar APIクライアント
- [ ] `tests/test_semantic_scholar.py`: ユニットテスト
- [ ] `config/academic_apis.yaml`: 設定ファイル

### 10.2 Phase 2: 追加API（Week 2）

- [ ] `src/search/apis/openalex.py`: OpenAlex APIクライアント
- [ ] `src/search/apis/crossref.py`: Crossref APIクライアント
- [ ] `src/search/apis/arxiv.py`: arXiv APIクライアント
- [ ] `tests/test_openalex.py`, `tests/test_crossref.py`, `tests/test_arxiv.py`

### 10.3 Phase 3: 統合（Week 3）

- [ ] `src/search/academic_provider.py`: `AcademicSearchProvider`
- [ ] `src/filter/evidence_graph.py`: `NodeType.PAPER`, `RelationType.ACADEMIC_CITES` 追加
- [ ] `src/storage/schema.sql`: `papers`, `academic_citations` テーブル追加
- [ ] `migrations/002_add_academic_tables.sql`: マイグレーション
- [ ] `src/research/executor.py`: 学術クエリ判定・ルーティング

### 10.4 Phase 4: テスト・検証（Week 4）

- [ ] `tests/test_academic_provider.py`: 統合テスト
- [ ] `tests/test_evidence_graph_academic.py`: エビデンスグラフ拡張テスト
- [ ] `tests/scripts/debug_academic_api_flow.py`: E2E検証スクリプト
- [ ] ドキュメント更新

---

## 11. 仕様書更新提案

### 11.1 `docs/REQUIREMENTS.md` への追記案

**§3.3.1 エビデンスグラフ拡張** に追記:

```markdown
- 学術引用グラフ統合:
  - 学術論文は `pages.page_type = 'academic_paper'` で識別
  - 学術メタデータは `pages.paper_metadata` (JSON) に格納
  - 既存CITESエッジに `is_academic`, `is_influential` 属性を追加
  - Semantic Scholar APIの"influential citations"フラグを活用
  - 引用チェーン深度≤3を推奨（孫引き以上は信頼度を減衰）
```

**§3.1.3 外部データソースAPI** を更新:

```markdown
- 学術API統合戦略（補完的アプローチ）:
  - 学術クエリ時は一般検索と学術API検索を並列実行し、結果をマージ
  - Semantic Scholar: 引用グラフ取得の主API（influential citations対応）
  - OpenAlex: メタデータ補完、大規模検索（100k/day + 10/sec）
  - Crossref: DOI解決、メタデータ正規化（polite pool推奨）
  - arXiv: プレプリント検索（3秒間隔、最大30,000件）
  - 優先順位: Semantic Scholar > OpenAlex > Crossref > arXiv
  - polite pool: mailto パラメータでrate limit優遇
```

**§7 品質基準** に追記:

```markdown
- 学術的支持の品質基準:
  - 学術主張に対し、査読済み論文からの支持≥1件
  - 支持論文の総被引用数≥10（影響力の指標）
  - 引用チェーンの深度≤3（孫引き以上は要注意フラグ）
  - influential citation（Semantic Scholar）を含む場合、信頼度を加点
```

---

## 12. リスクと対策

| リスク | 影響 | 対策 |
|-------|------|------|
| API Rate Limit超過 | 検索失敗 | `ACADEMIC_API_POLICY`でバックオフ、複数API分散 |
| APIサービス停止 | 機能停止 | フォールバック順序を設定、キャッシュ活用 |
| 大量の引用グラフ | メモリ不足 | depth制限、段階的取得、DB永続化 |
| 重複論文検出 | データ汚染 | DOIベースの重複排除 |
| 非英語論文の抄録なし | 情報欠落 | title検索にフォールバック |

---

## 13. 関連ドキュメント

- `docs/IMPLEMENTATION_PLAN.md` §Phase J.2
- `docs/REQUIREMENTS.md` §3.1.3, §3.3.1, §5.1
- `docs/O6_ADDITIONAL_ISSUES.md`（類似フォーマットの参考）

---

## 更新履歴

| 日付 | 内容 |
|------|------|
| 2025-12-16 | 初版作成 |
| 2025-12-16 | アーキテクチャ改訂: 補完的検索戦略に変更、PDFフルテキスト取得フロー追加、Paper/Page統合設計（ハイブリッド方式）、引用グラフ検索時取得、API仕様調査結果反映 |
| 2025-12-16 | **Abstract Only戦略採用**: PDFフルテキスト取得を設計上排除。学術論文は抄録＋メタデータのみ自動取得し、フルテキストは参照先（DOI/OA URL）として提示。Lancetは「コンテキストエンジニアリングの一部」として信頼性の高いサジェストに専念する設計思想を明確化 |

