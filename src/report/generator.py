"""
Report generator for Lancet.
Creates research reports from collected evidence.
"""

import json
import re
import unicodedata
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

from src.filter.claim_timeline import ClaimTimeline, TimelineEventType
from src.storage.database import get_database
from src.utils.config import get_settings
from src.utils.logging import get_logger

logger = get_logger(__name__)


def generate_anchor_slug(heading: str) -> str:
    """Generate URL anchor slug from heading text.
    
    Uses GitHub-style slug generation:
    - Lowercase
    - Replace spaces with hyphens
    - Remove special characters
    - Handle Japanese text (keep as-is, replace spaces)
    
    Args:
        heading: Heading text.
        
    Returns:
        URL-safe anchor slug.
    """
    if not heading:
        return ""

    # Normalize unicode
    text = unicodedata.normalize("NFKC", heading)

    # Lowercase
    text = text.lower()

    # Replace spaces and underscores with hyphens
    text = re.sub(r"[\s_]+", "-", text)

    # Remove characters that aren't alphanumeric, hyphens, or Japanese/CJK
    # Keep: a-z, 0-9, -, Japanese hiragana/katakana/kanji
    text = re.sub(r"[^\w\u3040-\u309f\u30a0-\u30ff\u4e00-\u9fff-]", "", text)

    # Remove leading/trailing hyphens
    text = text.strip("-")

    # Collapse multiple hyphens
    text = re.sub(r"-+", "-", text)

    return text


def generate_deep_link(url: str, heading_context: str | None) -> str:
    """Generate a deep link URL with anchor.
    
    Args:
        url: Base URL.
        heading_context: Heading context for anchor.
        
    Returns:
        URL with anchor fragment if heading is available.
    """
    if not heading_context:
        return url

    anchor = generate_anchor_slug(heading_context)
    if not anchor:
        return url

    # Parse URL and add fragment
    parsed = urlparse(url)

    # Don't override existing fragment
    if parsed.fragment:
        return url

    # Add anchor fragment
    new_url = urlunparse((
        parsed.scheme,
        parsed.netloc,
        parsed.path,
        parsed.params,
        parsed.query,
        anchor,
    ))

    return new_url


class Citation:
    """Represents a citation with deep link support.
    
    Per §3.4: All citations should have deep links to the relevant section.
    """

    def __init__(
        self,
        url: str,
        title: str,
        heading_context: str | None = None,
        excerpt: str | None = None,
        discovered_at: str | None = None,
        source_tag: str | None = None,
    ):
        self.url = url
        self.title = title
        self.heading_context = heading_context
        self.excerpt = excerpt
        self.discovered_at = discovered_at
        self.source_tag = source_tag

    @property
    def deep_link(self) -> str:
        """Get URL with anchor fragment."""
        return generate_deep_link(self.url, self.heading_context)

    @property
    def is_primary_source(self) -> bool:
        """Check if this is a primary source (§3.4: Source Priority Order)."""
        if not self.source_tag:
            return False
        return self.source_tag in ("government", "academic", "official", "standard", "registry")

    def to_markdown(self, index: int, include_excerpt: bool = True) -> str:
        """Format citation as Markdown.
        
        Args:
            index: Citation number.
            include_excerpt: Include excerpt text.
            
        Returns:
            Markdown formatted citation.
        """
        lines = []

        # Main citation line with deep link
        link = self.deep_link
        lines.append(f"{index}. [{self.title}]({link})")

        # Add section reference if available
        if self.heading_context:
            lines.append(f"   - セクション: {self.heading_context}")

        # Add source type indicator
        if self.source_tag:
            source_labels = {
                "government": "🏛️ 政府・公的機関",
                "academic": "📚 学術資料",
                "official": "✅ 公式発表",
                "standard": "📋 規格・標準",
                "registry": "📜 登記・登録",
                "news": "📰 ニュース",
                "blog": "📝 ブログ",
                "forum": "💬 フォーラム",
            }
            label = source_labels.get(self.source_tag, self.source_tag)
            lines.append(f"   - 種別: {label}")

        # Add excerpt if requested
        if include_excerpt and self.excerpt:
            excerpt_text = self.excerpt[:150]
            if len(self.excerpt) > 150:
                excerpt_text += "..."
            lines.append(f"   > {excerpt_text}")

        # Add discovery timestamp
        if self.discovered_at:
            try:
                dt = datetime.fromisoformat(self.discovered_at.replace("Z", "+00:00"))
                formatted = dt.strftime("%Y年%m月%d日")
                lines.append(f"   - 取得日: {formatted}")
            except (ValueError, AttributeError):
                pass

        return "\n".join(lines)


class ReportGenerator:
    """Generates research reports from evidence."""

    def __init__(self):
        self._settings = get_settings()

    async def generate(
        self,
        task_id: str,
        format_type: str = "markdown",
        include_evidence_graph: bool = True,
    ) -> dict[str, Any]:
        """Generate a research report.
        
        Args:
            task_id: Task ID to generate report for.
            format_type: Output format (markdown, json).
            include_evidence_graph: Include evidence graph.
            
        Returns:
            Report generation result.
        """
        db = await get_database()

        # Get task
        task = await db.fetch_one(
            "SELECT * FROM tasks WHERE id = ?",
            (task_id,),
        )

        if task is None:
            return {"ok": False, "error": f"Task not found: {task_id}"}

        # Get claims
        claims = await db.fetch_all(
            "SELECT * FROM claims WHERE task_id = ? ORDER BY confidence_score DESC",
            (task_id,),
        )

        # Get evidence (fragments with high scores)
        # Include source_tag for primary/secondary classification (§3.4)
        fragments = await db.fetch_all(
            """
            SELECT f.*, p.url, p.title as page_title, p.domain, s.source_tag
            FROM fragments f
            JOIN pages p ON f.page_id = p.id
            JOIN serp_items s ON p.url = s.url
            JOIN queries q ON s.query_id = q.id
            WHERE q.task_id = ?
              AND f.is_relevant = 1
            ORDER BY f.rerank_score DESC
            LIMIT 100
            """,
            (task_id,),
        )

        # Get evidence graph edges
        edges = []
        if include_evidence_graph:
            edges = await db.fetch_all(
                """
                SELECT * FROM edges
                WHERE source_id IN (SELECT id FROM claims WHERE task_id = ?)
                   OR target_id IN (SELECT id FROM claims WHERE task_id = ?)
                """,
                (task_id, task_id),
            )

        # Generate report
        if format_type == "markdown":
            report_content = await self._generate_markdown(task, claims, fragments, edges)
        else:
            report_content = await self._generate_json(task, claims, fragments, edges)

        # Save report
        reports_dir = Path(self._settings.storage.reports_dir)
        reports_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        ext = ".md" if format_type == "markdown" else ".json"
        filename = f"report_{task_id[:8]}_{timestamp}{ext}"
        filepath = reports_dir / filename

        filepath.write_text(report_content, encoding="utf-8")

        # Update task
        await db.update(
            "tasks",
            {
                "status": "completed",
                "result_summary": f"Report generated: {filename}",
                "completed_at": datetime.now(UTC).isoformat(),
            },
            "id = ?",
            (task_id,),
        )

        logger.info(
            "Report generated",
            task_id=task_id,
            format=format_type,
            filepath=str(filepath),
        )

        return {
            "ok": True,
            "task_id": task_id,
            "format": format_type,
            "filepath": str(filepath),
            "claim_count": len(claims),
            "fragment_count": len(fragments),
        }

    async def _generate_markdown(
        self,
        task: dict[str, Any],
        claims: list[dict[str, Any]],
        fragments: list[dict[str, Any]],
        edges: list[dict[str, Any]],
    ) -> str:
        """Generate markdown report.
        
        Args:
            task: Task record.
            claims: List of claims.
            fragments: List of relevant fragments.
            edges: Evidence graph edges.
            
        Returns:
            Markdown content.
        """
        lines = []

        # Title
        lines.append("# リサーチレポート")
        lines.append("")
        lines.append(f"**調査テーマ:** {task['query']}")
        lines.append(f"**生成日時:** {datetime.now().strftime('%Y年%m月%d日 %H:%M')}")
        lines.append(f"**タスクID:** {task['id']}")
        lines.append("")

        # Executive Summary
        lines.append("## エグゼクティブサマリー")
        lines.append("")

        if claims:
            # Top claims
            top_claims = [c for c in claims if c.get("confidence_score", 0) >= 0.7][:5]
            if top_claims:
                lines.append("### 主要な発見")
                lines.append("")
                for i, claim in enumerate(top_claims, 1):
                    confidence = claim.get("confidence_score", 0)
                    lines.append(f"{i}. {claim['claim_text']} (信頼度: {confidence:.2f})")
                lines.append("")

        # Methodology
        lines.append("## 調査方法")
        lines.append("")
        lines.append("本レポートは以下の手法で生成されました:")
        lines.append("")
        lines.append("1. 複数の検索エンジンを用いた網羅的な情報収集")
        lines.append("2. BM25、埋め込み、リランキングによる多段階の関連性評価")
        lines.append("3. ローカルLLMによる事実・主張の抽出")
        lines.append("4. NLIモデルによる立場の判定と矛盾検出")
        lines.append("")

        # Main Findings
        lines.append("## 主要な発見")
        lines.append("")

        if claims:
            # Group by type
            fact_claims = [c for c in claims if c.get("claim_type") == "fact"]
            opinion_claims = [c for c in claims if c.get("claim_type") == "opinion"]
            other_claims = [c for c in claims if c.get("claim_type") not in ("fact", "opinion")]

            if fact_claims:
                lines.append("### 事実")
                lines.append("")
                for claim in fact_claims[:10]:
                    confidence = claim.get("confidence_score", 0)
                    supporting = claim.get("supporting_count", 0)
                    refuting = claim.get("refuting_count", 0)

                    lines.append(f"- {claim['claim_text']}")
                    lines.append(f"  - 信頼度: {confidence:.2f}")
                    lines.append(f"  - 支持ソース: {supporting}件, 反証ソース: {refuting}件")
                    lines.append("")

            if opinion_claims:
                lines.append("### 意見・見解")
                lines.append("")
                for claim in opinion_claims[:5]:
                    lines.append(f"- {claim['claim_text']}")
                lines.append("")
        else:
            lines.append("*主張の抽出結果がありません*")
            lines.append("")

        # Evidence with deep links (§3.4: Source Priority Order)
        lines.append("## エビデンス")
        lines.append("")

        if fragments:
            # Separate primary and secondary sources
            primary_frags = [f for f in fragments if f.get("source_tag") in
                           ("government", "academic", "official", "standard", "registry")]
            secondary_frags = [f for f in fragments if f.get("source_tag") not in
                             ("government", "academic", "official", "standard", "registry")]

            # Primary sources first (§3.4)
            if primary_frags:
                lines.append("### 一次資料")
                lines.append("")

                for frag in primary_frags[:10]:
                    title = frag.get("page_title", "")
                    url = frag.get("url", "")
                    heading = frag.get("heading_context", "")
                    text = frag.get("text_content", "")[:200]

                    # Generate deep link
                    deep_url = generate_deep_link(url, heading)

                    lines.append(f"**[{title}]({deep_url})**")
                    if heading:
                        lines.append(f"📍 セクション: {heading}")
                    lines.append("")
                    lines.append(f"> {text}...")
                    lines.append("")

            # Secondary sources
            if secondary_frags:
                lines.append("### 二次資料")
                lines.append("")

                # Group by domain
                by_domain: dict[str, list] = {}
                for frag in secondary_frags:
                    domain = frag.get("domain", "unknown")
                    if domain not in by_domain:
                        by_domain[domain] = []
                    by_domain[domain].append(frag)

                for domain, frags in list(by_domain.items())[:8]:
                    lines.append(f"#### {domain}")
                    lines.append("")

                    for frag in frags[:2]:
                        title = frag.get("page_title", "")
                        url = frag.get("url", "")
                        heading = frag.get("heading_context", "")
                        text = frag.get("text_content", "")[:150]

                        # Generate deep link
                        deep_url = generate_deep_link(url, heading)

                        lines.append(f"**[{title}]({deep_url})**")
                        if heading:
                            lines.append(f"📍 セクション: {heading}")
                        lines.append("")
                        lines.append(f"> {text}...")
                        lines.append("")
        else:
            lines.append("*エビデンスがありません*")
            lines.append("")

        # Sources with full citations (§3.4: Deep Link Generation)
        lines.append("## 出典一覧")
        lines.append("")

        # Build citations list
        citations: list[Citation] = []
        seen_urls = set()

        for frag in fragments:
            url = frag.get("url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                citation = Citation(
                    url=url,
                    title=frag.get("page_title", url),
                    heading_context=frag.get("heading_context"),
                    excerpt=frag.get("text_content", "")[:200] if frag.get("text_content") else None,
                    discovered_at=frag.get("created_at"),
                    source_tag=frag.get("source_tag"),
                )
                citations.append(citation)

        # Sort: primary sources first
        citations.sort(key=lambda c: (0 if c.is_primary_source else 1, c.title))

        # Primary sources section
        primary_citations = [c for c in citations if c.is_primary_source]
        secondary_citations = [c for c in citations if not c.is_primary_source]

        if primary_citations:
            lines.append("### 一次資料")
            lines.append("")
            for i, citation in enumerate(primary_citations, 1):
                lines.append(citation.to_markdown(i, include_excerpt=False))
                lines.append("")

        if secondary_citations:
            lines.append("### 二次資料・その他")
            lines.append("")
            for i, citation in enumerate(secondary_citations, len(primary_citations) + 1):
                lines.append(citation.to_markdown(i, include_excerpt=False))
                lines.append("")

        lines.append("")

        # Timeline section (§3.4)
        timeline_lines = self._generate_timeline_section(claims)
        if timeline_lines:
            lines.extend(timeline_lines)

        # Limitations
        lines.append("## 制約事項")
        lines.append("")
        lines.append("- 本レポートは自動生成されたものであり、人間による検証を推奨します")
        lines.append("- 情報の鮮度は収集時点のものです")
        lines.append("- 商用APIを使用していないため、一部の情報源にアクセスできていない可能性があります")
        lines.append("")

        # Metadata
        lines.append("---")
        lines.append("")
        lines.append("*Generated by Lancet - Local Autonomous Deep Research Agent*")

        return "\n".join(lines)

    def _generate_timeline_section(
        self,
        claims: list[dict[str, Any]],
    ) -> list[str]:
        """Generate timeline section for report (§3.4).
        
        Args:
            claims: List of claims with timeline data.
            
        Returns:
            List of markdown lines for timeline section.
        """
        lines = []

        # Count claims with timelines
        claims_with_timeline = []
        retracted_claims = []
        corrected_claims = []

        for claim in claims:
            timeline_json = claim.get("timeline_json")
            if not timeline_json:
                continue

            timeline = ClaimTimeline.from_json(timeline_json)
            if timeline and timeline.has_timeline:
                claims_with_timeline.append((claim, timeline))

                if timeline.is_retracted:
                    retracted_claims.append((claim, timeline))
                if timeline.is_corrected:
                    corrected_claims.append((claim, timeline))

        if not claims_with_timeline:
            return []

        lines.append("## タイムライン")
        lines.append("")
        lines.append(f"タイムライン付与済み主張: {len(claims_with_timeline)}件 / {len(claims)}件")
        lines.append("")

        # Alert for retracted or corrected claims
        if retracted_claims:
            lines.append("### ⚠️ 撤回された主張")
            lines.append("")
            for claim, timeline in retracted_claims:
                lines.append(f"- ~~{claim.get('claim_text', '')}~~")
                retraction = next(
                    (e for e in timeline.events if e.event_type == TimelineEventType.RETRACTED),
                    None
                )
                if retraction:
                    lines.append(f"  - 撤回日: {retraction.timestamp.strftime('%Y年%m月%d日')}")
                    if retraction.notes:
                        lines.append(f"  - 理由: {retraction.notes}")
                    if retraction.source_url:
                        lines.append(f"  - 出典: [{retraction.source_url[:60]}...]({retraction.source_url})")
            lines.append("")

        if corrected_claims:
            lines.append("### 📝 訂正された主張")
            lines.append("")
            for claim, timeline in corrected_claims:
                lines.append(f"- {claim.get('claim_text', '')}")
                correction = next(
                    (e for e in timeline.events if e.event_type == TimelineEventType.CORRECTED),
                    None
                )
                if correction:
                    lines.append(f"  - 訂正日: {correction.timestamp.strftime('%Y年%m月%d日')}")
                    if correction.notes:
                        lines.append(f"  - 内容: {correction.notes}")
            lines.append("")

        # Show timeline for high-confidence claims
        high_confidence_with_timeline = [
            (c, t) for c, t in claims_with_timeline
            if (c.get("confidence_score") or 0) >= 0.7
            and not t.is_retracted
        ][:10]  # Limit to 10

        if high_confidence_with_timeline:
            lines.append("### 主要な主張のタイムライン")
            lines.append("")

            for claim, timeline in high_confidence_with_timeline:
                claim_text = claim.get("claim_text", "")
                if len(claim_text) > 80:
                    claim_text = claim_text[:77] + "..."

                lines.append(f"**{claim_text}**")
                lines.append("")

                # Show events
                for event in timeline.events[:5]:  # Limit events per claim
                    event_labels = {
                        TimelineEventType.FIRST_APPEARED: "📅 初出",
                        TimelineEventType.UPDATED: "🔄 更新",
                        TimelineEventType.CORRECTED: "📝 訂正",
                        TimelineEventType.RETRACTED: "⚠️ 撤回",
                        TimelineEventType.CONFIRMED: "✅ 確認",
                    }
                    label = event_labels.get(event.event_type, "📌")
                    date_str = event.timestamp.strftime("%Y年%m月%d日")

                    lines.append(f"- {label} {date_str}")
                    if event.source_url:
                        url_display = event.source_url[:50] + "..." if len(event.source_url) > 50 else event.source_url
                        lines.append(f"  - [{url_display}]({event.source_url})")
                    if event.wayback_snapshot_url:
                        lines.append(f"  - [📜 アーカイブ]({event.wayback_snapshot_url})")

                lines.append("")

        return lines

    async def _generate_json(
        self,
        task: dict[str, Any],
        claims: list[dict[str, Any]],
        fragments: list[dict[str, Any]],
        edges: list[dict[str, Any]],
    ) -> str:
        """Generate JSON report.
        
        Args:
            task: Task record.
            claims: List of claims.
            fragments: List of relevant fragments.
            edges: Evidence graph edges.
            
        Returns:
            JSON content.
        """
        # Parse timeline data for each claim
        claims_with_parsed_timeline = []
        timeline_stats = {
            "total_with_timeline": 0,
            "retracted": 0,
            "corrected": 0,
            "confirmed": 0,
        }

        for claim in claims:
            claim_copy = dict(claim)
            timeline_json = claim.get("timeline_json")

            if timeline_json:
                timeline = ClaimTimeline.from_json(timeline_json)
                if timeline and timeline.has_timeline:
                    claim_copy["timeline"] = timeline.to_dict()
                    timeline_stats["total_with_timeline"] += 1
                    if timeline.is_retracted:
                        timeline_stats["retracted"] += 1
                    if timeline.is_corrected:
                        timeline_stats["corrected"] += 1
                    if timeline.confirmation_count > 0:
                        timeline_stats["confirmed"] += 1

            claims_with_parsed_timeline.append(claim_copy)

        report = {
            "meta": {
                "task_id": task["id"],
                "query": task["query"],
                "generated_at": datetime.now(UTC).isoformat(),
                "generator": "Lancet",
            },
            "summary": {
                "claim_count": len(claims),
                "fragment_count": len(fragments),
                "edge_count": len(edges),
                "timeline": timeline_stats,
            },
            "claims": claims_with_parsed_timeline,
            "fragments": fragments,
            "evidence_graph": {
                "edges": edges,
            },
        }

        return json.dumps(report, ensure_ascii=False, indent=2)


# Global generator
_generator: ReportGenerator | None = None


async def generate_report(
    task_id: str,
    format_type: str = "markdown",
    include_evidence_graph: bool = True,
) -> dict[str, Any]:
    """Generate a research report (MCP tool handler).
    
    Args:
        task_id: Task ID.
        format_type: Output format.
        include_evidence_graph: Include evidence graph.
        
    Returns:
        Generation result.
    """
    global _generator
    if _generator is None:
        _generator = ReportGenerator()

    return await _generator.generate(
        task_id=task_id,
        format_type=format_type,
        include_evidence_graph=include_evidence_graph,
    )


async def get_report_materials(
    task_id: str,
    include_evidence_graph: bool = True,
    include_fragments: bool = True,
) -> dict[str, Any]:
    """Get report materials for Cursor AI to compose a report (§2.1 compliant).
    
    Returns structured data (claims, fragments, evidence graph) without
    generating the actual report. Report composition is Cursor AI's responsibility.
    
    Args:
        task_id: Task ID.
        include_evidence_graph: Include evidence graph structure.
        include_fragments: Include source fragments.
        
    Returns:
        Report materials as structured data.
    """
    db = await get_database()

    # Get task
    task = await db.fetch_one(
        "SELECT * FROM tasks WHERE id = ?",
        (task_id,),
    )

    if task is None:
        return {"ok": False, "error": f"Task not found: {task_id}"}

    # Get claims with supporting/refuting counts
    claims = await db.fetch_all(
        """
        SELECT 
            c.*,
            (SELECT COUNT(*) FROM edges e 
             WHERE e.target_id = c.id AND e.relation = 'supports') as support_count,
            (SELECT COUNT(*) FROM edges e 
             WHERE e.target_id = c.id AND e.relation = 'refutes') as refute_count
        FROM claims c
        WHERE c.task_id = ?
        ORDER BY c.confidence_score DESC
        """,
        (task_id,),
    )

    # Classify claims by confidence threshold (§4.5)
    high_confidence = [c for c in claims if (c.get("confidence_score") or 0) >= 0.7]
    low_confidence = [c for c in claims if (c.get("confidence_score") or 0) < 0.7]

    # Get fragments if requested
    fragments = []
    if include_fragments:
        fragments = await db.fetch_all(
            """
            SELECT f.*, p.url, p.title as page_title, p.domain, s.source_tag
            FROM fragments f
            JOIN pages p ON f.page_id = p.id
            LEFT JOIN serp_items s ON p.url = s.url
            LEFT JOIN queries q ON s.query_id = q.id
            WHERE q.task_id = ? AND f.is_relevant = 1
            ORDER BY f.rerank_score DESC
            LIMIT 200
            """,
            (task_id,),
        )

        # Classify by source type (§3.4: Source Priority Order)
        for frag in fragments:
            frag["is_primary_source"] = frag.get("source_tag") in (
                "government", "academic", "official", "standard", "registry"
            )
            # Add deep link
            if frag.get("url") and frag.get("heading_context"):
                frag["deep_link"] = generate_deep_link(
                    frag["url"], frag["heading_context"]
                )

    # Get evidence graph if requested
    evidence_graph = None
    if include_evidence_graph:
        edges = await db.fetch_all(
            """
            SELECT * FROM edges
            WHERE source_id IN (SELECT id FROM claims WHERE task_id = ?)
               OR target_id IN (SELECT id FROM claims WHERE task_id = ?)
            """,
            (task_id, task_id),
        )

        # Build graph summary
        supports = [e for e in edges if e.get("relation") == "supports"]
        refutes = [e for e in edges if e.get("relation") == "refutes"]
        cites = [e for e in edges if e.get("relation") == "cites"]

        evidence_graph = {
            "edges": edges,
            "summary": {
                "total_edges": len(edges),
                "supports_count": len(supports),
                "refutes_count": len(refutes),
                "cites_count": len(cites),
            },
        }

    # Build summary
    primary_sources = len([f for f in fragments if f.get("is_primary_source")])

    # Calculate timeline statistics (§3.4)
    timeline_stats = {
        "claims_with_timeline": 0,
        "claims_retracted": 0,
        "claims_corrected": 0,
        "claims_confirmed": 0,
        "coverage_rate": 0.0,
    }

    for claim in claims:
        timeline_json = claim.get("timeline_json")
        if timeline_json:
            timeline = ClaimTimeline.from_json(timeline_json)
            if timeline and timeline.has_timeline:
                timeline_stats["claims_with_timeline"] += 1
                if timeline.is_retracted:
                    timeline_stats["claims_retracted"] += 1
                if timeline.is_corrected:
                    timeline_stats["claims_corrected"] += 1
                if timeline.confirmation_count > 0:
                    timeline_stats["claims_confirmed"] += 1

    if claims:
        timeline_stats["coverage_rate"] = timeline_stats["claims_with_timeline"] / len(claims)

    logger.info(
        "Report materials retrieved",
        task_id=task_id,
        claims_count=len(claims),
        fragments_count=len(fragments),
        timeline_coverage=timeline_stats["coverage_rate"],
    )

    return {
        "ok": True,
        "task_id": task_id,
        "original_query": task.get("query"),
        "task_status": task.get("status"),
        "claims": {
            "high_confidence": high_confidence,
            "low_confidence": low_confidence,
            "total": len(claims),
        },
        "fragments": fragments if include_fragments else None,
        "evidence_graph": evidence_graph,
        "timeline": timeline_stats,
        "summary": {
            "claims_total": len(claims),
            "claims_high_confidence": len(high_confidence),
            "fragments_total": len(fragments),
            "primary_sources": primary_sources,
            "secondary_sources": len(fragments) - primary_sources,
            "timeline_coverage_rate": timeline_stats["coverage_rate"],
        },
    }


async def get_evidence_graph(
    task_id: str,
    claim_ids: list[str] | None = None,
    include_fragments: bool = True,
) -> dict[str, Any]:
    """Get evidence graph structure for a task.
    
    Returns nodes (claims, fragments) and edges (supports, refutes, cites)
    as structured data for Cursor AI to interpret.
    
    Args:
        task_id: Task ID.
        claim_ids: Optional filter by specific claim IDs.
        include_fragments: Include linked fragments.
        
    Returns:
        Evidence graph as structured data.
    """
    db = await get_database()

    # Get task
    task = await db.fetch_one(
        "SELECT * FROM tasks WHERE id = ?",
        (task_id,),
    )

    if task is None:
        return {"ok": False, "error": f"Task not found: {task_id}"}

    # Get claims
    if claim_ids:
        placeholders = ",".join("?" for _ in claim_ids)
        claims = await db.fetch_all(
            f"SELECT * FROM claims WHERE id IN ({placeholders})",
            claim_ids,
        )
    else:
        claims = await db.fetch_all(
            "SELECT * FROM claims WHERE task_id = ?",
            (task_id,),
        )

    claim_id_set = {c["id"] for c in claims}

    # Get edges involving these claims
    if claim_ids:
        placeholders = ",".join("?" for _ in claim_ids)
        edges = await db.fetch_all(
            f"""
            SELECT * FROM edges
            WHERE source_id IN ({placeholders})
               OR target_id IN ({placeholders})
            """,
            claim_ids + claim_ids,
        )
    else:
        edges = await db.fetch_all(
            """
            SELECT * FROM edges
            WHERE source_id IN (SELECT id FROM claims WHERE task_id = ?)
               OR target_id IN (SELECT id FROM claims WHERE task_id = ?)
            """,
            (task_id, task_id),
        )

    # Get linked fragments if requested
    fragments = []
    if include_fragments:
        # Get fragment IDs from edges
        fragment_ids = set()
        for edge in edges:
            if edge.get("source_type") == "fragment":
                fragment_ids.add(edge["source_id"])
            if edge.get("target_type") == "fragment":
                fragment_ids.add(edge["target_id"])

        if fragment_ids:
            placeholders = ",".join("?" for _ in fragment_ids)
            fragments = await db.fetch_all(
                f"""
                SELECT f.*, p.url, p.title as page_title, p.domain
                FROM fragments f
                JOIN pages p ON f.page_id = p.id
                WHERE f.id IN ({placeholders})
                """,
                list(fragment_ids),
            )

    # Build graph structure
    nodes = {
        "claims": [
            {
                "id": c["id"],
                "type": "claim",
                "text": c.get("claim_text"),
                "confidence": c.get("confidence_score"),
                "claim_type": c.get("claim_type"),
                "verified": c.get("is_verified"),
            }
            for c in claims
        ],
        "fragments": [
            {
                "id": f["id"],
                "type": "fragment",
                "text": f.get("text_content", "")[:500],
                "url": f.get("url"),
                "title": f.get("page_title"),
                "heading": f.get("heading_context"),
            }
            for f in fragments
        ],
    }

    # Classify edges
    edge_list = [
        {
            "id": e["id"],
            "source_type": e.get("source_type"),
            "source_id": e.get("source_id"),
            "target_type": e.get("target_type"),
            "target_id": e.get("target_id"),
            "relation": e.get("relation"),
            "confidence": e.get("confidence"),
        }
        for e in edges
    ]

    # Summary statistics
    relations = {}
    for e in edges:
        rel = e.get("relation", "unknown")
        relations[rel] = relations.get(rel, 0) + 1

    logger.info(
        "Evidence graph retrieved",
        task_id=task_id,
        claims=len(claims),
        fragments=len(fragments),
        edges=len(edges),
    )

    return {
        "ok": True,
        "task_id": task_id,
        "nodes": nodes,
        "edges": edge_list,
        "summary": {
            "claim_count": len(claims),
            "fragment_count": len(fragments),
            "edge_count": len(edges),
            "relations": relations,
        },
    }

