"""
Lyra ML Server - FastAPI Application.
Provides embedding and NLI inference endpoints.
SECURITY: Runs on internal-only network (lyra-internal).
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, HTTPException

from src.ml_server.embedding import get_embedding_service
from src.ml_server.nli import get_nli_service
from src.ml_server.schemas import (
    EmbedRequest,
    EmbedResponse,
    HealthResponse,
    NLIRequest,
    NLIResponse,
    NLIResult,
)

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Application lifespan handler."""
    logger.info("ML Server starting up")
    # Models are loaded lazily on first request
    yield
    logger.info("ML Server shutting down")


app = FastAPI(
    title="Lyra ML Server",
    description="Internal ML inference server for embedding and NLI",
    version="1.0.0",
    lifespan=lifespan,
)


# =============================================================================
# Health Check
# =============================================================================


@app.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Health check endpoint."""
    embedding_service = get_embedding_service()
    nli_service = get_nli_service()

    return HealthResponse(
        status="ok",
        models_loaded={
            "embedding": embedding_service.is_loaded,
            "nli": nli_service.is_loaded,
        },
    )


# =============================================================================
# Embedding
# =============================================================================


@app.post("/embed", response_model=EmbedResponse)
async def embed(request: EmbedRequest) -> EmbedResponse:
    """Generate embeddings for texts.

    Args:
        request: EmbedRequest containing texts and optional batch_size.

    Returns:
        EmbedResponse with normalized embedding vectors (768-dim for BGE-base).
    """
    try:
        service = get_embedding_service()
        embeddings = await service.encode(request.texts, batch_size=request.batch_size)

        logger.info("Embedding completed", text_count=len(request.texts))

        return EmbedResponse(ok=True, embeddings=embeddings)

    except Exception as e:
        logger.error("Embedding error", error=str(e))
        return EmbedResponse(ok=False, embeddings=[], error=str(e))


# =============================================================================
# NLI (Natural Language Inference)
# =============================================================================


@app.post("/nli", response_model=NLIResponse)
async def nli(request: NLIRequest) -> NLIResponse:
    """Judge stance relationships for claim pairs.

    Args:
        request: NLIRequest containing premise-hypothesis pairs.

    Returns:
        NLIResponse with label (SUPPORTS/REFUTES/NEUTRAL) and confidence for each pair.
    """
    try:
        service = get_nli_service()

        results = []
        for pair in request.pairs:
            prediction = await service.predict(
                premise=pair.premise,
                nli_hypothesis=pair.nli_hypothesis,
            )

            results.append(
                NLIResult(
                    pair_id=pair.pair_id,
                    label=prediction["label"],
                    confidence=prediction["confidence"],
                    raw_label=prediction.get("raw_label"),
                )
            )

        logger.info(
            "NLI completed",
            pair_count=len(request.pairs),
        )

        return NLIResponse(ok=True, results=results)

    except Exception as e:
        logger.error("NLI error", error=str(e))
        return NLIResponse(ok=False, results=[], error=str(e))


# =============================================================================
# Warmup (optional - for preloading models)
# =============================================================================


@app.post("/warmup")
async def warmup() -> dict:
    """Warmup endpoint to preload all models."""
    try:
        embedding_service = get_embedding_service()
        nli_service = get_nli_service()

        await embedding_service.load()
        await nli_service.load()

        logger.info("All models warmed up")

        return {"ok": True, "message": "All models loaded"}

    except Exception as e:
        logger.error("Warmup error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e)) from e
