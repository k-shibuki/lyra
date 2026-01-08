"""
Tests for ML Server components.

=============================================================================
ML Testing Strategy
=============================================================================

This project uses a hybrid architecture where ML inference runs in an isolated
container (lyra-ml) for security. Tests are split into two categories:

1. UNIT TESTS (this file - test_ml_server.py)
   - Test model path management, service classes, label mapping, etc.
   - Uses mocks to test service behavior without actual ML libraries

2. E2E TESTS (test_ml_server_e2e.py) - RECOMMENDED
   - Test actual HTTP communication with the ML server container
   - Run from WSL environment, communicate via proxy (localhost:8080)
   - This is the PRIMARY way to validate ML server functionality

How to run:
    # E2E tests (recommended - validates actual ML server behavior)
    pytest tests/test_ml_server_e2e.py -v -m e2e

    # Unit tests
    pytest tests/test_ml_server.py -v

=============================================================================
"""

import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# =============================================================================
# model_paths.py Tests
# =============================================================================


class TestModelPaths:
    """Tests for model path management."""

    def setup_method(self) -> None:
        """Reset cached model paths before each test."""
        # Clear the cached model paths
        import src.ml_server.model_paths as mp

        mp._model_paths = None

    def test_get_model_paths_with_valid_json(self, tmp_path: Path) -> None:
        """
        Given: A valid model_paths.json file exists
        When: get_model_paths() is called
        Then: Returns the parsed model paths dictionary
        """
        # Given
        # Use paths within /app/models for validation
        model_paths_data = {
            "embedding": "/app/models/huggingface/hub/models--BAAI--bge-m3/snapshots/test",
            "embedding_name": "BAAI/bge-m3",
            "nli": "/app/models/huggingface/hub/models--cross-encoder--nli-deberta-v3-small/snapshots/test",
            "nli_name": "cross-encoder/nli-deberta-v3-small",
        }
        json_file = tmp_path / "model_paths.json"
        json_file.write_text(json.dumps(model_paths_data))

        # When
        with patch.dict(os.environ, {"LYRA_ML__MODEL_PATHS_FILE": str(json_file)}):
            from src.ml_server.model_paths import get_model_paths

            result = get_model_paths()

        # Then
        assert result is not None
        assert (
            result["embedding"] == "/app/models/huggingface/hub/models--BAAI--bge-m3/snapshots/test"
        )
        assert (
            result["nli"]
            == "/app/models/huggingface/hub/models--cross-encoder--nli-deberta-v3-small/snapshots/test"
        )

    def test_get_model_paths_file_not_found(self, tmp_path: Path) -> None:
        """
        Given: model_paths.json file does not exist
        When: get_model_paths() is called
        Then: Returns None
        """
        # Given
        non_existent_file = tmp_path / "non_existent.json"

        # When
        with patch.dict(os.environ, {"LYRA_ML__MODEL_PATHS_FILE": str(non_existent_file)}):
            from src.ml_server.model_paths import get_model_paths

            result = get_model_paths()

        # Then
        assert result is None

    def test_get_model_paths_invalid_json(self, tmp_path: Path) -> None:
        """
        Given: model_paths.json contains invalid JSON
        When: get_model_paths() is called
        Then: Returns None (error handled gracefully)
        """
        # Given
        json_file = tmp_path / "model_paths.json"
        json_file.write_text("{ invalid json }")

        # When
        with patch.dict(os.environ, {"LYRA_ML__MODEL_PATHS_FILE": str(json_file)}):
            from src.ml_server.model_paths import get_model_paths

            result = get_model_paths()

        # Then
        assert result is None

    def test_get_embedding_path_with_local_paths(self, tmp_path: Path) -> None:
        """
        Given: model_paths.json exists with embedding path
        When: get_embedding_path() is called
        Then: Returns the local embedding path (validated)
        """
        # Given
        # Use a path within /app/models for validation
        # All required keys must be present for validation to succeed
        model_paths_data = {
            "embedding": "/app/models/embedding/model",
            "embedding_name": "BAAI/bge-m3",
            "nli": "/app/models/nli/model",
            "nli_name": "cross-encoder/nli-deberta-v3-small",
        }
        json_file = tmp_path / "model_paths.json"
        json_file.write_text(json.dumps(model_paths_data))

        # When
        with patch.dict(os.environ, {"LYRA_ML__MODEL_PATHS_FILE": str(json_file)}):
            from src.ml_server.model_paths import get_embedding_path

            result = get_embedding_path()

        # Then
        assert result == "/app/models/embedding/model"

    def test_get_embedding_path_fallback_to_env(self, tmp_path: Path) -> None:
        """
        Given: model_paths.json does not exist
        When: get_embedding_path() is called
        Then: Returns model name from environment variable
        """
        # Given
        non_existent = tmp_path / "non_existent.json"

        # When
        with patch.dict(
            os.environ,
            {
                "LYRA_ML__MODEL_PATHS_FILE": str(non_existent),
                "LYRA_ML__EMBEDDING_MODEL": "custom/embedding-model",
            },
        ):
            from src.ml_server.model_paths import get_embedding_path

            result = get_embedding_path()

        # Then
        assert result == "custom/embedding-model"

    def test_get_nli_path_with_local_paths(self, tmp_path: Path) -> None:
        """
        Given: model_paths.json exists with NLI path
        When: get_nli_path() is called
        Then: Returns the local NLI path (validated)
        """
        # Given
        # Use a path within /app/models for validation
        # All required keys must be present for validation to succeed
        model_paths_data = {
            "embedding": "/app/models/embedding/model",
            "embedding_name": "BAAI/bge-m3",
            "nli": "/app/models/nli/model",
            "nli_name": "cross-encoder/nli-deberta-v3-small",
        }
        json_file = tmp_path / "model_paths.json"
        json_file.write_text(json.dumps(model_paths_data))

        # When
        with patch.dict(os.environ, {"LYRA_ML__MODEL_PATHS_FILE": str(json_file)}):
            from src.ml_server.model_paths import get_nli_path

            result = get_nli_path()

        # Then
        assert result == "/app/models/nli/model"

    def test_is_using_local_paths_true(self, tmp_path: Path) -> None:
        """
        Given: model_paths.json exists with valid paths
        When: is_using_local_paths() is called
        Then: Returns True
        """
        # Given
        # Use paths within /app/models for validation
        model_paths_data = {
            "embedding": "/app/models/huggingface/hub/models--BAAI--bge-m3/snapshots/test",
            "embedding_name": "BAAI/bge-m3",
            "nli": "/app/models/huggingface/hub/models--cross-encoder--nli-deberta-v3-small/snapshots/test",
            "nli_name": "cross-encoder/nli-deberta-v3-small",
        }
        json_file = tmp_path / "model_paths.json"
        json_file.write_text(json.dumps(model_paths_data))

        # When
        with patch.dict(os.environ, {"LYRA_ML__MODEL_PATHS_FILE": str(json_file)}):
            from src.ml_server.model_paths import is_using_local_paths

            result = is_using_local_paths()

        # Then
        assert result is True

    def test_is_using_local_paths_false(self, tmp_path: Path) -> None:
        """
        Given: model_paths.json does not exist
        When: is_using_local_paths() is called
        Then: Returns False
        """
        # Given
        non_existent = tmp_path / "non_existent.json"

        # When
        with patch.dict(os.environ, {"LYRA_ML__MODEL_PATHS_FILE": str(non_existent)}):
            from src.ml_server.model_paths import is_using_local_paths

            result = is_using_local_paths()

        # Then
        assert result is False

    def test_path_traversal_rejected(self, tmp_path: Path) -> None:
        """
        Given: model_paths.json contains path traversal (../)
        When: get_model_paths() is called
        Then: Returns None (path validation fails)
        """
        # Given
        model_paths_data = {
            "embedding": "/app/models/../../etc/passwd",
            "embedding_name": "BAAI/bge-m3",
            "nli": "/app/models/nli/model",
            "nli_name": "cross-encoder/nli-deberta-v3-small",
        }
        json_file = tmp_path / "model_paths.json"
        json_file.write_text(json.dumps(model_paths_data))

        # When
        with patch.dict(os.environ, {"LYRA_ML__MODEL_PATHS_FILE": str(json_file)}):
            from src.ml_server.model_paths import get_model_paths

            result = get_model_paths()

        # Then
        assert result is None

    def test_path_outside_allowed_directory_rejected(self, tmp_path: Path) -> None:
        """
        Given: model_paths.json contains path outside /app/models
        When: get_model_paths() is called
        Then: Returns None (path validation fails)
        """
        # Given
        model_paths_data = {
            "embedding": "/etc/passwd",
            "embedding_name": "BAAI/bge-m3",
            "nli": "/app/models/nli/model",
            "nli_name": "cross-encoder/nli-deberta-v3-small",
        }
        json_file = tmp_path / "model_paths.json"
        json_file.write_text(json.dumps(model_paths_data))

        # When
        with patch.dict(os.environ, {"LYRA_ML__MODEL_PATHS_FILE": str(json_file)}):
            from src.ml_server.model_paths import get_model_paths

            result = get_model_paths()

        # Then
        assert result is None


# =============================================================================
# embedding.py Tests
# =============================================================================


class TestEmbeddingService:
    """Tests for EmbeddingService."""

    def test_is_loaded_false_initially(self) -> None:
        """
        Given: A new EmbeddingService instance
        When: is_loaded is checked
        Then: Returns False
        """
        # Given/When
        from src.ml_server.embedding import EmbeddingService

        service = EmbeddingService()

        # Then
        assert service.is_loaded is False

    @pytest.mark.asyncio
    async def test_encode_empty_list(self) -> None:
        """
        Given: An EmbeddingService instance
        When: encode() is called with an empty list
        Then: Returns an empty list without loading the model
        """
        # Given
        from src.ml_server.embedding import EmbeddingService

        service = EmbeddingService()

        # When
        result = await service.encode([])

        # Then
        assert result == []
        assert service.is_loaded is False

    @pytest.mark.asyncio
    async def test_encode_with_mock_model(self) -> None:
        """
        Given: EmbeddingService with mocked model (load bypassed)
        When: encode() is called with texts
        Then: Returns embedding vectors
        """
        # Given
        from src.ml_server.embedding import EmbeddingService

        mock_model = MagicMock()
        # Return mock objects with tolist() method (mimicking numpy arrays)
        mock_emb1 = MagicMock()
        mock_emb1.tolist.return_value = [0.1, 0.2, 0.3]
        mock_emb2 = MagicMock()
        mock_emb2.tolist.return_value = [0.4, 0.5, 0.6]
        mock_model.encode.return_value = [mock_emb1, mock_emb2]

        # Bypass load() and inject mock model directly
        with patch.object(EmbeddingService, "load", new_callable=AsyncMock):
            service = EmbeddingService()
            service._model = mock_model

            # When
            result = await service.encode(["text1", "text2"])

        # Then
        assert len(result) == 2
        assert result[0] == [0.1, 0.2, 0.3]
        assert result[1] == [0.4, 0.5, 0.6]
        mock_model.encode.assert_called_once()

    @pytest.mark.asyncio
    async def test_encode_model_load_failure(self) -> None:
        """
        Given: EmbeddingService with load() that raises exception
        When: encode() is called
        Then: Raises exception with error message
        """
        # Given
        from src.ml_server.embedding import EmbeddingService

        service = EmbeddingService()

        # Patch load() to simulate model loading failure
        with patch.object(
            EmbeddingService,
            "load",
            new_callable=AsyncMock,
            side_effect=RuntimeError("Model loading failed: file not found"),
        ):
            # When/Then
            with pytest.raises(RuntimeError) as exc_info:
                await service.encode(["test text"])

            assert "Model loading failed" in str(exc_info.value)


# =============================================================================
# nli.py Tests
# =============================================================================


class TestNLIService:
    """Tests for NLIService."""

    def test_is_loaded_false_initially(self) -> None:
        """
        Given: A new NLIService instance
        When: is_loaded is checked
        Then: Returns False
        """
        # Given/When
        from src.ml_server.nli import NLIService

        service = NLIService()

        # Then
        assert service.is_loaded is False

    def test_map_label_entailment(self) -> None:
        """
        Given: NLIService instance
        When: _map_label() is called with entailment labels
        Then: Returns 'supports'
        """
        # Given
        from src.ml_server.nli import NLIService

        service = NLIService()

        # When/Then
        assert service._map_label("ENTAILMENT") == "supports"
        assert service._map_label("entailment") == "supports"
        assert service._map_label("support") == "supports"

    def test_map_label_contradiction(self) -> None:
        """
        Given: NLIService instance
        When: _map_label() is called with contradiction labels
        Then: Returns 'refutes'
        """
        # Given
        from src.ml_server.nli import NLIService

        service = NLIService()

        # When/Then
        assert service._map_label("CONTRADICTION") == "refutes"
        assert service._map_label("contradiction") == "refutes"
        assert service._map_label("refute") == "refutes"

    def test_map_label_neutral(self) -> None:
        """
        Given: NLIService instance
        When: _map_label() is called with neutral labels
        Then: Returns 'neutral'
        """
        # Given
        from src.ml_server.nli import NLIService

        service = NLIService()

        # When/Then
        assert service._map_label("NEUTRAL") == "neutral"
        assert service._map_label("neutral") == "neutral"
        assert service._map_label("unknown") == "neutral"

    @pytest.mark.asyncio
    async def test_predict_with_mock_model(self) -> None:
        """
        Given: NLIService with mocked pipeline
        When: predict() is called
        Then: Returns prediction result
        """
        # Given
        from src.ml_server.nli import NLIService

        mock_pipeline = MagicMock()
        mock_pipeline.return_value = [{"label": "ENTAILMENT", "score": 0.95}]

        # Patch at load() level to avoid AutoTokenizer validation
        with (patch.object(NLIService, "load", new_callable=AsyncMock) as mock_load,):
            service = NLIService()
            service._model = mock_pipeline

            # When
            result = await service.predict(
                premise="The sky is blue.",
                nli_hypothesis="The weather is clear.",
            )

            # Then: load() was called
            mock_load.assert_called_once()

        # Then
        assert result["label"] == "supports"
        assert result["confidence"] == pytest.approx(0.95)
        assert result["raw_label"] == "ENTAILMENT"

    @pytest.mark.asyncio
    async def test_predict_batch_with_mock_model(self) -> None:
        """
        Given: NLIService with mocked pipeline
        When: predict_batch() is called with multiple pairs
        Then: Returns multiple prediction results
        """
        # Given
        from src.ml_server.nli import NLIService

        mock_pipeline = MagicMock()
        mock_pipeline.return_value = [
            {"label": "ENTAILMENT", "score": 0.9},
            {"label": "CONTRADICTION", "score": 0.85},
            {"label": "NEUTRAL", "score": 0.7},
        ]

        # Patch at load() level to avoid AutoTokenizer validation
        with (patch.object(NLIService, "load", new_callable=AsyncMock) as mock_load,):
            service = NLIService()
            service._model = mock_pipeline

            # When
            pairs = [
                ("premise1", "hypothesis1"),
                ("premise2", "hypothesis2"),
                ("premise3", "hypothesis3"),
            ]
            result = await service.predict_batch(pairs)

            # Then: load() was called
            mock_load.assert_called_once()

        # Then
        assert len(result) == 3
        assert result[0]["label"] == "supports"
        assert result[1]["label"] == "refutes"
        assert result[2]["label"] == "neutral"

    @pytest.mark.asyncio
    async def test_predict_model_load_failure(self) -> None:
        """
        Given: NLIService with pipeline that raises exception
        When: predict() is called
        Then: Raises exception with error message
        """
        # Given
        from src.ml_server.nli import NLIService

        service = NLIService()

        # Patch load() to simulate model loading failure
        with patch.object(
            NLIService,
            "load",
            new_callable=AsyncMock,
            side_effect=RuntimeError("NLI model loading failed"),
        ):
            # When/Then
            with pytest.raises(RuntimeError) as exc_info:
                await service.predict(
                    premise="Test premise",
                    nli_hypothesis="Test hypothesis",
                )

            assert "NLI model loading failed" in str(exc_info.value)


# =============================================================================
# Integration Tests (FastAPI TestClient) - Covered by E2E
# =============================================================================
# FastAPI endpoint tests are now covered by test_ml_server_e2e.py which tests
# the actual HTTP API. This provides better production-like validation.
# See: test_ml_server_e2e.py::TestMLServerE2E
