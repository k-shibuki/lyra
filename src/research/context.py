"""
Research context provider for Lancet.

Provides design support information to Cursor AI for subquery design.
Does NOT generate subquery candidates - that is Cursor AI's responsibility.

See requirements.md §2.1.4 and §3.1.7.1.

Includes pivot exploration support per §3.1.1:
- Organization → subsidiaries, officers, location, domain
- Domain → subdomain, certificate SAN, organization
- Person → aliases, handles, affiliations
"""

import re
from dataclasses import dataclass, field
from typing import Any

from src.storage.database import get_database
from src.utils.logging import get_logger
from src.research.pivot import (
    PivotExpander,
    PivotSuggestion,
    EntityType,
    detect_entity_type,
    get_pivot_expander,
)

logger = get_logger(__name__)


@dataclass
class EntityInfo:
    """Extracted entity information."""
    
    text: str
    entity_type: str  # person, organization, location, product, event
    context: str  # Surrounding text where entity was found
    confidence: float = 1.0


@dataclass
class TemplateInfo:
    """Vertical template information."""
    
    name: str  # academic, government, corporate, technical
    description: str
    example_operators: list[str] = field(default_factory=list)
    recommended_engines: list[str] = field(default_factory=list)


@dataclass
class PastQueryInfo:
    """Information about similar past queries."""
    
    query: str
    harvest_rate: float
    success_engines: list[str] = field(default_factory=list)


# Predefined vertical templates
VERTICAL_TEMPLATES = {
    "academic": TemplateInfo(
        name="academic",
        description="学術・研究資料向けテンプレート",
        example_operators=["site:arxiv.org", "site:pubmed.gov", "filetype:pdf", "site:jstage.jst.go.jp"],
        recommended_engines=["duckduckgo", "qwant"],
    ),
    "government": TemplateInfo(
        name="government",
        description="政府・公的機関向けテンプレート",
        example_operators=["site:go.jp", "site:gov.uk", "site:who.int", "filetype:pdf"],
        recommended_engines=["duckduckgo", "qwant", "mojeek"],
    ),
    "corporate": TemplateInfo(
        name="corporate",
        description="企業・IR情報向けテンプレート",
        example_operators=["site:edinet-fsa.go.jp", "IR", "有価証券報告書", "プレスリリース"],
        recommended_engines=["duckduckgo", "qwant"],
    ),
    "technical": TemplateInfo(
        name="technical",
        description="技術文書・仕様書向けテンプレート",
        example_operators=["filetype:pdf", "specification", "RFC", "仕様書"],
        recommended_engines=["duckduckgo", "mojeek"],
    ),
    "news": TemplateInfo(
        name="news",
        description="ニュース・報道向けテンプレート",
        example_operators=["after:2024-01-01", "ニュース", "報道"],
        recommended_engines=["duckduckgo", "qwant"],
    ),
}

# Entity type patterns (simple regex-based, not using full NER)
ENTITY_PATTERNS = {
    "organization": [
        r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\s+(?:Inc|Corp|Ltd|LLC|Co|会社|株式会社|有限会社)\.?)",
        r"(株式会社[^\s、。]+)",
        r"([^\s、。]+株式会社)",
    ],
    "location": [
        r"(東京|大阪|名古屋|福岡|札幌|横浜|神戸|京都)",
        r"([A-Z][a-z]+(?:,\s*[A-Z]{2})?)",  # City, State format
    ],
    "product": [
        r"([A-Z][a-zA-Z0-9]+(?:\s+[A-Z0-9][a-zA-Z0-9]*)*)",  # Product names
    ],
}


class ResearchContext:
    """
    Provides design support information for Cursor AI.
    
    This class extracts entities, suggests applicable templates,
    and retrieves past query success rates. It does NOT generate
    subquery candidates - that responsibility belongs to Cursor AI.
    """
    
    def __init__(self, task_id: str):
        """Initialize research context for a task.
        
        Args:
            task_id: The task ID to provide context for.
        """
        self.task_id = task_id
        self._db = None
        self._task = None
        self._original_query: str = ""
    
    async def _ensure_db(self) -> None:
        """Ensure database connection is available."""
        if self._db is None:
            self._db = await get_database()
    
    async def _load_task(self) -> None:
        """Load task information from database."""
        await self._ensure_db()
        self._task = await self._db.fetch_one(
            "SELECT * FROM tasks WHERE id = ?",
            (self.task_id,),
        )
        if self._task:
            self._original_query = self._task.get("query", "")
    
    async def get_context(self) -> dict[str, Any]:
        """
        Get design support information for Cursor AI.
        
        Returns:
            Dictionary containing:
            - original_query: The research question
            - extracted_entities: List of extracted entities
            - applicable_templates: List of applicable vertical templates
            - similar_past_queries: Past queries with success rates
            - recommended_engines: Engines recommended for this query
            - high_success_domains: Domains with high success rates
            - pivot_suggestions: Pivot exploration suggestions (§3.1.1)
            - notes: Additional hints for Cursor AI
            
        Note:
            This does NOT include subquery candidates.
            Cursor AI designs subqueries using this information.
        """
        await self._load_task()
        
        if not self._task:
            return {
                "ok": False,
                "error": f"Task not found: {self.task_id}",
            }
        
        entities = await self._extract_entities()
        templates = self._get_applicable_templates()
        past_queries = await self._get_similar_past_queries()
        recommended_engines = await self._get_recommended_engines()
        high_success_domains = await self._get_high_success_domains()
        
        # Generate pivot suggestions for extracted entities (§3.1.1)
        pivot_suggestions = self._get_pivot_suggestions(entities)
        
        return {
            "ok": True,
            "task_id": self.task_id,
            "original_query": self._original_query,
            "extracted_entities": [
                {
                    "text": e.text,
                    "type": e.entity_type,
                    "context": e.context,
                }
                for e in entities
            ],
            "applicable_templates": [
                {
                    "name": t.name,
                    "description": t.description,
                    "example_operators": t.example_operators,
                }
                for t in templates
            ],
            "similar_past_queries": [
                {
                    "query": p.query,
                    "harvest_rate": p.harvest_rate,
                    "success_engines": p.success_engines,
                }
                for p in past_queries
            ],
            "recommended_engines": recommended_engines,
            "high_success_domains": high_success_domains,
            "pivot_suggestions": pivot_suggestions,
            "notes": self._generate_notes(entities, templates),
        }
    
    async def _extract_entities(self) -> list[EntityInfo]:
        """
        Extract entities from the original query.
        
        Uses simple pattern matching. For production, consider
        using a proper NER model via the local LLM.
        """
        entities = []
        query = self._original_query
        
        for entity_type, patterns in ENTITY_PATTERNS.items():
            for pattern in patterns:
                try:
                    matches = re.findall(pattern, query)
                    for match in matches:
                        if isinstance(match, tuple):
                            match = match[0]
                        if len(match) > 2:  # Filter very short matches
                            entities.append(EntityInfo(
                                text=match,
                                entity_type=entity_type,
                                context=query,
                            ))
                except re.error:
                    continue
        
        # Deduplicate by text
        seen = set()
        unique_entities = []
        for e in entities:
            if e.text not in seen:
                seen.add(e.text)
                unique_entities.append(e)
        
        return unique_entities
    
    def _get_applicable_templates(self) -> list[TemplateInfo]:
        """
        Determine applicable vertical templates based on query content.
        """
        templates = []
        query_lower = self._original_query.lower()
        
        # Academic indicators
        academic_keywords = ["研究", "論文", "学術", "研究", "paper", "study", "research", "journal"]
        if any(kw in query_lower for kw in academic_keywords):
            templates.append(VERTICAL_TEMPLATES["academic"])
        
        # Government indicators
        gov_keywords = ["政府", "省", "庁", "官", "法律", "規制", "government", "regulation", "policy"]
        if any(kw in query_lower for kw in gov_keywords):
            templates.append(VERTICAL_TEMPLATES["government"])
        
        # Corporate indicators
        corp_keywords = ["会社", "企業", "株式", "IR", "決算", "業績", "company", "corporation"]
        if any(kw in query_lower for kw in corp_keywords):
            templates.append(VERTICAL_TEMPLATES["corporate"])
        
        # Technical indicators
        tech_keywords = ["技術", "仕様", "規格", "プロトコル", "API", "specification", "protocol", "standard"]
        if any(kw in query_lower for kw in tech_keywords):
            templates.append(VERTICAL_TEMPLATES["technical"])
        
        # News indicators
        news_keywords = ["ニュース", "報道", "最新", "news", "latest", "recent"]
        if any(kw in query_lower for kw in news_keywords):
            templates.append(VERTICAL_TEMPLATES["news"])
        
        # If no specific match, suggest general templates
        if not templates:
            templates = [VERTICAL_TEMPLATES["academic"], VERTICAL_TEMPLATES["government"]]
        
        return templates
    
    async def _get_similar_past_queries(self) -> list[PastQueryInfo]:
        """
        Find similar past queries and their success rates.
        """
        await self._ensure_db()
        
        # Get recent successful queries with good harvest rates
        past_queries = await self._db.fetch_all(
            """
            SELECT query_text, harvest_rate, engines_used
            FROM queries
            WHERE harvest_rate > 0.2
            ORDER BY created_at DESC
            LIMIT 10
            """,
        )
        
        results = []
        for pq in past_queries:
            # Simple similarity check (could use embeddings for better matching)
            query_text = pq.get("query_text", "")
            if self._is_similar_query(query_text):
                engines = []
                if pq.get("engines_used"):
                    try:
                        import json
                        engines = json.loads(pq["engines_used"])
                    except (json.JSONDecodeError, TypeError):
                        pass
                
                results.append(PastQueryInfo(
                    query=query_text,
                    harvest_rate=pq.get("harvest_rate", 0),
                    success_engines=engines,
                ))
        
        return results[:5]  # Limit to top 5
    
    def _is_similar_query(self, past_query: str) -> bool:
        """Check if a past query is similar to current query."""
        # Simple word overlap check
        current_words = set(self._original_query.lower().split())
        past_words = set(past_query.lower().split())
        
        if not current_words or not past_words:
            return False
        
        overlap = len(current_words & past_words)
        min_len = min(len(current_words), len(past_words))
        
        return overlap / min_len > 0.3 if min_len > 0 else False
    
    async def _get_recommended_engines(self) -> list[str]:
        """
        Get recommended search engines based on health and success rates.
        """
        await self._ensure_db()
        
        # Get healthy engines sorted by success rate
        engines = await self._db.fetch_all(
            """
            SELECT engine, success_rate_24h, weight
            FROM engine_health
            WHERE status != 'open'
            ORDER BY success_rate_24h * weight DESC
            LIMIT 5
            """,
        )
        
        if engines:
            return [e["engine"] for e in engines]
        
        # Default recommendations
        return ["duckduckgo", "qwant", "mojeek"]
    
    async def _get_high_success_domains(self) -> list[str]:
        """
        Get domains with historically high success rates.
        """
        await self._ensure_db()
        
        domains = await self._db.fetch_all(
            """
            SELECT domain, success_rate_24h
            FROM domains
            WHERE success_rate_24h > 0.8
              AND total_requests > 5
            ORDER BY success_rate_24h DESC
            LIMIT 10
            """,
        )
        
        if domains:
            return [d["domain"] for d in domains]
        
        # Default high-success domains
        return ["go.jp", "who.int", "arxiv.org", "wikipedia.org"]
    
    def _generate_notes(
        self,
        entities: list[EntityInfo],
        templates: list[TemplateInfo],
    ) -> str:
        """
        Generate helpful notes for Cursor AI.
        """
        notes = []
        
        if entities:
            entity_types = set(e.entity_type for e in entities)
            if "organization" in entity_types:
                notes.append("組織名が検出されました。IR情報や公式サイトの検索が有効です。")
            if "location" in entity_types:
                notes.append("地名が検出されました。地域特化の検索が有効です。")
        
        if any(t.name == "academic" for t in templates):
            notes.append("学術検索が推奨されます（site:arxiv.org, site:jstage.jst.go.jp等）。")
        
        if any(t.name == "government" for t in templates):
            notes.append("政府系サイト検索が推奨されます（site:go.jp等）。")
        
        return " ".join(notes) if notes else "特記事項なし"
    
    def _get_pivot_suggestions(
        self,
        entities: list[EntityInfo],
    ) -> list[dict[str, Any]]:
        """
        Generate pivot exploration suggestions for entities.
        
        Implements §3.1.1 pivot exploration patterns:
        - Organization → subsidiaries, officers, location, domain
        - Domain → subdomain, certificate SAN, organization
        - Person → aliases, handles, affiliations
        
        Args:
            entities: List of extracted entities.
            
        Returns:
            List of pivot suggestion dictionaries.
        """
        if not entities:
            return []
        
        pivot_expander = get_pivot_expander()
        
        # Convert EntityInfo to dict format expected by PivotExpander
        entity_dicts = [
            {
                "text": e.text,
                "type": e.entity_type,
                "context": e.context,
            }
            for e in entities
        ]
        
        # Get priority pivots (top suggestions)
        pivots = pivot_expander.get_priority_pivots(
            entity_dicts,
            max_per_entity=3,
        )
        
        # Convert to serializable format
        return [
            {
                "pivot_type": p.pivot_type.value,
                "source_entity": p.source_entity,
                "query_examples": p.query_examples[:3],  # Limit examples
                "target_entity_type": p.target_entity_type.value if p.target_entity_type else None,
                "priority": p.priority,
                "rationale": p.rationale,
                "operators": p.operators,
            }
            for p in pivots
        ]






