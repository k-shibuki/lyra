"""
NLI (Natural Language Inference) model service.
"""

import os

import structlog

from src.ml_server.model_paths import (
    get_nli_fast_path,
    get_nli_slow_path,
    is_using_local_paths,
)

logger = structlog.get_logger(__name__)


class NLIService:
    """NLI model service for stance classification."""

    LABELS = ["supports", "refutes", "neutral"]

    def __init__(self):
        self._fast_model = None
        self._slow_model = None
        self._use_gpu = os.environ.get("LANCET_ML__USE_GPU", "true").lower() == "true"

    @property
    def is_fast_loaded(self) -> bool:
        """Check if fast model is loaded."""
        return self._fast_model is not None

    @property
    def is_slow_loaded(self) -> bool:
        """Check if slow model is loaded."""
        return self._slow_model is not None

    async def load_fast(self) -> None:
        """Load fast (CPU) NLI model."""
        if self._fast_model is not None:
            return

        try:
            from transformers import pipeline
            from transformers.utils import logging as hf_logging

            # Suppress HuggingFace warnings in offline mode
            hf_logging.set_verbosity_error()

            model_path = get_nli_fast_path()
            use_local = is_using_local_paths()

            logger.info(
                "Loading fast NLI model",
                model_path=model_path,
                use_local=use_local,
            )

            # When using local paths, always use local_files_only=True
            local_only = use_local or os.environ.get("HF_HUB_OFFLINE", "0") == "1"

            self._fast_model = pipeline(
                "text-classification",
                model=model_path,
                device=-1,  # CPU
                local_files_only=local_only,
            )
            logger.info("Fast NLI model loaded", model_path=model_path)

        except Exception as e:
            logger.error("Failed to load fast NLI model", error=str(e))
            raise

    async def load_slow(self) -> None:
        """Load slow (GPU) NLI model."""
        if self._slow_model is not None:
            return

        try:
            import torch
            from transformers import pipeline

            model_path = get_nli_slow_path()
            use_local = is_using_local_paths()
            device = 0 if torch.cuda.is_available() and self._use_gpu else -1

            logger.info(
                "Loading slow NLI model",
                model_path=model_path,
                use_local=use_local,
                device="GPU" if device == 0 else "CPU",
            )

            # When using local paths, always use local_files_only=True
            local_only = use_local or os.environ.get("HF_HUB_OFFLINE", "0") == "1"

            self._slow_model = pipeline(
                "text-classification",
                model=model_path,
                device=device,
                local_files_only=local_only,
            )

            device_name = "GPU" if device == 0 else "CPU"
            logger.info(
                "Slow NLI model loaded",
                model_path=model_path,
                device=device_name,
            )

        except Exception as e:
            logger.error("Failed to load slow NLI model", error=str(e))
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
        use_slow: bool = False,
    ) -> dict:
        """Predict stance relationship.

        Args:
            premise: Premise text.
            hypothesis: Hypothesis text.
            use_slow: Whether to use slow model.

        Returns:
            Prediction result with label and confidence.
        """
        if use_slow:
            await self.load_slow()
            model = self._slow_model
        else:
            await self.load_fast()
            model = self._fast_model

        # Format input for NLI
        input_text = f"{premise} [SEP] {hypothesis}"

        try:
            result = model(input_text)[0]

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
        use_slow: bool = False,
    ) -> list[dict]:
        """Predict stance for multiple pairs.

        Args:
            pairs: List of (premise, hypothesis) tuples.
            use_slow: Whether to use slow model.

        Returns:
            List of prediction results.
        """
        if use_slow:
            await self.load_slow()
            model = self._slow_model
        else:
            await self.load_fast()
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
