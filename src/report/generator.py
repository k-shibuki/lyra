"""
Report generator for Lancet.
Creates research reports from collected evidence.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.utils.config import get_settings
from src.utils.logging import get_logger
from src.storage.database import get_database

logger = get_logger(__name__)


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
        fragments = await db.fetch_all(
            """
            SELECT f.*, p.url, p.title as page_title, p.domain
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
                "completed_at": datetime.now(timezone.utc).isoformat(),
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
        lines.append(f"# リサーチレポート")
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
        
        # Evidence
        lines.append("## エビデンス")
        lines.append("")
        
        if fragments:
            # Group by domain
            by_domain: dict[str, list] = {}
            for frag in fragments:
                domain = frag.get("domain", "unknown")
                if domain not in by_domain:
                    by_domain[domain] = []
                by_domain[domain].append(frag)
            
            for domain, frags in list(by_domain.items())[:10]:
                lines.append(f"### {domain}")
                lines.append("")
                
                for frag in frags[:3]:
                    title = frag.get("page_title", "")
                    url = frag.get("url", "")
                    text = frag.get("text_content", "")[:200]
                    
                    lines.append(f"**{title}**")
                    lines.append(f"URL: {url}")
                    lines.append("")
                    lines.append(f"> {text}...")
                    lines.append("")
        else:
            lines.append("*エビデンスがありません*")
            lines.append("")
        
        # Sources
        lines.append("## 出典一覧")
        lines.append("")
        
        seen_urls = set()
        source_count = 0
        
        for frag in fragments:
            url = frag.get("url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                source_count += 1
                title = frag.get("page_title", url)
                lines.append(f"{source_count}. [{title}]({url})")
        
        lines.append("")
        
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
        report = {
            "meta": {
                "task_id": task["id"],
                "query": task["query"],
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "generator": "Lancet",
            },
            "summary": {
                "claim_count": len(claims),
                "fragment_count": len(fragments),
                "edge_count": len(edges),
            },
            "claims": claims,
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

