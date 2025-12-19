"""
NLI (Natural Language Inference) for Lancet.
Determines stance relationships between claims.

When ml.use_remote=True, NLI inference is performed via HTTP calls
to the lancet-ml container on internal network.
"""

from typing import Any

from src.utils.config import get_settings
from src.utils.logging import get_logger

logger = get_logger(__name__)


class NLIModel:
    """NLI model for stance classification."""

    LABELS = ["supports", "refutes", "neutral"]

    def __init__(self) -> None:
        self._fast_model = None
        self._slow_model = None
        self._settings = get_settings()

    async def _ensure_fast_model(self) -> None:
        """Load fast (CPU) NLI model."""
        if self._fast_model is not None:
            return

        try:
            from transformers import pipeline

            model_name = self._settings.nli.fast_model

            self._fast_model = pipeline(
                "text-classification",
                model=model_name,
                device=-1,  # CPU
            )

            logger.info("Fast NLI model loaded", model=model_name)

        except Exception as e:
            logger.error("Failed to load fast NLI model", error=str(e))
            raise

    async def _ensure_slow_model(self) -> None:
        """Load slow (GPU) NLI model."""
        if self._slow_model is not None:
            return

        try:
            import torch
            from transformers import pipeline

            model_name = self._settings.nli.slow_model

            device = 0 if torch.cuda.is_available() and self._settings.nli.use_gpu_for_slow else -1

            self._slow_model = pipeline(
                "text-classification",
                model=model_name,
                device=device,
            )

            device_name = "GPU" if device == 0 else "CPU"
            logger.info("Slow NLI model loaded", model=model_name, device=device_name)

        except Exception as e:
            logger.error("Failed to load slow NLI model", error=str(e))
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
        use_slow: bool = False,
    ) -> dict[str, Any]:
        """Predict stance relationship.

        Args:
            premise: Premise text.
            hypothesis: Hypothesis text.
            use_slow: Whether to use slow model.

        Returns:
            Prediction result with label and confidence.
        """
        if use_slow:
            await self._ensure_slow_model()
            model = self._slow_model
        else:
            await self._ensure_fast_model()
            model = self._fast_model

        # Format input for NLI
        input_text = f"{premise} [SEP] {hypothesis}"

        try:
            result = model(input_text)[0]

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
        use_slow: bool = False,
    ) -> list[dict[str, Any]]:
        """Predict stance for multiple pairs.

        Args:
            pairs: List of (premise, hypothesis) tuples.
            use_slow: Whether to use slow model.

        Returns:
            List of prediction results.
        """
        if use_slow:
            await self._ensure_slow_model()
            model = self._slow_model
        else:
            await self._ensure_fast_model()
            model = self._fast_model

        inputs = [f"{p} [SEP] {h}" for p, h in pairs]

        try:
            results = model(inputs)

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

    # First pass with fast model
    results = await client.nli(pairs, use_slow=False)

    # Check which pairs need slow model
    low_confidence_pairs = []
    low_confidence_indices = []

    for idx, (pair, result) in enumerate(zip(pairs, results, strict=False)):
        if result.get("confidence", 0) < 0.7:
            low_confidence_pairs.append(pair)
            low_confidence_indices.append(idx)

    # Second pass with slow model for low confidence pairs
    if low_confidence_pairs:
        slow_results = await client.nli(low_confidence_pairs, use_slow=True)
        for idx, result in zip(low_confidence_indices, slow_results, strict=False):
            result["used_slow_model"] = True
            results[idx] = result

    # Map result format
    final_results = []
    for idx, result in enumerate(results):
        final_results.append(
            {
                "pair_id": result.get("pair_id", pairs[idx].get("pair_id", "unknown")),
                "stance": result.get("label", "neutral"),
                "confidence": result.get("confidence", 0.0),
                "used_slow_model": result.get("used_slow_model", False),
            }
        )

    logger.info(
        "NLI judgment completed (remote)",
        pair_count=len(pairs),
        slow_model_used=sum(1 for r in final_results if r.get("used_slow_model")),
    )

    return final_results


async def _nli_judge_local(
    pairs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Judge using local model."""
    model = _get_model()

    results = []

    # First pass with fast model
    for pair in pairs:
        pair_id = pair.get("pair_id", "unknown")
        premise = pair.get("premise", "")
        hypothesis = pair.get("hypothesis", "")

        prediction = await model.predict(premise, hypothesis, use_slow=False)

        # Check if we need slow model (low confidence or ambiguous)
        need_slow = prediction["confidence"] < 0.7

        if need_slow:
            prediction = await model.predict(premise, hypothesis, use_slow=True)

        results.append(
            {
                "pair_id": pair_id,
                "stance": prediction["label"],
                "confidence": prediction["confidence"],
                "used_slow_model": need_slow,
            }
        )

    logger.info(
        "NLI judgment completed (local)",
        pair_count=len(pairs),
        slow_model_used=sum(1 for r in results if r.get("used_slow_model")),
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
            # Check both directions
            pred1 = await model.predict(
                claim1["text"],
                claim2["text"],
                use_slow=False,
            )

            if pred1["label"] == "refutes" and pred1["confidence"] > 0.7:
                # Verify with slow model
                pred_slow = await model.predict(
                    claim1["text"],
                    claim2["text"],
                    use_slow=True,
                )

                if pred_slow["label"] == "refutes" and pred_slow["confidence"] > 0.6:
                    contradictions.append(
                        {
                            "claim1_id": claim1["id"],
                            "claim2_id": claim2["id"],
                            "claim1_text": claim1["text"],
                            "claim2_text": claim2["text"],
                            "confidence": pred_slow["confidence"],
                        }
                    )

    logger.info(
        "Contradiction detection completed",
        claim_count=len(claims),
        contradiction_count=len(contradictions),
    )

    return contradictions

    return contradictions
