"""
NLI (Natural Language Inference) model service.
"""

import os

import structlog

from src.ml_server.model_paths import (
    get_nli_path,
    is_using_local_paths,
)

logger = structlog.get_logger(__name__)


class NLIService:
    """NLI model service for stance classification."""

    LABELS = ["supports", "refutes", "neutral"]

    def __init__(self) -> None:
        from typing import Any

        self._model: Any = None

    @property
    def is_loaded(self) -> bool:
        """Check if model is loaded."""
        return self._model is not None

    async def load(self) -> None:
        """Load NLI model (GPU)."""
        if self._model is not None:
            return

        try:
            from transformers import AutoModelForSequenceClassification, AutoTokenizer, pipeline

            model_path = get_nli_path()
            use_local = is_using_local_paths()

            logger.info(
                "Loading NLI model",
                model_path=model_path,
                use_local=use_local,
            )

            local_only = use_local or os.environ.get("HF_HUB_OFFLINE", "0") == "1"

            # Load tokenizer and model separately to avoid local_files_only
            # being passed to tokenizer's _batch_encode_plus() during inference
            tokenizer = AutoTokenizer.from_pretrained(
                model_path,
                local_files_only=local_only,
            )
            model = AutoModelForSequenceClassification.from_pretrained(
                model_path,
                local_files_only=local_only,
            )

            self._model = pipeline(
                "text-classification",
                model=model,
                tokenizer=tokenizer,
                device=0,
            )

            logger.info(
                "NLI model loaded on GPU",
                model_path=model_path,
            )

        except Exception as e:
            logger.error("Failed to load NLI model", error=str(e))
            raise

    def _map_label(self, label: str) -> str:
        """Map model label to standard format."""
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
    ) -> dict:
        """Predict stance relationship.

        Args:
            premise: Premise text.
            hypothesis: Hypothesis text.

        Returns:
            Prediction result with label and confidence.
        """
        await self.load()

        input_text = f"{premise} [SEP] {hypothesis}"

        try:
            result = self._model(input_text)[0]

            return {
                "label": self._map_label(result["label"]),
                "confidence": result["score"],
                "raw_label": result["label"],
            }

        except Exception as e:
            logger.error("NLI prediction error", error=str(e))
            return {
                "label": "neutral",
                "confidence": 0.0,
                "raw_label": None,
                "error": str(e),
            }

    async def predict_batch(
        self,
        pairs: list[tuple[str, str]],
    ) -> list[dict]:
        """Predict stance for multiple pairs.

        Args:
            pairs: List of (premise, hypothesis) tuples.

        Returns:
            List of prediction results.
        """
        await self.load()

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
            return [
                {"label": "neutral", "confidence": 0.0, "raw_label": None, "error": str(e)}
                for _ in pairs
            ]


# Global singleton
_nli_service: NLIService | None = None


def get_nli_service() -> NLIService:
    """Get or create NLI service singleton."""
    global _nli_service
    if _nli_service is None:
        _nli_service = NLIService()
    return _nli_service
