"""
NLI (Natural Language Inference) for Lyra.
Determines stance relationships between claims.

When ml.use_remote=True, NLI inference is performed via HTTP calls
to the lyra-ml container on internal network.
"""

from typing import Any

from src.utils.config import get_settings
from src.utils.logging import get_logger

logger = get_logger(__name__)


class NLIModel:
    """NLI model for stance classification."""

    LABELS = ["supports", "refutes", "neutral"]

    def __init__(self) -> None:
        self._model: Any = None
        self._settings = get_settings()

    async def _ensure_model(self) -> None:
        """Load NLI model (GPU)."""
        if self._model is not None:
            return

        try:
            from transformers import pipeline

            model_name = self._settings.nli.model

            self._model = pipeline(
                "text-classification",
                model=model_name,
                device=0,
            )

            logger.info("NLI model loaded on GPU", model=model_name)

        except Exception as e:
            logger.error("Failed to load NLI model", error=str(e))
            raise

    def _map_label(self, label: str) -> str:
        """Map model label to standard format.

        Args:
            label: Raw model label.

        Returns:
            Standard label (supports/refutes/neutral).
        """
        label_lower = label.lower()

        if "entail" in label_lower or "support" in label_lower:
            return "supports"
        elif "contradict" in label_lower or "refute" in label_lower:
            return "refutes"
        else:
            return "neutral"

    async def predict(
        self,
        premise: str,
        hypothesis: str,
    ) -> dict[str, Any]:
        """Predict stance relationship.

        Args:
            premise: Premise text.
            hypothesis: Hypothesis text.

        Returns:
            Prediction result with label and confidence.
        """
        await self._ensure_model()

        input_text = f"{premise} [SEP] {hypothesis}"

        try:
            result = self._model(input_text)[0]

            label = self._map_label(result["label"])
            confidence = result["score"]

            return {
                "label": label,
                "confidence": confidence,
                "raw_label": result["label"],
            }

        except Exception as e:
            logger.error("NLI prediction error", error=str(e))
            return {
                "label": "neutral",
                "confidence": 0.0,
                "error": str(e),
            }

    async def predict_batch(
        self,
        pairs: list[tuple[str, str]],
    ) -> list[dict[str, Any]]:
        """Predict stance for multiple pairs.

        Args:
            pairs: List of (premise, hypothesis) tuples.

        Returns:
            List of prediction results.
        """
        await self._ensure_model()

        inputs = [f"{p} [SEP] {h}" for p, h in pairs]

        try:
            results = self._model(inputs)

            predictions = []
            for result in results:
                predictions.append(
                    {
                        "label": self._map_label(result["label"]),
                        "confidence": result["score"],
                        "raw_label": result["label"],
                    }
                )

            return predictions

        except Exception as e:
            logger.error("NLI batch prediction error", error=str(e))
            return [{"label": "neutral", "confidence": 0.0, "error": str(e)} for _ in pairs]


# Global model instance
_nli_model: NLIModel | None = None


def _get_model() -> NLIModel:
    """Get or create NLI model."""
    global _nli_model
    if _nli_model is None:
        _nli_model = NLIModel()
    return _nli_model


async def nli_judge(
    pairs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Judge stance relationships for claim pairs.

    Args:
        pairs: List of pair dicts with 'pair_id', 'premise', 'hypothesis'.

    Returns:
        List of result dicts with 'pair_id', 'stance', 'confidence'.
    """
    settings = get_settings()

    # Use remote ML server if configured
    if settings.ml.use_remote:
        return await _nli_judge_remote(pairs)

    return await _nli_judge_local(pairs)


async def _nli_judge_remote(
    pairs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Judge via ML server."""
    from src.ml_client import get_ml_client

    if not pairs:
        return []

    client = get_ml_client()

    results = await client.nli(pairs)

    # Map result format
    final_results = []
    for idx, result in enumerate(results):
        final_results.append(
            {
                "pair_id": result.get("pair_id", pairs[idx].get("pair_id", "unknown")),
                "stance": result.get("label", "neutral"),
                "confidence": result.get("confidence", 0.0),
            }
        )

    logger.info(
        "NLI judgment completed (remote)",
        pair_count=len(pairs),
    )

    return final_results


async def _nli_judge_local(
    pairs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Judge using local model."""
    model = _get_model()

    results = []

    for pair in pairs:
        pair_id = pair.get("pair_id", "unknown")
        premise = pair.get("premise", "")
        hypothesis = pair.get("hypothesis", "")

        prediction = await model.predict(premise, hypothesis)

        results.append(
            {
                "pair_id": pair_id,
                "stance": prediction["label"],
                "confidence": prediction["confidence"],
            }
        )

    logger.info(
        "NLI judgment completed (local)",
        pair_count=len(pairs),
    )

    return results


async def detect_contradictions(
    claims: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Detect contradictions among a set of claims.

    Args:
        claims: List of claim dicts with 'id' and 'text'.

    Returns:
        List of contradiction dicts.
    """
    model = _get_model()

    contradictions = []

    # Compare all pairs
    for i, claim1 in enumerate(claims):
        for claim2 in claims[i + 1 :]:
            pred = await model.predict(
                claim1["text"],
                claim2["text"],
            )

            if pred["label"] == "refutes" and pred["confidence"] > 0.7:
                contradictions.append(
                    {
                        "claim1_id": claim1["id"],
                        "claim2_id": claim2["id"],
                        "claim1_text": claim1["text"],
                        "claim2_text": claim2["text"],
                        "confidence": pred["confidence"],
                    }
                )

    logger.info(
        "Contradiction detection completed",
        claim_count=len(claims),
        contradiction_count=len(contradictions),
    )

    return contradictions
