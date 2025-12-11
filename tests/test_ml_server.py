"""
Tests for ML Server components.
Tests model path management and service classes with mocks.
"""

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# =============================================================================
# model_paths.py Tests
# =============================================================================


class TestModelPaths:
    """Tests for model path management."""

    def setup_method(self):
        """Reset cached model paths before each test."""
        # Clear the cached model paths
        import src.ml_server.model_paths as mp

        mp._model_paths = None

    def test_get_model_paths_with_valid_json(self, tmp_path: Path):
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
            "reranker": "/app/models/huggingface/hub/models--BAAI--bge-reranker-v2-m3/snapshots/test",
            "reranker_name": "BAAI/bge-reranker-v2-m3",
            "nli_fast": "/app/models/huggingface/hub/models--cross-encoder--nli-deberta-v3-xsmall/snapshots/test",
            "nli_fast_name": "cross-encoder/nli-deberta-v3-xsmall",
            "nli_slow": "/app/models/huggingface/hub/models--cross-encoder--nli-deberta-v3-small/snapshots/test",
            "nli_slow_name": "cross-encoder/nli-deberta-v3-small",
        }
        json_file = tmp_path / "model_paths.json"
        json_file.write_text(json.dumps(model_paths_data))

        # When
        with patch.dict(os.environ, {"LANCET_ML__MODEL_PATHS_FILE": str(json_file)}):
            from src.ml_server.model_paths import get_model_paths

            result = get_model_paths()

        # Then
        assert result is not None
        assert result["embedding"] == "/app/models/huggingface/hub/models--BAAI--bge-m3/snapshots/test"
        assert result["reranker"] == "/app/models/huggingface/hub/models--BAAI--bge-reranker-v2-m3/snapshots/test"
        assert result["nli_fast"] == "/app/models/huggingface/hub/models--cross-encoder--nli-deberta-v3-xsmall/snapshots/test"
        assert result["nli_slow"] == "/app/models/huggingface/hub/models--cross-encoder--nli-deberta-v3-small/snapshots/test"

    def test_get_model_paths_file_not_found(self, tmp_path: Path):
        """
        Given: model_paths.json file does not exist
        When: get_model_paths() is called
        Then: Returns None
        """
        # Given
        non_existent_file = tmp_path / "non_existent.json"

        # When
        with patch.dict(
            os.environ, {"LANCET_ML__MODEL_PATHS_FILE": str(non_existent_file)}
        ):
            from src.ml_server.model_paths import get_model_paths

            result = get_model_paths()

        # Then
        assert result is None

    def test_get_model_paths_invalid_json(self, tmp_path: Path):
        """
        Given: model_paths.json contains invalid JSON
        When: get_model_paths() is called
        Then: Returns None (error handled gracefully)
        """
        # Given
        json_file = tmp_path / "model_paths.json"
        json_file.write_text("{ invalid json }")

        # When
        with patch.dict(os.environ, {"LANCET_ML__MODEL_PATHS_FILE": str(json_file)}):
            from src.ml_server.model_paths import get_model_paths

            result = get_model_paths()

        # Then
        assert result is None

    def test_get_embedding_path_with_local_paths(self, tmp_path: Path):
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
            "reranker": "/app/models/reranker/model",
            "reranker_name": "BAAI/bge-reranker-v2-m3",
            "nli_fast": "/app/models/nli_fast/model",
            "nli_fast_name": "cross-encoder/nli-deberta-v3-xsmall",
            "nli_slow": "/app/models/nli_slow/model",
            "nli_slow_name": "cross-encoder/nli-deberta-v3-small",
        }
        json_file = tmp_path / "model_paths.json"
        json_file.write_text(json.dumps(model_paths_data))

        # When
        with patch.dict(os.environ, {"LANCET_ML__MODEL_PATHS_FILE": str(json_file)}):
            from src.ml_server.model_paths import get_embedding_path

            result = get_embedding_path()

        # Then
        assert result == "/app/models/embedding/model"

    def test_get_embedding_path_fallback_to_env(self, tmp_path: Path):
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
                "LANCET_ML__MODEL_PATHS_FILE": str(non_existent),
                "LANCET_ML__EMBEDDING_MODEL": "custom/embedding-model",
            },
        ):
            from src.ml_server.model_paths import get_embedding_path

            result = get_embedding_path()

        # Then
        assert result == "custom/embedding-model"

    def test_get_reranker_path_with_local_paths(self, tmp_path: Path):
        """
        Given: model_paths.json exists with reranker path
        When: get_reranker_path() is called
        Then: Returns the local reranker path (validated)
        """
        # Given
        # Use a path within /app/models for validation
        # All required keys must be present for validation to succeed
        model_paths_data = {
            "embedding": "/app/models/embedding/model",
            "embedding_name": "BAAI/bge-m3",
            "reranker": "/app/models/reranker/model",
            "reranker_name": "BAAI/bge-reranker-v2-m3",
            "nli_fast": "/app/models/nli_fast/model",
            "nli_fast_name": "cross-encoder/nli-deberta-v3-xsmall",
            "nli_slow": "/app/models/nli_slow/model",
            "nli_slow_name": "cross-encoder/nli-deberta-v3-small",
        }
        json_file = tmp_path / "model_paths.json"
        json_file.write_text(json.dumps(model_paths_data))

        # When
        with patch.dict(os.environ, {"LANCET_ML__MODEL_PATHS_FILE": str(json_file)}):
            from src.ml_server.model_paths import get_reranker_path

            result = get_reranker_path()

        # Then
        assert result == "/app/models/reranker/model"

    def test_get_nli_fast_path_with_local_paths(self, tmp_path: Path):
        """
        Given: model_paths.json exists with NLI fast path
        When: get_nli_fast_path() is called
        Then: Returns the local NLI fast path (validated)
        """
        # Given
        # Use a path within /app/models for validation
        # All required keys must be present for validation to succeed
        model_paths_data = {
            "embedding": "/app/models/embedding/model",
            "embedding_name": "BAAI/bge-m3",
            "reranker": "/app/models/reranker/model",
            "reranker_name": "BAAI/bge-reranker-v2-m3",
            "nli_fast": "/app/models/nli_fast/model",
            "nli_fast_name": "cross-encoder/nli-deberta-v3-xsmall",
            "nli_slow": "/app/models/nli_slow/model",
            "nli_slow_name": "cross-encoder/nli-deberta-v3-small",
        }
        json_file = tmp_path / "model_paths.json"
        json_file.write_text(json.dumps(model_paths_data))

        # When
        with patch.dict(os.environ, {"LANCET_ML__MODEL_PATHS_FILE": str(json_file)}):
            from src.ml_server.model_paths import get_nli_fast_path

            result = get_nli_fast_path()

        # Then
        assert result == "/app/models/nli_fast/model"

    def test_get_nli_slow_path_with_local_paths(self, tmp_path: Path):
        """
        Given: model_paths.json exists with NLI slow path
        When: get_nli_slow_path() is called
        Then: Returns the local NLI slow path (validated)
        """
        # Given
        # Use a path within /app/models for validation
        # All required keys must be present for validation to succeed
        model_paths_data = {
            "embedding": "/app/models/embedding/model",
            "embedding_name": "BAAI/bge-m3",
            "reranker": "/app/models/reranker/model",
            "reranker_name": "BAAI/bge-reranker-v2-m3",
            "nli_fast": "/app/models/nli_fast/model",
            "nli_fast_name": "cross-encoder/nli-deberta-v3-xsmall",
            "nli_slow": "/app/models/nli_slow/model",
            "nli_slow_name": "cross-encoder/nli-deberta-v3-small",
        }
        json_file = tmp_path / "model_paths.json"
        json_file.write_text(json.dumps(model_paths_data))

        # When
        with patch.dict(os.environ, {"LANCET_ML__MODEL_PATHS_FILE": str(json_file)}):
            from src.ml_server.model_paths import get_nli_slow_path

            result = get_nli_slow_path()

        # Then
        assert result == "/app/models/nli_slow/model"

    def test_is_using_local_paths_true(self, tmp_path: Path):
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
            "reranker": "/app/models/huggingface/hub/models--BAAI--bge-reranker-v2-m3/snapshots/test",
            "reranker_name": "BAAI/bge-reranker-v2-m3",
            "nli_fast": "/app/models/huggingface/hub/models--cross-encoder--nli-deberta-v3-xsmall/snapshots/test",
            "nli_fast_name": "cross-encoder/nli-deberta-v3-xsmall",
            "nli_slow": "/app/models/huggingface/hub/models--cross-encoder--nli-deberta-v3-small/snapshots/test",
            "nli_slow_name": "cross-encoder/nli-deberta-v3-small",
        }
        json_file = tmp_path / "model_paths.json"
        json_file.write_text(json.dumps(model_paths_data))

        # When
        with patch.dict(os.environ, {"LANCET_ML__MODEL_PATHS_FILE": str(json_file)}):
            from src.ml_server.model_paths import is_using_local_paths

            result = is_using_local_paths()

        # Then
        assert result is True

    def test_is_using_local_paths_false(self, tmp_path: Path):
        """
        Given: model_paths.json does not exist
        When: is_using_local_paths() is called
        Then: Returns False
        """
        # Given
        non_existent = tmp_path / "non_existent.json"

        # When
        with patch.dict(os.environ, {"LANCET_ML__MODEL_PATHS_FILE": str(non_existent)}):
            from src.ml_server.model_paths import is_using_local_paths

            result = is_using_local_paths()

        # Then
        assert result is False

    def test_path_traversal_rejected(self, tmp_path: Path):
        """
        Given: model_paths.json contains path traversal (../)
        When: get_model_paths() is called
        Then: Returns None (path validation fails)
        """
        # Given
        model_paths_data = {
            "embedding": "/app/models/../../etc/passwd",
            "embedding_name": "BAAI/bge-m3",
            "reranker": "/app/models/reranker/model",
            "reranker_name": "BAAI/bge-reranker-v2-m3",
            "nli_fast": "/app/models/nli_fast/model",
            "nli_fast_name": "cross-encoder/nli-deberta-v3-xsmall",
            "nli_slow": "/app/models/nli_slow/model",
            "nli_slow_name": "cross-encoder/nli-deberta-v3-small",
        }
        json_file = tmp_path / "model_paths.json"
        json_file.write_text(json.dumps(model_paths_data))

        # When
        with patch.dict(os.environ, {"LANCET_ML__MODEL_PATHS_FILE": str(json_file)}):
            from src.ml_server.model_paths import get_model_paths

            result = get_model_paths()

        # Then
        assert result is None

    def test_path_outside_allowed_directory_rejected(self, tmp_path: Path):
        """
        Given: model_paths.json contains path outside /app/models
        When: get_model_paths() is called
        Then: Returns None (path validation fails)
        """
        # Given
        model_paths_data = {
            "embedding": "/etc/passwd",
            "embedding_name": "BAAI/bge-m3",
            "reranker": "/app/models/reranker/model",
            "reranker_name": "BAAI/bge-reranker-v2-m3",
            "nli_fast": "/app/models/nli_fast/model",
            "nli_fast_name": "cross-encoder/nli-deberta-v3-xsmall",
            "nli_slow": "/app/models/nli_slow/model",
            "nli_slow_name": "cross-encoder/nli-deberta-v3-small",
        }
        json_file = tmp_path / "model_paths.json"
        json_file.write_text(json.dumps(model_paths_data))

        # When
        with patch.dict(os.environ, {"LANCET_ML__MODEL_PATHS_FILE": str(json_file)}):
            from src.ml_server.model_paths import get_model_paths

            result = get_model_paths()

        # Then
        assert result is None


# =============================================================================
# embedding.py Tests
# =============================================================================


class TestEmbeddingService:
    """Tests for EmbeddingService."""

    def test_is_loaded_false_initially(self):
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
    async def test_encode_empty_list(self):
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
    async def test_encode_with_mock_model(self):
        """
        Given: EmbeddingService with mocked SentenceTransformer
        When: encode() is called with texts
        Then: Returns embedding vectors
        """
        # Given
        import numpy as np

        from src.ml_server.embedding import EmbeddingService

        mock_model = MagicMock()
        mock_embeddings = np.array([[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]])
        mock_model.encode.return_value = mock_embeddings

        service = EmbeddingService()

        # Mock to() to return self to workaround of GPU move
        mock_model.to = MagicMock(return_value=mock_model)

        with patch(
            "sentence_transformers.SentenceTransformer", return_value=mock_model
        ) as mock_st:
            with patch(
                "src.ml_server.embedding.get_embedding_path",
                return_value="/mock/path",
            ):
                with patch(
                    "src.ml_server.embedding.is_using_local_paths", return_value=True
                ):
                    # When
                    result = await service.encode(["text1", "text2"])

        # Then
        assert len(result) == 2
        assert result[0] == [0.1, 0.2, 0.3]
        assert result[1] == [0.4, 0.5, 0.6]
        # Verify model was created and encode was called
        mock_st.assert_called_once()
        mock_model.encode.assert_called_once()

    @pytest.mark.asyncio
    async def test_encode_model_load_failure(self):
        """
        Given: EmbeddingService with SentenceTransformer that raises exception
        When: encode() is called
        Then: Raises exception with error message
        """
        # Given
        from src.ml_server.embedding import EmbeddingService

        service = EmbeddingService()

        with patch(
            "sentence_transformers.SentenceTransformer",
            side_effect=RuntimeError("Model loading failed: file not found"),
        ):
            with patch(
                "src.ml_server.embedding.get_embedding_path",
                return_value="/nonexistent/path",
            ):
                with patch(
                    "src.ml_server.embedding.is_using_local_paths", return_value=True
                ):
                    # When/Then
                    with pytest.raises(RuntimeError) as exc_info:
                        await service.encode(["test text"])

                    assert "Model loading failed" in str(exc_info.value)


# =============================================================================
# reranker.py Tests
# =============================================================================


class TestRerankerService:
    """Tests for RerankerService."""

    def test_is_loaded_false_initially(self):
        """
        Given: A new RerankerService instance
        When: is_loaded is checked
        Then: Returns False
        """
        # Given/When
        from src.ml_server.reranker import RerankerService

        service = RerankerService()

        # Then
        assert service.is_loaded is False

    @pytest.mark.asyncio
    async def test_rerank_empty_documents(self):
        """
        Given: A RerankerService instance
        When: rerank() is called with empty documents
        Then: Returns an empty list without loading the model
        """
        # Given
        from src.ml_server.reranker import RerankerService

        service = RerankerService()

        # When
        result = await service.rerank(query="test query", documents=[])

        # Then
        assert result == []
        assert service.is_loaded is False

    @pytest.mark.asyncio
    async def test_rerank_with_mock_model(self):
        """
        Given: RerankerService with mocked CrossEncoder
        When: rerank() is called
        Then: Returns ranked results
        """
        # Given
        import numpy as np

        from src.ml_server.reranker import RerankerService

        mock_model = MagicMock()
        # Scores for 3 documents
        mock_model.predict.return_value = np.array([0.5, 0.9, 0.3])

        service = RerankerService()

        with patch("sentence_transformers.CrossEncoder", return_value=mock_model):
            with patch(
                "src.ml_server.reranker.get_reranker_path", return_value="/mock/path"
            ):
                with patch(
                    "src.ml_server.reranker.is_using_local_paths", return_value=True
                ):
                    # When
                    result = await service.rerank(
                        query="query", documents=["doc1", "doc2", "doc3"], top_k=2
                    )

        # Then
        assert len(result) == 2
        # Results should be sorted by score descending
        assert result[0][0] == 1  # doc2 has highest score
        assert result[0][1] == pytest.approx(0.9)
        assert result[1][0] == 0  # doc1 has second highest score
        assert result[1][1] == pytest.approx(0.5)

    @pytest.mark.asyncio
    async def test_rerank_model_load_failure(self):
        """
        Given: RerankerService with CrossEncoder that raises exception
        When: rerank() is called
        Then: Raises exception with error message
        """
        # Given
        from src.ml_server.reranker import RerankerService

        service = RerankerService()

        with patch(
            "sentence_transformers.CrossEncoder",
            side_effect=RuntimeError("Reranker model loading failed"),
        ):
            with patch(
                "src.ml_server.reranker.get_reranker_path",
                return_value="/nonexistent/path",
            ):
                with patch(
                    "src.ml_server.reranker.is_using_local_paths", return_value=True
                ):
                    # When/Then
                    with pytest.raises(RuntimeError) as exc_info:
                        await service.rerank(query="test", documents=["doc1"])

                    assert "Reranker model loading failed" in str(exc_info.value)


# =============================================================================
# nli.py Tests
# =============================================================================


class TestNLIService:
    """Tests for NLIService."""

    def test_is_loaded_false_initially(self):
        """
        Given: A new NLIService instance
        When: is_fast_loaded and is_slow_loaded are checked
        Then: Both return False
        """
        # Given/When
        from src.ml_server.nli import NLIService

        service = NLIService()

        # Then
        assert service.is_fast_loaded is False
        assert service.is_slow_loaded is False

    def test_map_label_entailment(self):
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

    def test_map_label_contradiction(self):
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

    def test_map_label_neutral(self):
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
    async def test_predict_with_mock_model(self):
        """
        Given: NLIService with mocked pipeline
        When: predict() is called
        Then: Returns prediction result
        """
        # Given
        from src.ml_server.nli import NLIService

        mock_pipeline = MagicMock()
        mock_pipeline.return_value = [{"label": "ENTAILMENT", "score": 0.95}]

        service = NLIService()

        with patch("transformers.pipeline", return_value=mock_pipeline):
            with patch(
                "src.ml_server.nli.get_nli_fast_path", return_value="/mock/path"
            ):
                with patch("src.ml_server.nli.is_using_local_paths", return_value=True):
                    # When
                    result = await service.predict(
                        premise="The sky is blue.",
                        hypothesis="The weather is clear.",
                        use_slow=False,
                    )

        # Then
        assert result["label"] == "supports"
        assert result["confidence"] == pytest.approx(0.95)
        assert result["raw_label"] == "ENTAILMENT"

    @pytest.mark.asyncio
    async def test_predict_batch_with_mock_model(self):
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

        service = NLIService()

        with patch("transformers.pipeline", return_value=mock_pipeline):
            with patch(
                "src.ml_server.nli.get_nli_fast_path", return_value="/mock/path"
            ):
                with patch("src.ml_server.nli.is_using_local_paths", return_value=True):
                    # When
                    pairs = [
                        ("premise1", "hypothesis1"),
                        ("premise2", "hypothesis2"),
                        ("premise3", "hypothesis3"),
                    ]
                    result = await service.predict_batch(pairs)

        # Then
        assert len(result) == 3
        assert result[0]["label"] == "supports"
        assert result[1]["label"] == "refutes"
        assert result[2]["label"] == "neutral"

    @pytest.mark.asyncio
    async def test_predict_use_slow_model(self):
        """
        Given: NLIService with mocked pipeline
        When: predict() is called with use_slow=True
        Then: Uses the slow model
        """
        # Given
        import torch

        from src.ml_server.nli import NLIService

        mock_pipeline = MagicMock()
        mock_pipeline.return_value = [{"label": "ENTAILMENT", "score": 0.98}]

        service = NLIService()

        with patch("transformers.pipeline", return_value=mock_pipeline) as mock_pl:
            with patch(
                "src.ml_server.nli.get_nli_slow_path", return_value="/mock/slow/path"
            ):
                with patch("src.ml_server.nli.is_using_local_paths", return_value=True):
                    with patch.object(torch.cuda, "is_available", return_value=False):
                        # When
                        result = await service.predict(
                            premise="Test premise",
                            hypothesis="Test hypothesis",
                            use_slow=True,
                        )

        # Then
        assert result["label"] == "supports"
        # Verify pipeline was called with slow model path
        call_kwargs = mock_pl.call_args[1]
        assert call_kwargs["model"] == "/mock/slow/path"

    @pytest.mark.asyncio
    async def test_predict_model_load_failure(self):
        """
        Given: NLIService with pipeline that raises exception
        When: predict() is called
        Then: Raises exception with error message
        """
        # Given
        from src.ml_server.nli import NLIService

        service = NLIService()

        with patch(
            "transformers.pipeline",
            side_effect=RuntimeError("NLI model loading failed"),
        ):
            with patch(
                "src.ml_server.nli.get_nli_fast_path", return_value="/nonexistent/path"
            ):
                with patch("src.ml_server.nli.is_using_local_paths", return_value=True):
                    # When/Then
                    with pytest.raises(RuntimeError) as exc_info:
                        await service.predict(
                            premise="Test premise",
                            hypothesis="Test hypothesis",
                            use_slow=False,
                        )

                    assert "NLI model loading failed" in str(exc_info.value)


# =============================================================================
# Integration Tests (with FastAPI TestClient)
# Note: These tests require FastAPI which is only available in ML container.
# For unit tests, we test the service classes directly with mocks.
# =============================================================================


@pytest.mark.skip(reason="FastAPI TestClient requires ML container environment")
class TestMLServerAPI:
    """Integration tests for ML Server API endpoints.
    
    These tests are skipped in main container as FastAPI is not installed.
    Run E2E tests in ML container instead.
    """

    @pytest.fixture
    def client(self):
        """Create test client."""
        from fastapi.testclient import TestClient

        from src.ml_server.main import app

        return TestClient(app)

    def test_health_check(self, client):
        """
        Given: ML Server is running
        When: GET /health is called
        Then: Returns status ok with models_loaded info
        """
        # When
        response = client.get("/health")

        # Then
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "models_loaded" in data

    def test_embed_endpoint_validation(self, client):
        """
        Given: ML Server is running
        When: POST /embed is called without texts
        Then: Returns validation error
        """
        # When
        response = client.post("/embed", json={})

        # Then
        assert response.status_code == 422  # Validation error

    def test_rerank_endpoint_validation(self, client):
        """
        Given: ML Server is running
        When: POST /rerank is called without required fields
        Then: Returns validation error
        """
        # When
        response = client.post("/rerank", json={})

        # Then
        assert response.status_code == 422  # Validation error

    def test_nli_endpoint_validation(self, client):
        """
        Given: ML Server is running
        When: POST /nli is called without required fields
        Then: Returns validation error
        """
        # When
        response = client.post("/nli", json={})

        # Then
        assert response.status_code == 422  # Validation error

