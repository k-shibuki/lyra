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
| §3.1 | 学術・公的は直接ソース（arXiv, PubMed等）を優先 | AcademicSearchProvider実装 |
| §3.1.3 | OpenAlex/Semantic Scholar/Crossref/Unpaywall APIの利用 | 4つのAPIクライアント実装 |
| §3.3.1 | エビデンスグラフ: supports/refutes/citesエッジ | `academic_cites`エッジ追加 |
| §4.3.5 | 公式APIへのバックオフ付きリトライ | `ACADEMIC_API_POLICY`適用 |
| §5.1 | 学術: OpenAlex/Semantic Scholar/Crossref/Unpaywall | 外部依存として明記 |
| §7 | ソース階層: 一次資料 > 公的機関 > 学術 | 信頼度計算に反映 |

### 1.3 Zero OpEx原則との適合

| API | 料金 | 認証 | Rate Limit | 適合 |
|-----|:----:|:----:|:----------:|:----:|
| **Semantic Scholar** | 無料 | 不要 | 100/5min | ✅ |
| **OpenAlex** | 無料 | 不要 | 100k/day | ✅ |
| **Crossref** | 無料 | 不要 | polite pool | ✅ |
| **arXiv API** | 無料 | 不要 | 3秒間隔 | ✅ |
| **Unpaywall** | 無料 | メール | 100k/day | ✅ |

---

## 2. アーキテクチャ設計

### 2.1 全体構成

```
┌─────────────────────────────────────────────────────────────────┐
│                      SearchProviderRegistry                      │
├─────────────────────────────────────────────────────────────────┤
│  BrowserSearchProvider     │  AcademicSearchProvider (NEW)      │
│  (検索エンジン用)           │  (学術API用)                        │
└─────────────────────────────────────────────────────────────────┘
                                      │
                    ┌─────────────────┼─────────────────┐
                    │                 │                 │
           ┌────────▼───────┐ ┌──────▼──────┐ ┌───────▼───────┐
           │ SemanticScholar │ │  OpenAlex   │ │   Crossref    │
           │    Client       │ │   Client    │ │    Client     │
           └────────┬────────┘ └──────┬──────┘ └───────┬───────┘
                    │                 │                 │
                    └─────────────────┼─────────────────┘
                                      │
                    ┌─────────────────▼─────────────────┐
                    │        EvidenceGraph 拡張         │
                    │  NodeType.PAPER (NEW)            │
                    │  RelationType.ACADEMIC_CITES (NEW)│
                    └───────────────────────────────────┘
```

### 2.2 モジュール構成

| ディレクトリ | ファイル | 役割 |
|------------|---------|------|
| `src/search/apis/` | `__init__.py` | APIクライアント共通エクスポート |
| | `base.py` | `BaseAcademicClient` 抽象クラス |
| | `semantic_scholar.py` | Semantic Scholar APIクライアント |
| | `openalex.py` | OpenAlex APIクライアント |
| | `crossref.py` | Crossref APIクライアント |
| | `arxiv.py` | arXiv OAI-PMH クライアント |
| | `unpaywall.py` | Unpaywall APIクライアント |
| `src/search/` | `academic_provider.py` | `AcademicSearchProvider` 統合プロバイダ |
| `src/filter/` | `evidence_graph.py` | `NodeType.PAPER`, `RelationType.ACADEMIC_CITES` 追加 |
| `src/utils/` | `schemas.py` | `Paper`, `Citation`, `Author` Pydanticモデル |
| `config/` | `academic_apis.yaml` | API設定（エンドポイント、rate limit等） |

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

### 3.2 エビデンスグラフ拡張（`src/filter/evidence_graph.py`）

```python
# 既存
class NodeType(str, Enum):
    CLAIM = "claim"
    FRAGMENT = "fragment"
    PAGE = "page"
    PAPER = "paper"  # NEW: 学術論文ノード

class RelationType(str, Enum):
    SUPPORTS = "supports"
    REFUTES = "refutes"
    CITES = "cites"
    NEUTRAL = "neutral"
    ACADEMIC_CITES = "academic_cites"  # NEW: 学術引用（正式な引用関係）
```

**拡張理由**:
- `PAGE`と`PAPER`の区別: 学術論文は構造化メタデータ（著者、DOI、引用数）を持つ
- `CITES`と`ACADEMIC_CITES`の区別: 学術引用は正式な引用関係であり、信頼度が高い

### 3.3 DBスキーマ拡張（`src/storage/schema.sql`）

```sql
-- 学術論文テーブル（NEW）
CREATE TABLE IF NOT EXISTS papers (
    id TEXT PRIMARY KEY,
    task_id TEXT,
    title TEXT NOT NULL,
    abstract TEXT,
    authors TEXT,  -- JSON配列
    year INTEGER,
    published_date TEXT,
    doi TEXT UNIQUE,
    arxiv_id TEXT,
    venue TEXT,
    citation_count INTEGER DEFAULT 0,
    reference_count INTEGER DEFAULT 0,
    is_open_access INTEGER DEFAULT 0,
    oa_url TEXT,
    pdf_url TEXT,
    source_api TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (task_id) REFERENCES tasks(id)
);

CREATE INDEX IF NOT EXISTS idx_papers_doi ON papers(doi);
CREATE INDEX IF NOT EXISTS idx_papers_task_id ON papers(task_id);
CREATE INDEX IF NOT EXISTS idx_papers_year ON papers(year);

-- 学術引用テーブル（NEW）
CREATE TABLE IF NOT EXISTS academic_citations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    citing_paper_id TEXT NOT NULL,
    cited_paper_id TEXT NOT NULL,
    context TEXT,
    is_influential INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (citing_paper_id) REFERENCES papers(id),
    FOREIGN KEY (cited_paper_id) REFERENCES papers(id),
    UNIQUE(citing_paper_id, cited_paper_id)
);

CREATE INDEX IF NOT EXISTS idx_academic_citations_citing ON academic_citations(citing_paper_id);
CREATE INDEX IF NOT EXISTS idx_academic_citations_cited ON academic_citations(cited_paper_id);
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
                headers={"User-Agent": "Lancet/1.0 (research tool; mailto:lancet@example.com)"}
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

### 6.1 検索パイプライン連携

**変更ファイル**: `src/research/executor.py`

```python
async def _execute_search(self, query: str) -> tuple[list[dict], str | None, dict]:
    """検索実行（学術ソース判定追加）."""
    
    # 学術クエリ判定
    if self._is_academic_query(query):
        from src.search.academic_provider import get_academic_provider
        provider = get_academic_provider()
        response = await provider.search(query, options)
        return [r.to_dict() for r in response.results], None, {}
    
    # 既存のブラウザ検索
    return await self._execute_browser_search(query)

def _is_academic_query(self, query: str) -> bool:
    """学術クエリかどうかを判定.
    
    判定基準:
    - 明示的指定: engines=["semantic_scholar", "arxiv"]
    - キーワード: "論文", "paper", "研究", "study", "arXiv", "DOI"
    - サイト指定: site:arxiv.org, site:pubmed
    """
    academic_keywords = [
        "論文", "paper", "研究", "study", "学術",
        "arxiv", "pubmed", "doi:", "10.1", "journal"
    ]
    query_lower = query.lower()
    return any(kw in query_lower for kw in academic_keywords)
```

### 6.2 エビデンスグラフ連携

**変更ファイル**: `src/filter/evidence_graph.py`

```python
async def add_paper_with_citations(
    self,
    paper: Paper,
    citations: list[Citation],
) -> None:
    """論文と引用関係をグラフに追加.
    
    Args:
        paper: 論文メタデータ
        citations: 引用関係リスト
    """
    # 論文ノードを追加
    self.add_node(
        NodeType.PAPER,
        paper.id,
        title=paper.title,
        doi=paper.doi,
        year=paper.year,
        citation_count=paper.citation_count,
        source_api=paper.source_api,
    )
    
    # 引用エッジを追加
    for citation in citations:
        # 被引用論文ノードが存在しなければ追加（軽量版）
        cited_node = self._make_node_id(NodeType.PAPER, citation.cited_paper_id)
        if not self._graph.has_node(cited_node):
            self.add_node(NodeType.PAPER, citation.cited_paper_id)
        
        # 学術引用エッジを追加
        self.add_edge(
            NodeType.PAPER, citation.citing_paper_id,
            NodeType.PAPER, citation.cited_paper_id,
            RelationType.ACADEMIC_CITES,
            is_influential=citation.is_influential,
            context=citation.context,
        )

def calculate_academic_support(self, claim_id: str) -> dict[str, Any]:
    """主張に対する学術的支持を計算.
    
    Returns:
        {
            "supporting_papers": [...],  # 主張を支持する論文
            "total_citations": int,      # 支持論文の総被引用数
            "avg_year": float,           # 支持論文の平均発行年
            "has_influential": bool,     # influential citationを含むか
        }
    """
    claim_node = self._make_node_id(NodeType.CLAIM, claim_id)
    
    # 主張を支持するフラグメント → ソースページ → 論文 を辿る
    supporting_papers = []
    for fragment_node in self._graph.predecessors(claim_node):
        edge = self._graph.edges[fragment_node, claim_node]
        if edge.get("relation") != RelationType.SUPPORTS.value:
            continue
        
        # フラグメント → ページ → 論文
        for page_node in self._graph.predecessors(fragment_node):
            for paper_node in self._graph.predecessors(page_node):
                node_data = self._graph.nodes[paper_node]
                if node_data.get("node_type") == NodeType.PAPER.value:
                    supporting_papers.append(node_data)
    
    if not supporting_papers:
        return {"supporting_papers": [], "total_citations": 0, "avg_year": 0, "has_influential": False}
    
    return {
        "supporting_papers": supporting_papers,
        "total_citations": sum(p.get("citation_count", 0) for p in supporting_papers),
        "avg_year": sum(p.get("year", 0) for p in supporting_papers) / len(supporting_papers),
        "has_influential": any(
            self._graph.edges[p, c].get("is_influential")
            for p in supporting_papers
            for c in self._graph.successors(self._make_node_id(NodeType.PAPER, p.get("obj_id")))
        ),
    }
```

---

## 7. 設定ファイル

### 7.1 `config/academic_apis.yaml`

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
      User-Agent: "Lancet/1.0 (research tool; mailto:lancet@example.com)"
    
  crossref:
    enabled: true
    base_url: "https://api.crossref.org"
    rate_limit:
      polite_pool: true  # User-Agentにメール設定で優遇
    timeout_seconds: 30
    priority: 3
    headers:
      User-Agent: "Lancet/1.0 (research tool; mailto:lancet@example.com)"
    
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
    email: "lancet@example.com"  # 必須

# デフォルト設定
defaults:
  search_apis: ["semantic_scholar", "openalex"]
  citation_graph_api: "semantic_scholar"
  max_citation_depth: 2
  max_papers_per_search: 50
```

---

## 8. テスト計画

### 8.1 テスト観点表

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

### 8.2 テストファイル構成

| ファイル | 内容 | 件数目安 |
|---------|------|:--------:|
| `tests/test_semantic_scholar.py` | SemanticScholarClient | 15 |
| `tests/test_openalex.py` | OpenAlexClient | 15 |
| `tests/test_crossref.py` | CrossrefClient | 10 |
| `tests/test_arxiv.py` | ArxivClient | 10 |
| `tests/test_academic_provider.py` | AcademicSearchProvider | 20 |
| `tests/test_evidence_graph_academic.py` | 学術拡張 | 15 |

### 8.3 E2E検証スクリプト

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

## 9. 実装タスクリスト

### 9.1 Phase 1: 基盤（Week 1）

- [ ] `src/utils/schemas.py`: `Paper`, `Citation`, `Author`, `AcademicSearchResult` モデル追加
- [ ] `src/search/apis/base.py`: `BaseAcademicClient` 抽象クラス
- [ ] `src/search/apis/semantic_scholar.py`: Semantic Scholar APIクライアント
- [ ] `tests/test_semantic_scholar.py`: ユニットテスト
- [ ] `config/academic_apis.yaml`: 設定ファイル

### 9.2 Phase 2: 追加API（Week 2）

- [ ] `src/search/apis/openalex.py`: OpenAlex APIクライアント
- [ ] `src/search/apis/crossref.py`: Crossref APIクライアント
- [ ] `src/search/apis/arxiv.py`: arXiv APIクライアント
- [ ] `tests/test_openalex.py`, `tests/test_crossref.py`, `tests/test_arxiv.py`

### 9.3 Phase 3: 統合（Week 3）

- [ ] `src/search/academic_provider.py`: `AcademicSearchProvider`
- [ ] `src/filter/evidence_graph.py`: `NodeType.PAPER`, `RelationType.ACADEMIC_CITES` 追加
- [ ] `src/storage/schema.sql`: `papers`, `academic_citations` テーブル追加
- [ ] `migrations/002_add_academic_tables.sql`: マイグレーション
- [ ] `src/research/executor.py`: 学術クエリ判定・ルーティング

### 9.4 Phase 4: テスト・検証（Week 4）

- [ ] `tests/test_academic_provider.py`: 統合テスト
- [ ] `tests/test_evidence_graph_academic.py`: エビデンスグラフ拡張テスト
- [ ] `tests/scripts/debug_academic_api_flow.py`: E2E検証スクリプト
- [ ] ドキュメント更新

---

## 10. 仕様書更新提案

### 10.1 `docs/requirements.md` への追記案

**§3.3.1 エビデンスグラフ拡張** に追記:

```markdown
- 学術引用グラフ統合:
  - ノードタイプ: `PAPER`（学術論文）を追加
  - エッジタイプ: `academic_cites`（正式な学術引用関係）を追加
  - 学術引用は信頼度が高い（正式な引用関係のため）
  - Semantic Scholar APIの"influential citations"フラグを活用
```

**§3.1.3 外部データソースAPI** を更新:

```markdown
- 学術API統合戦略:
  - Semantic Scholar: 引用グラフ取得の主API（influential citations対応）
  - OpenAlex: メタデータ補完、大規模検索
  - Crossref: DOI解決、メタデータ正規化
  - arXiv: プレプリント検索
  - Unpaywall: OA版リンク解決
  - 優先順位: Semantic Scholar > OpenAlex > Crossref > arXiv
```

**§7 品質基準** に追記:

```markdown
- 学術的支持の品質基準:
  - 学術主張に対し、査読済み論文からの支持≥1件
  - 支持論文の総被引用数≥10（影響力の指標）
  - 引用チェーンの深度≤3（孫引き以上は要注意フラグ）
```

---

## 11. リスクと対策

| リスク | 影響 | 対策 |
|-------|------|------|
| API Rate Limit超過 | 検索失敗 | `ACADEMIC_API_POLICY`でバックオフ、複数API分散 |
| APIサービス停止 | 機能停止 | フォールバック順序を設定、キャッシュ活用 |
| 大量の引用グラフ | メモリ不足 | depth制限、段階的取得、DB永続化 |
| 重複論文検出 | データ汚染 | DOIベースの重複排除 |
| 非英語論文の抄録なし | 情報欠落 | title検索にフォールバック |

---

## 12. 関連ドキュメント

- `docs/IMPLEMENTATION_PLAN.md` §Phase J.2
- `docs/requirements.md` §3.1.3, §3.3.1, §5.1
- `docs/O6_ADDITIONAL_ISSUES.md`（類似フォーマットの参考）

---

## 更新履歴

| 日付 | 内容 |
|------|------|
| 2025-12-16 | 初版作成 |

