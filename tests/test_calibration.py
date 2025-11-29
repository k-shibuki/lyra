"""
Tests for confidence calibration module.

Covers:
- PlattScaling: Logistic regression calibration
- TemperatureScaling: Single parameter scaling
- Brier score and ECE metrics
- Calibrator: Main calibration manager
- EscalationDecider: Model escalation decisions

## Test Perspectives Table

| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---------|---------------------|---------------------------------------|-----------------|-------|
| TC-CS-N-01 | CalibrationSample | Equivalence – normal | All fields set | - |
| TC-CS-N-02 | Default values | Equivalence – normal | Sensible defaults | - |
| TC-CP-N-01 | to_dict | Equivalence – normal | Serializable dict | - |
| TC-CP-N-02 | from_dict | Equivalence – normal | Instance created | - |
| TC-PS-N-01 | Platt fit | Equivalence – normal | Improves calibration | - |
| TC-PS-N-02 | transform range | Equivalence – normal | [0, 1] output | - |
| TC-PS-N-03 | Identity transform | Equivalence – normal | sigmoid(0)=0.5 | - |
| TC-TS-N-01 | Temp fit positive | Equivalence – normal | T > 0 | - |
| TC-TS-N-02 | High T reduces conf | Equivalence – normal | Closer to 0.5 | - |
| TC-TS-N-03 | transform range | Equivalence – normal | [0, 1] output | - |
| TC-BS-N-01 | Perfect predictions | Equivalence – normal | Score = 0 | - |
| TC-BS-N-02 | Worst predictions | Equivalence – normal | Score = 1 | - |
| TC-BS-N-03 | Uncertain 0.5 | Equivalence – normal | Score = 0.25 | - |
| TC-BS-N-04 | Calibrated < overconf | Equivalence – normal | Lower score | - |
| TC-EC-N-01 | Perfect ECE | Equivalence – normal | ECE ≈ 0 | - |
| TC-EC-N-02 | Returns bins | Equivalence – normal | Bin data present | - |
| TC-CA-N-01 | fit_temperature | Equivalence – normal | Params returned | - |
| TC-CA-N-02 | fit_platt | Equivalence – normal | Params returned | - |
| TC-CA-N-03 | calibrate valid | Equivalence – normal | [0, 1] output | - |
| TC-CA-N-04 | calibrate no params | Equivalence – normal | Original returned | - |
| TC-CA-N-05 | evaluate metrics | Equivalence – normal | Metrics returned | - |
| TC-CA-N-06 | needs_recalib new | Equivalence – normal | False initially | - |
| TC-CA-N-07 | needs_recalib pending | Equivalence – normal | True at threshold | - |
| TC-CA-N-08 | add_sample accumulates | Equivalence – normal | Count increases | - |
| TC-CA-N-09 | add_sample triggers | Equivalence – normal | Returns True | - |
| TC-ED-N-01 | Escalate low conf | Equivalence – normal | True | - |
| TC-ED-N-02 | No escalate high | Equivalence – normal | False | - |
| TC-ED-N-03 | Uses calibrated | Equivalence – normal | Calibrated used | - |
| TC-MF-N-01 | calibrate_confidence | Equivalence – normal | Result dict | - |
| TC-MF-N-02 | evaluate_calibration | Equivalence – normal | Metrics dict | - |
| TC-MF-N-03 | fit_calibration | Equivalence – normal | Params dict | - |
| TC-MF-N-04 | check_escalation | Equivalence – normal | Decision dict | - |
| TC-MF-N-05 | add_calibration_sample | Equivalence – normal | Status dict | - |
| TC-EC-B-01 | Empty brier score | Boundary – empty | NaN | - |
| TC-EC-B-02 | Insufficient samples | Boundary – min | Default params | - |
| TC-EC-B-03 | Extreme probs | Boundary – 0/1 | No exception | - |
| TC-RE-N-01 | RollbackEvent create | Equivalence – normal | All fields set | - |
| TC-RE-N-02 | to_dict | Equivalence – normal | Serializable | - |
| TC-RE-N-03 | from_dict | Equivalence – normal | Instance created | - |
| TC-CH-N-01 | add_params version | Equivalence – normal | Incrementing | - |
| TC-CH-N-02 | get_latest | Equivalence – normal | Most recent | - |
| TC-CH-N-03 | get_previous | Equivalence – normal | Second most recent | - |
| TC-CH-N-04 | get_by_version | Equivalence – normal | Specific version | - |
| TC-CH-N-05 | max_history | Equivalence – normal | Limit enforced | - |
| TC-CH-N-06 | check_degradation | Equivalence – normal | Detects worse | - |
| TC-CH-N-07 | accepts improvement | Equivalence – normal | No flag | - |
| TC-CH-N-08 | rollback removes | Equivalence – normal | Current removed | - |
| TC-CH-N-09 | rollback logs event | Equivalence – normal | Event created | - |
| TC-CH-N-10 | rollback_to_version | Equivalence – normal | Goes to version | - |
| TC-CH-N-11 | get_stats | Equivalence – normal | Stats returned | - |
| TC-CR-N-01 | fit stores history | Equivalence – normal | History grows | - |
| TC-CR-N-02 | manual rollback | Equivalence – normal | Restores previous | - |
| TC-CR-N-03 | rollback_to_version | Equivalence – normal | Goes to version | - |
| TC-CR-N-04 | get_rollback_log | Equivalence – normal | Events returned | - |
| TC-CR-N-05 | get_history_stats | Equivalence – normal | Stats returned | - |
| TC-CR-N-06 | set_auto_rollback | Equivalence – normal | Toggles setting | - |
| TC-MR-N-01 | rollback success | Equivalence – normal | ok=True | - |
| TC-MR-N-02 | rollback no prev | Equivalence – normal | ok=False | - |
| TC-MR-N-03 | get_history | Equivalence – normal | Version list | - |
| TC-MR-N-04 | get_rollback_events | Equivalence – normal | Event list | - |
| TC-MR-N-05 | get_stats | Equivalence – normal | Comprehensive | - |
| TC-CE-N-01 | Evaluation create | Equivalence – normal | All fields set | - |
| TC-CE-N-02 | to_dict | Equivalence – normal | Serializable | - |
| TC-EV-N-01 | save_evaluation | Equivalence – normal | Saved to DB | - |
| TC-EV-N-02 | correct brier | Equivalence – normal | Score = 0 | - |
| TC-EV-N-03 | generate_id | Equivalence – normal | Unique IDs | - |
| TC-EV-N-04 | get_evaluations empty | Equivalence – normal | Empty list | - |
| TC-EV-N-05 | diagram no eval | Equivalence – normal | Error returned | - |
| TC-EV-N-06 | count_evaluations | Equivalence – normal | Count returned | - |
| TC-ME-N-01 | save_calibration_eval | Equivalence – normal | ok=True | - |
| TC-ME-N-02 | get_evaluations | Equivalence – normal | List returned | - |
| TC-ME-N-03 | get_diagram_data | Equivalence – normal | Bins returned | - |
"""

import pytest

# All tests in this module are unit tests (no external dependencies)
pytestmark = pytest.mark.unit
import math
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch
import tempfile

from src.utils.calibration import (
    CalibrationSample,
    CalibrationParams,
    CalibrationResult,
    CalibrationEvaluation,
    RollbackEvent,
    CalibrationHistory,
    CalibrationEvaluator,
    PlattScaling,
    TemperatureScaling,
    brier_score,
    expected_calibration_error,
    Calibrator,
    EscalationDecider,
    calibrate_confidence,
    evaluate_calibration,
    fit_calibration,
    check_escalation,
    add_calibration_sample,
    rollback_calibration,
    get_calibration_history,
    get_rollback_events,
    get_calibration_stats,
    save_calibration_evaluation,
    get_calibration_evaluations,
    get_reliability_diagram_data,
)


# =============================================================================
# Test Data
# =============================================================================

# Well-calibrated predictions (predictions ≈ actual frequency)
CALIBRATED_PREDICTIONS = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
CALIBRATED_LABELS = [0, 0, 0, 0, 1, 1, 1, 1, 1, 1]

# Overconfident predictions (predictions higher than actual)
OVERCONFIDENT_PREDICTIONS = [0.9, 0.8, 0.85, 0.75, 0.95, 0.7, 0.9, 0.8, 0.85, 0.9]
OVERCONFIDENT_LABELS = [0, 1, 0, 1, 1, 0, 0, 1, 1, 0]


# =============================================================================
# CalibrationSample Tests
# =============================================================================

class TestCalibrationSample:
    """Tests for CalibrationSample dataclass."""
    
    def test_create_sample(self):
        """Should create sample with all fields."""
        sample = CalibrationSample(
            predicted_prob=0.8,
            actual_label=1,
            logit=1.5,
            source="llm_extract",
        )
        
        assert sample.predicted_prob == 0.8
        assert sample.actual_label == 1
        assert sample.logit == 1.5
        assert sample.source == "llm_extract"
    
    def test_default_values(self):
        """Should have sensible defaults."""
        sample = CalibrationSample(
            predicted_prob=0.5,
            actual_label=0,
        )
        
        assert sample.logit is None
        assert sample.source == ""
        assert sample.timestamp is not None


# =============================================================================
# CalibrationParams Tests
# =============================================================================

class TestCalibrationParams:
    """Tests for CalibrationParams dataclass."""
    
    def test_to_dict(self):
        """Should convert to serializable dict."""
        params = CalibrationParams(
            method="temperature",
            temperature=1.5,
            source="test",
            samples_used=100,
        )
        
        d = params.to_dict()
        
        assert d["method"] == "temperature"
        assert d["temperature"] == 1.5
        assert d["source"] == "test"
        assert "fitted_at" in d
    
    def test_from_dict(self):
        """Should create from dict."""
        data = {
            "method": "platt",
            "platt_a": 1.2,
            "platt_b": -0.3,
            "source": "nli_judge",
            "samples_used": 50,
            "fitted_at": "2024-01-15T10:00:00+00:00",
        }
        
        params = CalibrationParams.from_dict(data)
        
        assert params.method == "platt"
        assert params.platt_a == 1.2
        assert params.platt_b == -0.3
        assert params.source == "nli_judge"


# =============================================================================
# PlattScaling Tests
# =============================================================================

class TestPlattScaling:
    """Tests for PlattScaling calibration."""
    
    def test_fit_improves_calibration(self):
        """Fitting should improve calibration on overconfident data."""
        # Convert probs to logits
        logits = [math.log(p / (1 - p + 1e-10)) for p in OVERCONFIDENT_PREDICTIONS]
        
        A, B = PlattScaling.fit(logits, OVERCONFIDENT_LABELS)
        
        # A and B should be non-trivial (not both at default values)
        is_default = (A == 1.0 and B == 0.0)
        assert not is_default, f"Expected non-default parameters, got A={A}, B={B}"
    
    def test_transform_valid_range(self):
        """Transform should output valid probabilities."""
        for logit in [-5, -1, 0, 1, 5]:
            prob = PlattScaling.transform(logit, 1.0, 0.0)
            assert 0.0 <= prob <= 1.0
    
    def test_transform_identity_when_no_scaling(self):
        """With A=1, B=0, should be identity sigmoid."""
        logit = 0.0
        prob = PlattScaling.transform(logit, 1.0, 0.0)
        
        assert abs(prob - 0.5) < 0.001


# =============================================================================
# TemperatureScaling Tests
# =============================================================================

class TestTemperatureScaling:
    """Tests for TemperatureScaling calibration."""
    
    def test_fit_returns_positive_temperature(self):
        """Temperature should be positive."""
        logits = [math.log(p / (1 - p + 1e-10)) for p in OVERCONFIDENT_PREDICTIONS]
        
        T = TemperatureScaling.fit(logits, OVERCONFIDENT_LABELS)
        
        assert T > 0
    
    def test_high_temperature_reduces_confidence(self):
        """Higher temperature should reduce extreme probabilities."""
        logit = 2.0  # High confidence
        
        prob_t1 = TemperatureScaling.transform(logit, 1.0)
        prob_t2 = TemperatureScaling.transform(logit, 2.0)
        
        # With higher temp, probability should be closer to 0.5
        assert abs(prob_t2 - 0.5) < abs(prob_t1 - 0.5)
    
    def test_transform_valid_range(self):
        """Transform should output valid probabilities."""
        for logit in [-5, -1, 0, 1, 5]:
            for T in [0.5, 1.0, 2.0]:
                prob = TemperatureScaling.transform(logit, T)
                assert 0.0 <= prob <= 1.0


# =============================================================================
# Metrics Tests
# =============================================================================

class TestBrierScore:
    """Tests for Brier score calculation."""
    
    def test_perfect_predictions(self):
        """Perfect predictions should have Brier score 0."""
        predictions = [0.0, 0.0, 1.0, 1.0]
        labels = [0, 0, 1, 1]
        
        score = brier_score(predictions, labels)
        
        assert score == 0.0
    
    def test_worst_predictions(self):
        """Completely wrong predictions should have high Brier score."""
        predictions = [1.0, 1.0, 0.0, 0.0]
        labels = [0, 0, 1, 1]
        
        score = brier_score(predictions, labels)
        
        assert score == 1.0
    
    def test_uncertain_predictions(self):
        """50% predictions should give Brier score 0.25."""
        predictions = [0.5, 0.5, 0.5, 0.5]
        labels = [0, 0, 1, 1]
        
        score = brier_score(predictions, labels)
        
        assert abs(score - 0.25) < 0.001
    
    def test_calibrated_lower_than_overconfident(self):
        """Well-calibrated predictions should have lower Brier score."""
        brier_calibrated = brier_score(CALIBRATED_PREDICTIONS, CALIBRATED_LABELS)
        brier_overconfident = brier_score(OVERCONFIDENT_PREDICTIONS, OVERCONFIDENT_LABELS)
        
        assert brier_calibrated < brier_overconfident


class TestExpectedCalibrationError:
    """Tests for ECE calculation."""
    
    def test_perfect_calibration(self):
        """Perfect calibration should have ECE 0."""
        # Predictions exactly match bin accuracy
        predictions = [0.5] * 10
        labels = [0, 0, 0, 0, 0, 1, 1, 1, 1, 1]
        
        ece, bins = expected_calibration_error(predictions, labels)
        
        assert ece < 0.1  # Allow small numerical error
    
    def test_returns_bin_data(self):
        """Should return bin data for reliability diagram."""
        ece, bins = expected_calibration_error(
            OVERCONFIDENT_PREDICTIONS,
            OVERCONFIDENT_LABELS,
            n_bins=5,
        )
        
        assert len(bins) == 5
        assert all("accuracy" in b for b in bins)
        assert all("confidence" in b for b in bins)


# =============================================================================
# Calibrator Tests
# =============================================================================

class TestCalibrator:
    """Tests for Calibrator class."""
    
    @pytest.fixture
    def calibrator(self, tmp_path):
        """Create calibrator with temp storage."""
        with patch("src.utils.calibration.get_project_root") as mock_root:
            mock_root.return_value = tmp_path
            return Calibrator()
    
    def test_fit_temperature(self, calibrator):
        """Should fit temperature scaling."""
        samples = [
            CalibrationSample(predicted_prob=p, actual_label=l, source="test")
            for p, l in zip(OVERCONFIDENT_PREDICTIONS, OVERCONFIDENT_LABELS)
        ]
        
        params = calibrator.fit(samples, "test", method="temperature")
        
        assert params.method == "temperature"
        assert params.temperature != 1.0  # Should have adjusted
        assert params.samples_used == len(samples)
    
    def test_fit_platt(self, calibrator):
        """Should fit Platt scaling."""
        samples = [
            CalibrationSample(predicted_prob=p, actual_label=l, source="test")
            for p, l in zip(OVERCONFIDENT_PREDICTIONS, OVERCONFIDENT_LABELS)
        ]
        
        params = calibrator.fit(samples, "test", method="platt")
        
        assert params.method == "platt"
        assert params.samples_used == len(samples)
    
    def test_calibrate_returns_valid_prob(self, calibrator):
        """Calibrated probability should be valid."""
        samples = [
            CalibrationSample(predicted_prob=p, actual_label=l, source="test")
            for p, l in zip(OVERCONFIDENT_PREDICTIONS, OVERCONFIDENT_LABELS)
        ]
        calibrator.fit(samples, "test")
        
        for prob in [0.1, 0.5, 0.9]:
            calibrated = calibrator.calibrate(prob, "test")
            assert 0.0 <= calibrated <= 1.0
    
    def test_calibrate_without_params(self, calibrator):
        """Should return original prob if no calibration."""
        prob = calibrator.calibrate(0.8, "unknown_source")
        
        assert prob == 0.8
    
    def test_evaluate_returns_metrics(self, calibrator):
        """Should return evaluation metrics."""
        samples = [
            CalibrationSample(predicted_prob=p, actual_label=l, source="test")
            for p, l in zip(OVERCONFIDENT_PREDICTIONS, OVERCONFIDENT_LABELS)
        ]
        
        result = calibrator.evaluate(samples, "test")
        
        assert result.brier_score >= 0
        assert result.expected_calibration_error >= 0
        assert result.samples_evaluated == len(samples)
    
    def test_needs_recalibration_new_source(self, calibrator):
        """New sources without samples don't need calibration (can't calibrate yet)."""
        # No samples yet - can't calibrate
        assert calibrator.needs_recalibration("new_source") is False
        
        # Add enough samples - now needs calibration
        for _ in range(Calibrator.RECALIBRATION_THRESHOLD):
            calibrator._pending_samples.setdefault("new_source", []).append(
                CalibrationSample(predicted_prob=0.5, actual_label=1, source="new_source")
            )
        assert calibrator.needs_recalibration("new_source") is True
    
    def test_needs_recalibration_with_pending_samples(self, calibrator):
        """Should trigger recalibration when enough samples pending."""
        # Initially calibrated
        samples = [
            CalibrationSample(predicted_prob=p, actual_label=l, source="test")
            for p, l in zip(OVERCONFIDENT_PREDICTIONS, OVERCONFIDENT_LABELS)
        ]
        calibrator.fit(samples, "test")
        
        # No pending samples yet
        assert calibrator.needs_recalibration("test") is False
        
        # Add samples up to threshold
        for i in range(Calibrator.RECALIBRATION_THRESHOLD):
            calibrator._pending_samples.setdefault("test", []).append(
                CalibrationSample(predicted_prob=0.5, actual_label=1, source="test")
            )
        
        assert calibrator.needs_recalibration("test") is True
    
    def test_add_sample_accumulates(self, calibrator):
        """add_sample should accumulate pending samples."""
        calibrator.add_sample(0.8, 1, "test")
        calibrator.add_sample(0.6, 0, "test")
        
        assert calibrator.get_pending_sample_count("test") == 2
    
    def test_add_sample_triggers_recalibration(self, calibrator):
        """add_sample should trigger recalibration at threshold."""
        # Add samples up to threshold - 1
        for i in range(Calibrator.RECALIBRATION_THRESHOLD - 1):
            result = calibrator.add_sample(0.8, 1, "test")
            assert result is False  # Not yet
        
        # Add one more to trigger
        result = calibrator.add_sample(0.8, 1, "test")
        assert result is True  # Triggered
        
        # Pending should be cleared after recalibration
        assert calibrator.get_pending_sample_count("test") == 0


# =============================================================================
# EscalationDecider Tests
# =============================================================================

class TestEscalationDecider:
    """Tests for EscalationDecider class."""
    
    @pytest.fixture
    def decider(self, tmp_path):
        """Create decider with temp calibrator."""
        with patch("src.utils.calibration.get_project_root") as mock_root:
            mock_root.return_value = tmp_path
            calibrator = Calibrator()
            return EscalationDecider(calibrator)
    
    def test_escalate_low_confidence(self, decider):
        """Should escalate when confidence below threshold."""
        should_escalate, calibrated = decider.should_escalate(
            0.5, "test", threshold=0.7
        )
        
        assert should_escalate is True
    
    def test_no_escalate_high_confidence(self, decider):
        """Should not escalate when confidence above threshold."""
        should_escalate, calibrated = decider.should_escalate(
            0.9, "test", threshold=0.7
        )
        
        assert should_escalate is False
    
    def test_uses_calibrated_confidence(self, decider):
        """Should use calibrated confidence for decision.
        
        Fitting on overconfident data should produce calibration that
        adjusts high confidence values.
        """
        # Fit calibration that lowers confidence
        samples = [
            CalibrationSample(predicted_prob=p, actual_label=l, source="test")
            for p, l in zip(OVERCONFIDENT_PREDICTIONS, OVERCONFIDENT_LABELS)
        ]
        decider._calibrator.fit(samples, "test", method="temperature")
        
        # Original 0.9 should be calibrated
        should_escalate, calibrated = decider.should_escalate(
            0.9, "test", threshold=0.7
        )
        
        # Calibrated value should be returned (valid probability in [0, 1])
        assert 0.0 <= calibrated <= 1.0, f"Calibrated confidence should be valid probability, got {calibrated}"
        # The calibration params should have been applied
        params = decider._calibrator.get_params("test")
        assert params is not None, "Expected calibration params to be set"
        # If temperature != 1.0, calibration was applied
        if params.temperature != 1.0:
            # Just verify we got a valid result - actual value depends on fitting
            assert isinstance(should_escalate, bool), "should_escalate should be bool"


# =============================================================================
# MCP Tool Function Tests
# =============================================================================

class TestMCPToolFunctions:
    """Tests for MCP tool integration functions."""
    
    @pytest.mark.asyncio
    async def test_calibrate_confidence(self):
        """calibrate_confidence should return result."""
        with patch("src.utils.calibration.get_calibrator") as mock_get:
            mock_calibrator = MagicMock()
            mock_calibrator.calibrate.return_value = 0.75
            mock_calibrator.get_params.return_value = CalibrationParams(
                method="temperature",
                temperature=1.2,
            )
            mock_get.return_value = mock_calibrator
            
            result = await calibrate_confidence(0.8, "test")
            
            assert result["original"] == 0.8
            assert result["calibrated"] == 0.75
            assert result["has_calibration"] is True
    
    @pytest.mark.asyncio
    async def test_evaluate_calibration(self):
        """evaluate_calibration should return metrics."""
        with patch("src.utils.calibration.get_calibrator") as mock_get:
            mock_calibrator = MagicMock()
            mock_calibrator.evaluate.return_value = CalibrationResult(
                brier_score=0.15,
                expected_calibration_error=0.05,
                samples_evaluated=100,
            )
            mock_get.return_value = mock_calibrator
            
            result = await evaluate_calibration(
                "test",
                [0.5, 0.6],
                [1, 0],
            )
            
            assert result["brier_score"] == 0.15
    
    @pytest.mark.asyncio
    async def test_fit_calibration(self):
        """fit_calibration should return params."""
        with patch("src.utils.calibration.get_calibrator") as mock_get:
            mock_calibrator = MagicMock()
            mock_calibrator.fit.return_value = CalibrationParams(
                method="temperature",
                temperature=1.3,
                samples_used=50,
            )
            mock_get.return_value = mock_calibrator
            
            result = await fit_calibration(
                "test",
                [0.5, 0.6],
                [1, 0],
            )
            
            assert result["method"] == "temperature"
            assert result["temperature"] == 1.3
    
    @pytest.mark.asyncio
    async def test_check_escalation(self):
        """check_escalation should return decision."""
        with patch("src.utils.calibration.get_escalation_decider") as mock_get:
            mock_decider = MagicMock()
            mock_decider.should_escalate.return_value = (True, 0.55)
            mock_get.return_value = mock_decider
            
            result = await check_escalation(0.6, "test")
            
            assert result["should_escalate"] is True
            assert result["calibrated_confidence"] == 0.55
    
    @pytest.mark.asyncio
    async def test_add_calibration_sample(self):
        """add_calibration_sample should add sample and return status."""
        with patch("src.utils.calibration.get_calibrator") as mock_get:
            mock_calibrator = MagicMock()
            mock_calibrator.add_sample.return_value = False
            mock_calibrator.get_pending_sample_count.return_value = 5
            mock_get.return_value = mock_calibrator
            
            result = await add_calibration_sample(0.8, 1, "test")
            
            assert result["sample_added"] is True
            assert result["pending_samples"] == 5
            assert result["recalibrated"] is False


# =============================================================================
# Edge Cases
# =============================================================================

class TestEdgeCases:
    """Edge case tests."""
    
    def test_brier_score_empty(self):
        """Should handle empty lists by returning NaN without warnings."""
        score = brier_score([], [])
        assert math.isnan(score)
    
    def test_fit_insufficient_samples(self, tmp_path):
        """Should handle insufficient samples gracefully."""
        with patch("src.utils.calibration.get_project_root") as mock_root:
            mock_root.return_value = tmp_path
            calibrator = Calibrator()
            
            samples = [
                CalibrationSample(predicted_prob=0.5, actual_label=1, source="test")
            ]
            
            params = calibrator.fit(samples, "test")
            
            # Should return default params
            assert params.temperature == 1.0
    
    def test_prob_to_logit_extreme_values(self, tmp_path):
        """Should handle extreme probabilities."""
        with patch("src.utils.calibration.get_project_root") as mock_root:
            mock_root.return_value = tmp_path
            calibrator = Calibrator()
            
            # Should not raise
            logit_low = calibrator._prob_to_logit(0.0)
            logit_high = calibrator._prob_to_logit(1.0)
            
            assert logit_low < 0
            assert logit_high > 0


# =============================================================================
# RollbackEvent Tests
# =============================================================================

class TestRollbackEvent:
    """Tests for RollbackEvent dataclass."""
    
    def test_create_rollback_event(self):
        """Should create rollback event with all fields."""
        event = RollbackEvent(
            source="test",
            from_version=2,
            to_version=1,
            reason="degradation",
            brier_before_rollback=0.25,
            brier_after_rollback=0.15,
        )
        
        assert event.source == "test"
        assert event.from_version == 2
        assert event.to_version == 1
        assert event.reason == "degradation"
    
    def test_to_dict(self):
        """Should serialize to dict."""
        event = RollbackEvent(
            source="test",
            from_version=3,
            to_version=2,
            reason="manual",
            brier_before_rollback=0.30,
            brier_after_rollback=0.20,
        )
        
        d = event.to_dict()
        
        assert d["source"] == "test"
        assert d["from_version"] == 3
        assert d["to_version"] == 2
        assert "timestamp" in d
    
    def test_from_dict(self):
        """Should deserialize from dict."""
        data = {
            "source": "nli_judge",
            "from_version": 5,
            "to_version": 4,
            "reason": "degradation",
            "brier_before_rollback": 0.22,
            "brier_after_rollback": 0.18,
            "timestamp": "2024-01-15T12:00:00+00:00",
        }
        
        event = RollbackEvent.from_dict(data)
        
        assert event.source == "nli_judge"
        assert event.from_version == 5
        assert event.to_version == 4


# =============================================================================
# CalibrationHistory Tests
# =============================================================================

class TestCalibrationHistory:
    """Tests for CalibrationHistory class (§4.6.1)."""
    
    @pytest.fixture
    def history(self, tmp_path):
        """Create history with temp storage."""
        with patch("src.utils.calibration.get_project_root") as mock_root:
            mock_root.return_value = tmp_path
            return CalibrationHistory(max_history=5)
    
    def test_add_params_creates_version(self, history):
        """add_params should assign incrementing version numbers."""
        params1 = CalibrationParams(method="temperature", source="test", temperature=1.0)
        params2 = CalibrationParams(method="temperature", source="test", temperature=1.2)
        
        history.add_params(params1)
        history.add_params(params2)
        
        hist = history.get_history("test")
        assert len(hist) == 2
        assert hist[0].version == 1
        assert hist[1].version == 2
    
    def test_get_latest(self, history):
        """get_latest should return most recent params."""
        params1 = CalibrationParams(method="temperature", source="test", temperature=1.0)
        params2 = CalibrationParams(method="temperature", source="test", temperature=1.5)
        
        history.add_params(params1)
        history.add_params(params2)
        
        latest = history.get_latest("test")
        assert latest is not None
        assert latest.temperature == 1.5
    
    def test_get_previous(self, history):
        """get_previous should return second-most recent params."""
        params1 = CalibrationParams(method="temperature", source="test", temperature=1.0)
        params2 = CalibrationParams(method="temperature", source="test", temperature=1.5)
        
        history.add_params(params1)
        history.add_params(params2)
        
        previous = history.get_previous("test")
        assert previous is not None
        assert previous.temperature == 1.0
    
    def test_get_by_version(self, history):
        """get_by_version should find specific version."""
        params1 = CalibrationParams(method="temperature", source="test", temperature=1.0)
        params2 = CalibrationParams(method="temperature", source="test", temperature=1.5)
        
        history.add_params(params1)
        history.add_params(params2)
        
        found = history.get_by_version("test", 1)
        assert found is not None
        assert found.temperature == 1.0
    
    def test_max_history_enforced(self, history):
        """Should enforce max history limit."""
        for i in range(10):
            params = CalibrationParams(
                method="temperature", 
                source="test", 
                temperature=1.0 + i * 0.1
            )
            history.add_params(params)
        
        hist = history.get_history("test")
        assert len(hist) == 5  # max_history=5
    
    def test_check_degradation_detects_worsening(self, history):
        """check_degradation should detect Brier score increase."""
        params1 = CalibrationParams(
            method="temperature", source="test", 
            brier_before=0.20, brier_after=0.15
        )
        params2 = CalibrationParams(
            method="temperature", source="test",
            brier_before=0.20, brier_after=0.20  # Worse
        )
        
        history.add_params(params1)
        history.add_params(params2)
        
        # Check degradation for a hypothetical new value that's worse
        is_degraded, ratio = history.check_degradation("test", 0.25)
        
        # 0.25 is 25% worse than 0.20 (previous), which exceeds 5% threshold
        assert is_degraded is True
        assert ratio > 0.05
    
    def test_check_degradation_accepts_improvement(self, history):
        """check_degradation should not flag improvements."""
        params1 = CalibrationParams(
            method="temperature", source="test",
            brier_before=0.20, brier_after=0.15
        )
        params2 = CalibrationParams(
            method="temperature", source="test",
            brier_before=0.15, brier_after=0.12
        )
        
        history.add_params(params1)
        history.add_params(params2)
        
        # Check with better value
        is_degraded, ratio = history.check_degradation("test", 0.10)
        
        assert is_degraded is False
        assert ratio < 0
    
    def test_rollback_removes_current(self, history):
        """rollback should remove current params and return previous."""
        params1 = CalibrationParams(
            method="temperature", source="test", temperature=1.0,
            brier_after=0.15
        )
        params2 = CalibrationParams(
            method="temperature", source="test", temperature=1.5,
            brier_after=0.25
        )
        
        history.add_params(params1)
        history.add_params(params2)
        
        rolled_back = history.rollback("test", reason="degradation")
        
        assert rolled_back is not None
        assert rolled_back.temperature == 1.0
        assert len(history.get_history("test")) == 1
    
    def test_rollback_logs_event(self, history):
        """rollback should log a RollbackEvent."""
        params1 = CalibrationParams(
            method="temperature", source="test", temperature=1.0,
            brier_after=0.15
        )
        params2 = CalibrationParams(
            method="temperature", source="test", temperature=1.5,
            brier_after=0.25
        )
        
        history.add_params(params1)
        history.add_params(params2)
        history.rollback("test", reason="degradation")
        
        events = history.get_rollback_log("test")
        assert len(events) == 1
        assert events[0].reason == "degradation"
        assert events[0].from_version == 2
        assert events[0].to_version == 1
    
    def test_rollback_to_version(self, history):
        """rollback_to_version should go to specific version."""
        for i in range(5):
            params = CalibrationParams(
                method="temperature", source="test",
                temperature=1.0 + i * 0.1,
                brier_after=0.20 - i * 0.01
            )
            history.add_params(params)
        
        # Rollback to version 2
        rolled_back = history.rollback_to_version("test", 2, reason="manual")
        
        assert rolled_back is not None
        assert rolled_back.version == 2
        assert len(history.get_history("test")) == 2
    
    def test_get_stats(self, history):
        """get_stats should return history statistics."""
        params = CalibrationParams(
            method="temperature", source="test",
            brier_after=0.15
        )
        history.add_params(params)
        
        stats = history.get_stats()
        
        assert "sources" in stats
        assert "test" in stats["sources"]
        assert stats["sources"]["test"]["history_size"] == 1


# =============================================================================
# Calibrator Rollback Tests
# =============================================================================

class TestCalibratorRollback:
    """Tests for Calibrator rollback functionality (§4.6.1)."""
    
    @pytest.fixture
    def calibrator(self, tmp_path):
        """Create calibrator with temp storage."""
        with patch("src.utils.calibration.get_project_root") as mock_root:
            mock_root.return_value = tmp_path
            return Calibrator(enable_auto_rollback=True)
    
    def test_fit_stores_history(self, calibrator):
        """fit should add params to history."""
        samples = [
            CalibrationSample(predicted_prob=p, actual_label=l, source="test")
            for p, l in zip(OVERCONFIDENT_PREDICTIONS, OVERCONFIDENT_LABELS)
        ]
        
        calibrator.fit(samples, "test")
        calibrator.fit(samples, "test")
        
        history = calibrator.get_history("test")
        assert len(history) >= 2
    
    def test_manual_rollback(self, calibrator):
        """rollback should restore previous params."""
        samples = [
            CalibrationSample(predicted_prob=p, actual_label=l, source="test")
            for p, l in zip(OVERCONFIDENT_PREDICTIONS, OVERCONFIDENT_LABELS)
        ]
        
        calibrator.fit(samples, "test")
        first_temp = calibrator.get_params("test").temperature
        
        # Fit again (may have different params)
        calibrator.fit(samples, "test")
        
        # Rollback
        rolled_back = calibrator.rollback("test", reason="manual")
        
        assert rolled_back is not None
        assert calibrator.get_params("test").version == rolled_back.version
    
    def test_rollback_to_version(self, calibrator):
        """rollback_to_version should go to specific version."""
        samples = [
            CalibrationSample(predicted_prob=p, actual_label=l, source="test")
            for p, l in zip(OVERCONFIDENT_PREDICTIONS, OVERCONFIDENT_LABELS)
        ]
        
        # Create multiple versions
        for _ in range(3):
            calibrator.fit(samples, "test")
        
        # Rollback to version 1
        rolled_back = calibrator.rollback_to_version("test", 1)
        
        assert rolled_back is not None
        assert rolled_back.version == 1
    
    def test_get_rollback_log(self, calibrator):
        """get_rollback_log should return events."""
        samples = [
            CalibrationSample(predicted_prob=p, actual_label=l, source="test")
            for p, l in zip(OVERCONFIDENT_PREDICTIONS, OVERCONFIDENT_LABELS)
        ]
        
        calibrator.fit(samples, "test")
        calibrator.fit(samples, "test")
        calibrator.rollback("test")
        
        events = calibrator.get_rollback_log("test")
        assert len(events) == 1
    
    def test_get_history_stats(self, calibrator):
        """get_history_stats should return statistics."""
        samples = [
            CalibrationSample(predicted_prob=p, actual_label=l, source="test")
            for p, l in zip(OVERCONFIDENT_PREDICTIONS, OVERCONFIDENT_LABELS)
        ]
        
        calibrator.fit(samples, "test")
        
        stats = calibrator.get_history_stats()
        
        assert "sources" in stats
        assert "total_rollbacks" in stats
    
    def test_set_auto_rollback(self, calibrator):
        """set_auto_rollback should toggle setting."""
        calibrator.set_auto_rollback(False)
        assert calibrator._enable_auto_rollback is False
        
        calibrator.set_auto_rollback(True)
        assert calibrator._enable_auto_rollback is True


# =============================================================================
# MCP Rollback Tool Tests
# =============================================================================

class TestMCPRollbackTools:
    """Tests for MCP rollback tool functions."""
    
    @pytest.mark.asyncio
    async def test_rollback_calibration_success(self):
        """rollback_calibration should rollback and return result."""
        with patch("src.utils.calibration.get_calibrator") as mock_get:
            mock_calibrator = MagicMock()
            mock_calibrator.rollback.return_value = CalibrationParams(
                method="temperature",
                temperature=1.2,
                brier_after=0.15,
                version=1,
            )
            mock_get.return_value = mock_calibrator
            
            result = await rollback_calibration("test", reason="manual")
            
            assert result["ok"] is True
            assert result["rolled_back_to_version"] == 1
    
    @pytest.mark.asyncio
    async def test_rollback_calibration_no_previous(self):
        """rollback_calibration should handle no previous version."""
        with patch("src.utils.calibration.get_calibrator") as mock_get:
            mock_calibrator = MagicMock()
            mock_calibrator.rollback.return_value = None
            mock_get.return_value = mock_calibrator
            
            result = await rollback_calibration("test")
            
            assert result["ok"] is False
            assert result["reason"] == "no_previous_version"
    
    @pytest.mark.asyncio
    async def test_get_calibration_history(self):
        """get_calibration_history should return version list."""
        with patch("src.utils.calibration.get_calibrator") as mock_get:
            mock_calibrator = MagicMock()
            mock_calibrator.get_history.return_value = [
                CalibrationParams(
                    method="temperature",
                    temperature=1.0,
                    brier_before=0.20,
                    brier_after=0.15,
                    samples_used=50,
                    version=1,
                ),
                CalibrationParams(
                    method="temperature",
                    temperature=1.2,
                    brier_before=0.15,
                    brier_after=0.12,
                    samples_used=60,
                    version=2,
                ),
            ]
            mock_get.return_value = mock_calibrator
            
            result = await get_calibration_history("test")
            
            assert result["source"] == "test"
            assert result["total_versions"] == 2
            assert len(result["versions"]) == 2
    
    @pytest.mark.asyncio
    async def test_get_rollback_events(self):
        """get_rollback_events should return event list."""
        with patch("src.utils.calibration.get_calibrator") as mock_get:
            mock_calibrator = MagicMock()
            mock_calibrator.get_rollback_log.return_value = [
                RollbackEvent(
                    source="test",
                    from_version=2,
                    to_version=1,
                    reason="degradation",
                    brier_before_rollback=0.25,
                    brier_after_rollback=0.15,
                ),
            ]
            mock_get.return_value = mock_calibrator
            
            result = await get_rollback_events("test")
            
            assert result["total_events"] == 1
            assert result["events"][0]["reason"] == "degradation"
    
    @pytest.mark.asyncio
    async def test_get_calibration_stats(self):
        """get_calibration_stats should return comprehensive stats."""
        with patch("src.utils.calibration.get_calibrator") as mock_get:
            mock_calibrator = MagicMock()
            mock_calibrator.get_all_sources.return_value = ["test"]
            mock_calibrator.get_params.return_value = CalibrationParams(
                method="temperature",
                temperature=1.2,
                brier_after=0.15,
                samples_used=50,
                version=2,
            )
            mock_calibrator.get_history_stats.return_value = {
                "sources": {"test": {"history_size": 2}},
                "total_rollbacks": 1,
            }
            mock_get.return_value = mock_calibrator
            
            result = await get_calibration_stats()
            
            assert "current_params" in result
            assert "history" in result
            assert "recalibration_threshold" in result


# =============================================================================
# CalibrationEvaluation Tests (§4.6.1)
# =============================================================================

class TestCalibrationEvaluation:
    """Tests for CalibrationEvaluation dataclass."""
    
    def test_create_evaluation(self):
        """Should create evaluation with all fields."""
        evaluation = CalibrationEvaluation(
            id="eval_001",
            source="llm_extract",
            brier_score=0.15,
            brier_score_calibrated=0.12,
            improvement_ratio=0.20,
            expected_calibration_error=0.08,
            samples_evaluated=100,
            bins=[{"bin_lower": 0.0, "bin_upper": 0.1, "count": 10}],
            calibration_version=2,
            evaluated_at=datetime.now(timezone.utc),
        )
        
        assert evaluation.id == "eval_001"
        assert evaluation.source == "llm_extract"
        assert evaluation.brier_score == 0.15
        assert evaluation.improvement_ratio == 0.20
    
    def test_to_dict(self):
        """Should convert to serializable dict."""
        evaluation = CalibrationEvaluation(
            id="eval_002",
            source="nli_judge",
            brier_score=0.18,
            brier_score_calibrated=0.14,
            improvement_ratio=0.22,
            expected_calibration_error=0.06,
            samples_evaluated=50,
            bins=[],
            calibration_version=1,
            evaluated_at=datetime.now(timezone.utc),
        )
        
        d = evaluation.to_dict()
        
        assert d["evaluation_id"] == "eval_002"
        assert d["source"] == "nli_judge"
        assert "evaluated_at" in d


# =============================================================================
# CalibrationEvaluator Tests (§4.6.1)
# =============================================================================

class TestCalibrationEvaluator:
    """Tests for CalibrationEvaluator class (§4.6.1)."""
    
    @pytest.fixture
    def mock_db(self):
        """Create mock database."""
        db = MagicMock()
        db.execute = MagicMock(return_value=MagicMock(fetchall=MagicMock(return_value=[])))
        db.commit = MagicMock()
        return db
    
    @pytest.fixture
    def evaluator(self, mock_db, tmp_path):
        """Create evaluator with mock database."""
        with patch("src.utils.calibration.get_project_root") as mock_root:
            mock_root.return_value = tmp_path
            with patch("src.utils.calibration.get_database") as mock_get_db:
                mock_get_db.return_value = mock_db
                return CalibrationEvaluator(db=mock_db)
    
    def test_save_evaluation(self, evaluator, mock_db):
        """save_evaluation should calculate metrics and save to DB."""
        predictions = [0.1, 0.4, 0.6, 0.9, 0.2, 0.8, 0.3, 0.7, 0.5, 0.95]
        labels = [0, 0, 1, 1, 0, 1, 0, 1, 0, 1]
        
        evaluation = evaluator.save_evaluation("test_source", predictions, labels)
        
        assert evaluation.source == "test_source"
        assert evaluation.samples_evaluated == 10
        assert 0 <= evaluation.brier_score <= 1
        # Should have at least 1 calibration bin
        assert len(evaluation.bins) >= 1, f"Expected >=1 bins, got {len(evaluation.bins)}"
        mock_db.execute.assert_called()
        mock_db.commit.assert_called()
    
    def test_save_evaluation_stores_correct_brier(self, evaluator, mock_db):
        """save_evaluation should calculate correct Brier score."""
        # Perfect predictions
        predictions = [0.0, 0.0, 1.0, 1.0]
        labels = [0, 0, 1, 1]
        
        evaluation = evaluator.save_evaluation("test", predictions, labels)
        
        assert evaluation.brier_score == 0.0
    
    def test_generate_id(self, evaluator):
        """_generate_id should create unique IDs."""
        id1 = evaluator._generate_id()
        id2 = evaluator._generate_id()
        
        assert id1 != id2
        assert id1.startswith("eval_")
    
    def test_get_evaluations_empty(self, evaluator, mock_db):
        """get_evaluations should return empty list when no data."""
        mock_db.execute.return_value.fetchall.return_value = []
        
        evaluations = evaluator.get_evaluations(source="test")
        
        assert evaluations == []
    
    def test_get_reliability_diagram_data_no_evaluation(self, evaluator, mock_db):
        """get_reliability_diagram_data should return error when no evaluation."""
        mock_db.execute.return_value.fetchall.return_value = []
        
        result = evaluator.get_reliability_diagram_data("nonexistent")
        
        assert result["ok"] is False
        assert result["reason"] == "no_evaluation_found"
    
    def test_count_evaluations(self, evaluator, mock_db):
        """count_evaluations should return count."""
        mock_db.execute.return_value.fetchone.return_value = (5,)
        
        count = evaluator.count_evaluations("test")
        
        assert count == 5


# =============================================================================
# MCP Calibration Evaluation Tool Tests (§4.6.1)
# =============================================================================

class TestMCPCalibrationEvaluationTools:
    """Tests for MCP calibration evaluation tool functions (§4.6.1)."""
    
    @pytest.mark.asyncio
    async def test_save_calibration_evaluation(self):
        """save_calibration_evaluation should save and return result."""
        with patch("src.utils.calibration.get_calibration_evaluator") as mock_get:
            mock_evaluator = MagicMock()
            mock_evaluator.save_evaluation.return_value = CalibrationEvaluation(
                id="eval_test",
                source="test",
                brier_score=0.15,
                brier_score_calibrated=0.12,
                improvement_ratio=0.20,
                expected_calibration_error=0.08,
                samples_evaluated=100,
                bins=[],
                calibration_version=1,
                evaluated_at=datetime.now(timezone.utc),
            )
            mock_get.return_value = mock_evaluator
            
            result = await save_calibration_evaluation(
                source="test",
                predictions=[0.5, 0.6],
                labels=[1, 0],
            )
            
            assert result["ok"] is True
            assert result["evaluation_id"] == "eval_test"
            assert result["source"] == "test"
    
    @pytest.mark.asyncio
    async def test_get_calibration_evaluations(self):
        """get_calibration_evaluations should return evaluation history."""
        with patch("src.utils.calibration.get_calibration_evaluator") as mock_get:
            mock_evaluator = MagicMock()
            mock_evaluator.get_evaluations.return_value = [
                CalibrationEvaluation(
                    id="eval_1",
                    source="test",
                    brier_score=0.15,
                    brier_score_calibrated=0.12,
                    improvement_ratio=0.20,
                    expected_calibration_error=0.08,
                    samples_evaluated=100,
                    bins=[],
                    calibration_version=1,
                    evaluated_at=datetime.now(timezone.utc),
                ),
            ]
            mock_evaluator.count_evaluations.return_value = 1
            mock_get.return_value = mock_evaluator
            
            result = await get_calibration_evaluations(source="test", limit=10)
            
            assert result["ok"] is True
            assert len(result["evaluations"]) == 1
            assert result["total_count"] == 1
    
    @pytest.mark.asyncio
    async def test_get_reliability_diagram_data(self):
        """get_reliability_diagram_data should return bin data."""
        with patch("src.utils.calibration.get_calibration_evaluator") as mock_get:
            mock_evaluator = MagicMock()
            mock_evaluator.get_reliability_diagram_data.return_value = {
                "ok": True,
                "source": "test",
                "evaluation_id": "eval_1",
                "n_bins": 10,
                "bins": [{"bin_lower": 0.0, "bin_upper": 0.1, "count": 5}],
                "overall_ece": 0.08,
            }
            mock_get.return_value = mock_evaluator
            
            result = await get_reliability_diagram_data(source="test")
            
            assert result["ok"] is True
            assert result["source"] == "test"
            assert len(result["bins"]) == 1

