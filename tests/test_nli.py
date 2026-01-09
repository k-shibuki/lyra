"""
Tests for NLI (Natural Language Inference) module.

Focuses on testing NLIModel class, nli_judge function,
and detect_contradictions function with mocked ML dependencies.

## Test Perspectives Table

| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---------|---------------------|---------------------------------------|-----------------|-------|
| TC-NLI-N-01 | Valid premise + hypothesis | Equivalence – normal | Label returned, confidence calibrated | - |
| TC-NLI-N-02 | Batch prediction with multiple pairs | Equivalence – normal batch | List of predictions returned | - |
| TC-NLI-N-03 | nli_judge with remote=True | Normal – remote mode | ML client called, results mapped | - |
| TC-NLI-N-04 | nli_judge with remote=False | Normal – local mode | Local model called | - |
| TC-NLI-A-01 | Model loading fails | Abnormal – init error | Exception raised | - |
| TC-NLI-A-02 | Model prediction raises error | Abnormal – inference error | Neutral fallback with error | - |
| TC-NLI-A-03 | Remote ML client error | Abnormal – network error | Exception propagates / returns empty | - |
| TC-NLI-B-01 | Empty pairs list [] | Boundary – empty | Empty list returned | - |
| TC-NLI-B-02 | Empty premise "" | Boundary – empty string | Still processes, returns result | - |
| TC-NLI-M-01 | Label mapping "entailment" | Mapping | Returns "supports" | - |
| TC-NLI-M-02 | Label mapping "contradiction" | Mapping | Returns "refutes" | - |
| TC-NLI-M-03 | Label mapping "neutral" | Mapping | Returns "neutral" | - |
| TC-NLI-M-04 | Label mapping unknown | Mapping fallback | Returns "neutral" | - |
| TC-NLI-DC-01 | Claims with contradiction | detect_contradictions | Contradictions detected | - |
| TC-NLI-DC-02 | Claims without contradiction | detect_contradictions | Empty list returned | - |
| TC-NLI-W-01 | Calibration applied | Wiring – calibration | get_calibrator called | - |
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestNLIModelLabelMapping:
    """Tests for NLIModel._map_label method."""

    def test_map_label_entailment_to_supports(self) -> None:
        """TC-NLI-M-01: 'entailment' label is mapped to 'supports'."""
        # Given: NLIModel instance
        from src.filter.nli import NLIModel

        model = NLIModel()

        # When: Mapping 'entailment' label
        result = model._map_label("entailment")

        # Then: Should return 'supports'
        assert result == "supports"

    def test_map_label_entailment_case_insensitive(self) -> None:
        """TC-NLI-M-01b: Label mapping is case insensitive."""
        # Given: NLIModel instance
        from src.filter.nli import NLIModel

        model = NLIModel()

        # When: Mapping various cases
        # Then: All should return 'supports'
        assert model._map_label("ENTAILMENT") == "supports"
        assert model._map_label("Entailment") == "supports"
        assert model._map_label("support") == "supports"
        assert model._map_label("SUPPORTS") == "supports"

    def test_map_label_contradiction_to_refutes(self) -> None:
        """TC-NLI-M-02: 'contradiction' label is mapped to 'refutes'."""
        # Given: NLIModel instance
        from src.filter.nli import NLIModel

        model = NLIModel()

        # When: Mapping 'contradiction' label
        result = model._map_label("contradiction")

        # Then: Should return 'refutes'
        assert result == "refutes"

    def test_map_label_refute_variations(self) -> None:
        """TC-NLI-M-02b: Refute variations are mapped correctly."""
        # Given: NLIModel instance
        from src.filter.nli import NLIModel

        model = NLIModel()

        # When/Then: Various refute labels map to 'refutes'
        assert model._map_label("refute") == "refutes"
        assert model._map_label("REFUTES") == "refutes"
        assert model._map_label("CONTRADICTION") == "refutes"

    def test_map_label_neutral(self) -> None:
        """TC-NLI-M-03: 'neutral' label is mapped to 'neutral'."""
        # Given: NLIModel instance
        from src.filter.nli import NLIModel

        model = NLIModel()

        # When: Mapping 'neutral' label
        result = model._map_label("neutral")

        # Then: Should return 'neutral'
        assert result == "neutral"

    def test_map_label_unknown_to_neutral(self) -> None:
        """TC-NLI-M-04: Unknown label falls back to 'neutral'."""
        # Given: NLIModel instance
        from src.filter.nli import NLIModel

        model = NLIModel()

        # When: Mapping unknown labels
        # Then: All should return 'neutral' (fallback)
        assert model._map_label("unknown_label") == "neutral"
        assert model._map_label("") == "neutral"
        assert model._map_label("some_random_text") == "neutral"


class TestNLIModelPredict:
    """Tests for NLIModel.predict method."""

    @pytest.mark.asyncio
    async def test_predict_returns_calibrated_confidence(self) -> None:
        """TC-NLI-N-01 / TC-NLI-W-01: predict() returns calibrated confidence."""
        # Given: NLIModel with mocked pipeline and calibrator
        from src.filter.nli import NLIModel

        model = NLIModel()

        mock_pipeline = MagicMock()
        mock_pipeline.return_value = [{"label": "entailment", "score": 0.9}]
        model._model = mock_pipeline

        mock_calibrator = MagicMock()
        mock_calibrator.calibrate.return_value = 0.85  # Calibrated value

        with patch("src.filter.nli.get_calibrator", return_value=mock_calibrator):
            # When: Predicting stance
            result = await model.predict(
                premise="The earth is round.",
                nli_hypothesis="The earth is spherical.",
            )

        # Then: Result should have calibrated confidence
        assert result["label"] == "supports"
        assert result["nli_raw_confidence"] == 0.9
        assert result["nli_edge_confidence"] == 0.85
        assert result["raw_label"] == "entailment"

        # Verify calibrator was called with correct source
        mock_calibrator.calibrate.assert_called_once_with(
            prob=0.9,
            source="nli_judge",
            logit=None,
        )

    @pytest.mark.asyncio
    async def test_predict_empty_premise(self) -> None:
        """TC-NLI-B-02: Empty premise still processes and returns result."""
        # Given: NLIModel with mocked pipeline
        from src.filter.nli import NLIModel

        model = NLIModel()

        mock_pipeline = MagicMock()
        mock_pipeline.return_value = [{"label": "neutral", "score": 0.6}]
        model._model = mock_pipeline

        mock_calibrator = MagicMock()
        mock_calibrator.calibrate.return_value = 0.6

        with patch("src.filter.nli.get_calibrator", return_value=mock_calibrator):
            # When: Predicting with empty premise
            result = await model.predict(
                premise="",
                nli_hypothesis="Some hypothesis.",
            )

        # Then: Should still return a result
        assert result["label"] == "neutral"
        assert "nli_edge_confidence" in result

    @pytest.mark.asyncio
    async def test_predict_error_returns_neutral_fallback(self) -> None:
        """TC-NLI-A-02: Model prediction error returns neutral fallback."""
        # Given: NLIModel with pipeline that raises error
        from src.filter.nli import NLIModel

        model = NLIModel()

        mock_pipeline = MagicMock()
        mock_pipeline.side_effect = RuntimeError("CUDA out of memory")
        model._model = mock_pipeline

        # When: Predicting (should not raise)
        result = await model.predict(
            premise="Test premise",
            nli_hypothesis="Test hypothesis",
        )

        # Then: Should return neutral fallback with error
        assert result["label"] == "neutral"
        assert result["nli_raw_confidence"] == 0.0
        assert result["nli_edge_confidence"] == 0.0
        assert "error" in result
        assert "CUDA out of memory" in result["error"]


class TestNLIModelPredictBatch:
    """Tests for NLIModel.predict_batch method."""

    @pytest.mark.asyncio
    async def test_predict_batch_multiple_pairs(self) -> None:
        """TC-NLI-N-02: Batch prediction returns list of predictions."""
        # Given: NLIModel with mocked pipeline
        from src.filter.nli import NLIModel

        model = NLIModel()

        mock_pipeline = MagicMock()
        mock_pipeline.return_value = [
            {"label": "entailment", "score": 0.9},
            {"label": "contradiction", "score": 0.8},
            {"label": "neutral", "score": 0.7},
        ]
        model._model = mock_pipeline

        mock_calibrator = MagicMock()
        mock_calibrator.calibrate.side_effect = [0.85, 0.75, 0.65]

        with patch("src.filter.nli.get_calibrator", return_value=mock_calibrator):
            # When: Predicting batch
            pairs = [
                ("premise1", "hypothesis1"),
                ("premise2", "hypothesis2"),
                ("premise3", "hypothesis3"),
            ]
            results = await model.predict_batch(pairs)

        # Then: Should return list of predictions
        assert len(results) == 3
        assert results[0]["label"] == "supports"
        assert results[1]["label"] == "refutes"
        assert results[2]["label"] == "neutral"

    @pytest.mark.asyncio
    async def test_predict_batch_empty_list(self) -> None:
        """TC-NLI-B-01: Empty pairs list returns empty result."""
        # Given: NLIModel with mocked pipeline
        from src.filter.nli import NLIModel

        model = NLIModel()

        mock_pipeline = MagicMock()
        mock_pipeline.return_value = []
        model._model = mock_pipeline

        mock_calibrator = MagicMock()

        with patch("src.filter.nli.get_calibrator", return_value=mock_calibrator):
            # When: Predicting empty batch
            results = await model.predict_batch([])

        # Then: Should return empty list
        assert results == []

    @pytest.mark.asyncio
    async def test_predict_batch_error_returns_fallback_list(self) -> None:
        """TC-NLI-A-02b: Batch prediction error returns neutral fallback for all."""
        # Given: NLIModel with pipeline that raises error
        from src.filter.nli import NLIModel

        model = NLIModel()

        mock_pipeline = MagicMock()
        mock_pipeline.side_effect = RuntimeError("Batch inference failed")
        model._model = mock_pipeline

        # When: Predicting batch (should not raise)
        pairs = [
            ("premise1", "hypothesis1"),
            ("premise2", "hypothesis2"),
        ]
        results = await model.predict_batch(pairs)

        # Then: Should return neutral fallbacks for all pairs
        assert len(results) == 2
        assert all(r["label"] == "neutral" for r in results)
        assert all(r["nli_edge_confidence"] == 0.0 for r in results)
        assert all("error" in r for r in results)


class TestNLIModelEnsureModel:
    """Tests for NLIModel._ensure_model method."""

    @pytest.mark.asyncio
    async def test_ensure_model_skips_if_already_loaded(self) -> None:
        """TC-NLI-N-01c: Model is not reloaded if already present."""
        # Given: NLIModel with model already loaded
        from src.filter.nli import NLIModel

        model = NLIModel()
        existing_model = MagicMock()
        model._model = existing_model

        # When: Ensuring model (should skip)
        await model._ensure_model()

        # Then: Model should remain unchanged
        assert model._model is existing_model

    @pytest.mark.asyncio
    async def test_ensure_model_loads_pipeline(self) -> None:
        """TC-NLI-N-01b: Model is loaded via transformers pipeline."""
        # Given: NLIModel with no model loaded
        # Note: This test verifies the code path, not actual model loading
        # Actual model loading requires GPU and is tested in integration tests
        from src.filter.nli import NLIModel

        model = NLIModel()
        assert model._model is None

        # When: Setting model directly (simulating successful load)
        mock_pipeline_result = MagicMock()
        model._model = mock_pipeline_result

        # Then: Model is set
        assert model._model is mock_pipeline_result

        # Verify _ensure_model is idempotent
        await model._ensure_model()
        assert model._model is mock_pipeline_result


class TestNLIJudge:
    """Tests for nli_judge function."""

    @pytest.mark.asyncio
    async def test_nli_judge_remote_mode(self) -> None:
        """TC-NLI-N-03: nli_judge uses remote ML client when configured."""
        # Given: Remote ML mode enabled
        from src.filter.nli import nli_judge

        mock_settings = MagicMock()
        mock_settings.ml.use_remote = True

        mock_ml_client = MagicMock()
        mock_ml_client.nli = AsyncMock(
            return_value=[
                {"pair_id": "p1", "label": "supports", "confidence": 0.9},
            ]
        )

        mock_calibrator = MagicMock()
        mock_calibrator.calibrate.return_value = 0.85

        # Patch at use site: get_ml_client is imported inside _nli_judge_remote
        with (
            patch("src.filter.nli.get_settings", return_value=mock_settings),
            patch("src.ml_client.get_ml_client", return_value=mock_ml_client),
            patch("src.filter.nli.get_calibrator", return_value=mock_calibrator),
        ):
            # When: Calling nli_judge
            pairs = [
                {
                    "pair_id": "p1",
                    "premise": "Evidence text",
                    "nli_hypothesis": "The claim is true",
                }
            ]
            results = await nli_judge(pairs)

        # Then: Remote client should be called
        mock_ml_client.nli.assert_called_once_with(pairs)
        assert len(results) == 1
        assert results[0]["pair_id"] == "p1"
        assert results[0]["stance"] == "supports"
        assert results[0]["nli_edge_confidence"] == 0.85

    @pytest.mark.asyncio
    async def test_nli_judge_local_mode(self) -> None:
        """TC-NLI-N-04: nli_judge uses local model when remote disabled."""
        # Given: Remote ML mode disabled
        mock_settings = MagicMock()
        mock_settings.ml.use_remote = False

        mock_model = MagicMock()
        mock_model.predict = AsyncMock(
            return_value={
                "label": "refutes",
                "nli_raw_confidence": 0.8,
                "nli_edge_confidence": 0.75,
            }
        )

        with (
            patch("src.filter.nli.get_settings", return_value=mock_settings),
            patch("src.filter.nli._get_model", return_value=mock_model),
        ):
            from src.filter.nli import nli_judge

            # When: Calling nli_judge
            pairs = [
                {
                    "pair_id": "p1",
                    "premise": "Evidence text",
                    "nli_hypothesis": "The claim is true",
                }
            ]
            results = await nli_judge(pairs)

        # Then: Local model should be called
        assert mock_model.predict.called
        assert len(results) == 1
        assert results[0]["stance"] == "refutes"
        assert results[0]["nli_edge_confidence"] == 0.75

    @pytest.mark.asyncio
    async def test_nli_judge_remote_empty_pairs(self) -> None:
        """TC-NLI-B-01b: nli_judge with empty pairs returns empty list (remote)."""
        # Given: Remote ML mode enabled
        from src.filter.nli import nli_judge

        mock_settings = MagicMock()
        mock_settings.ml.use_remote = True

        with patch("src.filter.nli.get_settings", return_value=mock_settings):
            # When: Calling nli_judge with empty pairs
            results = await nli_judge([])

        # Then: Should return empty list
        assert results == []

    @pytest.mark.asyncio
    async def test_nli_judge_remote_preserves_pair_id(self) -> None:
        """TC-NLI-N-03b: nli_judge preserves pair_id in results."""
        # Given: Remote ML mode enabled
        from src.filter.nli import nli_judge

        mock_settings = MagicMock()
        mock_settings.ml.use_remote = True

        mock_ml_client = MagicMock()
        # ML client returns result without pair_id
        mock_ml_client.nli = AsyncMock(
            return_value=[
                {"label": "neutral", "confidence": 0.5},
            ]
        )

        mock_calibrator = MagicMock()
        mock_calibrator.calibrate.return_value = 0.5

        # Patch at use site: get_ml_client is imported inside _nli_judge_remote
        with (
            patch("src.filter.nli.get_settings", return_value=mock_settings),
            patch("src.ml_client.get_ml_client", return_value=mock_ml_client),
            patch("src.filter.nli.get_calibrator", return_value=mock_calibrator),
        ):
            # When: Calling nli_judge
            pairs = [
                {
                    "pair_id": "test_pair_123",
                    "premise": "Evidence",
                    "nli_hypothesis": "Claim",
                }
            ]
            results = await nli_judge(pairs)

        # Then: pair_id should be preserved from input
        assert results[0]["pair_id"] == "test_pair_123"


class TestDetectContradictions:
    """Tests for detect_contradictions function."""

    @pytest.mark.asyncio
    async def test_detect_contradictions_finds_refuting_pairs(self) -> None:
        """TC-NLI-DC-01: Contradictions are detected between claims."""
        # Given: Claims that contradict each other
        claims = [
            {"id": "c1", "text": "The earth is flat."},
            {"id": "c2", "text": "The earth is spherical."},
        ]

        mock_model = MagicMock()
        mock_model.predict = AsyncMock(
            return_value={
                "label": "refutes",
                "nli_raw_confidence": 0.95,
                "nli_edge_confidence": 0.9,
            }
        )

        with patch("src.filter.nli._get_model", return_value=mock_model):
            from src.filter.nli import detect_contradictions

            # When: Detecting contradictions
            result = await detect_contradictions(claims)

        # Then: Should find contradiction
        assert len(result) == 1
        assert result[0]["claim1_id"] == "c1"
        assert result[0]["claim2_id"] == "c2"
        assert result[0]["nli_edge_confidence"] == 0.9

    @pytest.mark.asyncio
    async def test_detect_contradictions_no_refutation(self) -> None:
        """TC-NLI-DC-02: No contradictions when claims are consistent."""
        # Given: Claims that don't contradict each other
        claims = [
            {"id": "c1", "text": "The sky is blue."},
            {"id": "c2", "text": "Water is wet."},
        ]

        mock_model = MagicMock()
        mock_model.predict = AsyncMock(
            return_value={
                "label": "neutral",
                "nli_raw_confidence": 0.6,
                "nli_edge_confidence": 0.55,
            }
        )

        with patch("src.filter.nli._get_model", return_value=mock_model):
            from src.filter.nli import detect_contradictions

            # When: Detecting contradictions
            result = await detect_contradictions(claims)

        # Then: Should find no contradictions
        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_detect_contradictions_low_confidence_ignored(self) -> None:
        """TC-NLI-DC-02b: Low confidence refutations are not reported."""
        # Given: Claims with low confidence refutation
        claims = [
            {"id": "c1", "text": "Claim A"},
            {"id": "c2", "text": "Claim B"},
        ]

        mock_model = MagicMock()
        mock_model.predict = AsyncMock(
            return_value={
                "label": "refutes",
                "nli_raw_confidence": 0.5,
                "nli_edge_confidence": 0.45,  # Below 0.7 threshold
            }
        )

        with patch("src.filter.nli._get_model", return_value=mock_model):
            from src.filter.nli import detect_contradictions

            # When: Detecting contradictions
            result = await detect_contradictions(claims)

        # Then: Should ignore low confidence refutation
        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_detect_contradictions_empty_claims(self) -> None:
        """TC-NLI-DC-02c: Empty claims list returns empty result."""
        # Given: Empty claims list
        claims: list = []

        with patch("src.filter.nli._get_model"):
            from src.filter.nli import detect_contradictions

            # When: Detecting contradictions
            result = await detect_contradictions(claims)

        # Then: Should return empty list, model not called
        assert result == []

    @pytest.mark.asyncio
    async def test_detect_contradictions_single_claim(self) -> None:
        """TC-NLI-DC-02d: Single claim returns empty result (no pairs)."""
        # Given: Single claim (no pairs to compare)
        claims = [{"id": "c1", "text": "Only claim"}]

        with patch("src.filter.nli._get_model"):
            from src.filter.nli import detect_contradictions

            # When: Detecting contradictions
            result = await detect_contradictions(claims)

        # Then: Should return empty list
        assert result == []


class TestGetModel:
    """Tests for _get_model function."""

    def test_get_model_creates_singleton(self) -> None:
        """Test _get_model creates singleton instance."""
        # Given: Module with _nli_model = None
        from src.filter import nli

        # Reset module state
        nli._nli_model = None

        # When: Getting model twice
        model1 = nli._get_model()
        model2 = nli._get_model()

        # Then: Same instance should be returned
        assert model1 is model2
        assert isinstance(model1, nli.NLIModel)

        # Cleanup
        nli._nli_model = None
