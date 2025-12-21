"""
Citation relevance filtering (Phase 3).

Design:
- Use a source-agnostic impact_score derived from Paper.citation_count (local normalization).
- Stage 1: Embedding similarity + impact_score (fast coarse filter).
- Stage 2: LLM "evidence usefulness" score + Stage 1 signals (precise selection).

Important:
- We do NOT ask the LLM to judge SUPPORTS/REFUTES here (Decision 8).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from src.filter.ollama_provider import create_ollama_provider
from src.filter.provider import LLMOptions
from src.ml_client import get_ml_client
from src.utils.config import get_settings
from src.utils.logging import get_logger
from src.utils.prompt_manager import render_prompt
from src.utils.schemas import Paper

logger = get_logger(__name__)


@dataclass(frozen=True)
class CitationCandidateScore:
    paper: Paper
    final_score: float
    llm_score: float | None
    embedding_similarity: float
    impact_score: float


_INT_RE = re.compile(r"(-?\d+)")


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b, strict=False):
        dot += x * y
        na += x * x
        nb += y * y
    denom = math.sqrt(na) * math.sqrt(nb)
    if denom <= 0.0:
        return 0.0
    return max(0.0, min(1.0, dot / denom))


def _local_impact_scores(papers: list[Paper]) -> dict[str, float]:
    """
    Compute a 0..1 impact_score per paper using local normalization.

    We use log1p(citation_count) to reduce skew, then percentile-rank within the
    candidate set. This keeps the score source-agnostic (S2/OpenAlex both map
    into Paper.citation_count) and avoids field-level normalization complexity.
    """
    if not papers:
        return {}

    values = []
    for p in papers:
        cc = p.citation_count if getattr(p, "citation_count", None) is not None else 0
        values.append(math.log1p(max(0, int(cc))))

    if len(values) == 1:
        return {papers[0].id: 0.5}

    sorted_vals = sorted(values)

    def percentile(v: float) -> float:
        # average rank for ties
        lo = 0
        hi = len(sorted_vals)
        # leftmost
        while lo < hi:
            mid = (lo + hi) // 2
            if sorted_vals[mid] < v:
                lo = mid + 1
            else:
                hi = mid
        left = lo
        lo = 0
        hi = len(sorted_vals)
        # rightmost
        while lo < hi:
            mid = (lo + hi) // 2
            if sorted_vals[mid] <= v:
                lo = mid + 1
            else:
                hi = mid
        right = lo
        # average rank in [0, n-1]
        avg_rank = (left + right - 1) / 2.0
        return avg_rank / (len(sorted_vals) - 1)

    scores: dict[str, float] = {}
    for p, v in zip(papers, values, strict=False):
        scores[p.id] = float(max(0.0, min(1.0, percentile(v))))
    return scores


def _parse_llm_score_0_10(text: str) -> int | None:
    if not text:
        return None
    m = _INT_RE.search(text.strip())
    if not m:
        return None
    try:
        n = int(m.group(1))
        return max(0, min(10, n))
    except Exception:
        return None


async def filter_relevant_citations(
    *,
    query: str,
    source_paper: Paper,
    candidate_papers: list[Paper],
) -> list[CitationCandidateScore]:
    """
    Filter citations by relevance/usefulness.

    Returns:
        Sorted list (desc) of CitationCandidateScore for top stage2_top_k papers.
    """
    settings = get_settings()
    cfg = settings.search.citation_filter

    if not source_paper.abstract:
        return []

    # Only candidates with abstracts are usable for embedding/LLM.
    candidates = [p for p in candidate_papers if p.abstract]
    if not candidates:
        return []

    # -------------------------
    # Stage 1: embedding + impact_score (fast)
    # -------------------------
    ml = get_ml_client()
    batch_size = settings.embedding.batch_size

    src_abs = source_paper.abstract[: cfg.max_source_abstract_chars]
    cand_abs = [p.abstract[: cfg.max_target_abstract_chars] for p in candidates if p.abstract]

    embeddings = await ml.embed([src_abs, *cand_abs], batch_size=batch_size)
    if len(embeddings) != 1 + len(cand_abs):
        logger.warning("Embedding count mismatch", expected=1 + len(cand_abs), got=len(embeddings))
        return []

    src_emb = embeddings[0]
    cand_embs = embeddings[1:]
    embed_sims = [_cosine_similarity(src_emb, e) for e in cand_embs]

    impact_scores = _local_impact_scores(candidates)

    stage1 = []
    for p, sim in zip(candidates, embed_sims, strict=False):
        impact = impact_scores.get(p.id, 0.0)
        score = cfg.stage1_weight_embedding * sim + cfg.stage1_weight_impact * impact
        stage1.append((p, float(score), sim, impact))

    stage1.sort(key=lambda x: x[1], reverse=True)
    stage1 = stage1[: cfg.stage1_top_k]

    # -------------------------
    # Stage 2: LLM evidence usefulness (precise)
    # -------------------------
    provider = create_ollama_provider()
    results: list[CitationCandidateScore] = []
    try:
        for p, _s1, sim, impact in stage1:
            prompt = render_prompt(
                "relevance_evaluation",
                query=query,
                source_abstract=src_abs,
                target_abstract=p.abstract[: cfg.max_target_abstract_chars] if p.abstract else "",
            )

            options = LLMOptions(
                max_tokens=cfg.llm_max_tokens,
                timeout=cfg.llm_timeout_seconds,
            )

            resp = await provider.generate(prompt, options)
            llm_score_raw = _parse_llm_score_0_10(resp.text if resp.ok else "")
            llm_score = (llm_score_raw / 10.0) if llm_score_raw is not None else 0.5

            final = (
                cfg.stage2_weight_llm * llm_score
                + cfg.stage2_weight_embedding * sim
                + cfg.stage2_weight_impact * impact
            )

            results.append(
                CitationCandidateScore(
                    paper=p,
                    final_score=float(final),
                    llm_score=float(llm_score),
                    embedding_similarity=float(sim),
                    impact_score=float(impact),
                )
            )
    finally:
        await provider.close()

    results.sort(key=lambda x: x.final_score, reverse=True)
    return results[: cfg.stage2_top_k]
