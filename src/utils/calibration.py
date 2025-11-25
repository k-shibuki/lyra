"""
Confidence calibration for Lancet.

Implements probability calibration for LLM/NLI outputs (§3.3.4):
- Platt scaling (logistic regression on logits)
- Temperature scaling (single parameter scaling)
- Brier score evaluation
- Incremental recalibration (triggered after N samples accumulate)

References:
- §3.3.4: Confidence Calibration
- §7: Acceptance Criteria (Brier score improvement ≥20%)
"""

import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Sequence

import numpy as np

from src.utils.config import get_settings, get_project_root
from src.utils.logging import get_logger
from src.storage.database import get_database

logger = get_logger(__name__)


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class CalibrationSample:
    """Single sample for calibration."""
    
    predicted_prob: float  # Model's predicted probability
    actual_label: int  # Ground truth (0 or 1)
    logit: float | None = None  # Raw logit if available
    source: str = ""  # Source model (e.g., "llm_extract", "nli_judge")
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class CalibrationParams:
    """Calibration parameters."""
    
    method: str  # "platt" or "temperature"
    
    # Platt scaling params (logistic regression)
    platt_a: float = 1.0  # Slope
    platt_b: float = 0.0  # Intercept
    
    # Temperature scaling param
    temperature: float = 1.0
    
    # Metadata
    source: str = ""
    samples_used: int = 0
    brier_before: float | None = None
    brier_after: float | None = None
    fitted_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "method": self.method,
            "platt_a": self.platt_a,
            "platt_b": self.platt_b,
            "temperature": self.temperature,
            "source": self.source,
            "samples_used": self.samples_used,
            "brier_before": self.brier_before,
            "brier_after": self.brier_after,
            "fitted_at": self.fitted_at.isoformat(),
        }
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CalibrationParams":
        """Create from dictionary."""
        fitted_at = data.get("fitted_at")
        if isinstance(fitted_at, str):
            fitted_at = datetime.fromisoformat(fitted_at.replace("Z", "+00:00"))
        else:
            fitted_at = datetime.now(timezone.utc)
        
        return cls(
            method=data.get("method", "temperature"),
            platt_a=data.get("platt_a", 1.0),
            platt_b=data.get("platt_b", 0.0),
            temperature=data.get("temperature", 1.0),
            source=data.get("source", ""),
            samples_used=data.get("samples_used", 0),
            brier_before=data.get("brier_before"),
            brier_after=data.get("brier_after"),
            fitted_at=fitted_at,
        )


@dataclass
class CalibrationResult:
    """Result of calibration evaluation."""
    
    brier_score: float
    brier_score_calibrated: float | None = None
    improvement_ratio: float = 0.0  # (before - after) / before
    expected_calibration_error: float = 0.0  # ECE
    samples_evaluated: int = 0
    bins: list[dict[str, float]] = field(default_factory=list)  # Reliability diagram data
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "brier_score": self.brier_score,
            "brier_score_calibrated": self.brier_score_calibrated,
            "improvement_ratio": self.improvement_ratio,
            "expected_calibration_error": self.expected_calibration_error,
            "samples_evaluated": self.samples_evaluated,
            "bins": self.bins,
        }


# =============================================================================
# Calibration Methods
# =============================================================================

class PlattScaling:
    """Platt scaling (logistic regression) calibration.
    
    Fits: P(y=1|f) = 1 / (1 + exp(A*f + B))
    where f is the raw logit/score.
    """
    
    @staticmethod
    def fit(
        logits: Sequence[float],
        labels: Sequence[int],
        max_iter: int = 100,
        lr: float = 0.01,
    ) -> tuple[float, float]:
        """Fit Platt scaling parameters.
        
        Uses gradient descent to minimize log loss.
        
        Args:
            logits: Raw model outputs (logits or scores).
            labels: Ground truth labels (0 or 1).
            max_iter: Maximum iterations.
            lr: Learning rate.
            
        Returns:
            Tuple of (A, B) parameters.
        """
        logits = np.array(logits, dtype=np.float64)
        labels = np.array(labels, dtype=np.float64)
        
        # Initialize parameters
        A = 0.0
        B = 0.0
        
        n = len(logits)
        
        for _ in range(max_iter):
            # Forward pass
            z = A * logits + B
            p = 1.0 / (1.0 + np.exp(-z))
            
            # Clip for numerical stability
            p = np.clip(p, 1e-10, 1 - 1e-10)
            
            # Gradients
            error = p - labels
            grad_A = np.mean(error * logits)
            grad_B = np.mean(error)
            
            # Update
            A -= lr * grad_A
            B -= lr * grad_B
        
        return float(A), float(B)
    
    @staticmethod
    def transform(logit: float, A: float, B: float) -> float:
        """Apply Platt scaling to get calibrated probability.
        
        Args:
            logit: Raw logit/score.
            A: Platt A parameter.
            B: Platt B parameter.
            
        Returns:
            Calibrated probability.
        """
        z = A * logit + B
        return 1.0 / (1.0 + math.exp(-z))


class TemperatureScaling:
    """Temperature scaling calibration.
    
    Simple single-parameter scaling: P_calibrated = softmax(logit / T)
    """
    
    @staticmethod
    def fit(
        logits: Sequence[float],
        labels: Sequence[int],
        max_iter: int = 50,
        lr: float = 0.1,
    ) -> float:
        """Fit temperature parameter.
        
        Minimizes negative log likelihood.
        
        Args:
            logits: Raw model logits.
            labels: Ground truth labels.
            max_iter: Maximum iterations.
            lr: Learning rate.
            
        Returns:
            Optimal temperature.
        """
        logits = np.array(logits, dtype=np.float64)
        labels = np.array(labels, dtype=np.float64)
        
        # Start with T=1
        T = 1.0
        
        for _ in range(max_iter):
            # Scaled logits
            scaled = logits / T
            
            # Probabilities (binary case)
            p = 1.0 / (1.0 + np.exp(-scaled))
            p = np.clip(p, 1e-10, 1 - 1e-10)
            
            # Gradient of NLL w.r.t. T
            # d/dT sigmoid(x/T) = sigmoid(x/T) * (1 - sigmoid(x/T)) * (-x/T^2)
            sigmoid_grad = p * (1 - p) * (-logits / (T * T))
            
            # NLL gradient
            grad = np.mean(-(labels / p - (1 - labels) / (1 - p)) * sigmoid_grad)
            
            # Update
            T -= lr * grad
            T = max(0.1, min(T, 10.0))  # Clip to reasonable range
        
        return float(T)
    
    @staticmethod
    def transform(logit: float, temperature: float) -> float:
        """Apply temperature scaling.
        
        Args:
            logit: Raw logit.
            temperature: Temperature parameter.
            
        Returns:
            Calibrated probability.
        """
        scaled = logit / temperature
        return 1.0 / (1.0 + math.exp(-scaled))


# =============================================================================
# Evaluation Metrics
# =============================================================================

def brier_score(
    predictions: Sequence[float],
    labels: Sequence[int],
) -> float:
    """Calculate Brier score.
    
    Brier score = mean((predicted - actual)^2)
    Lower is better, 0 is perfect.
    
    Args:
        predictions: Predicted probabilities.
        labels: Ground truth labels (0 or 1).
        
    Returns:
        Brier score.
    """
    predictions = np.array(predictions)
    labels = np.array(labels)
    
    return float(np.mean((predictions - labels) ** 2))


def expected_calibration_error(
    predictions: Sequence[float],
    labels: Sequence[int],
    n_bins: int = 10,
) -> tuple[float, list[dict[str, float]]]:
    """Calculate Expected Calibration Error (ECE).
    
    ECE = sum(|B_m| / n * |accuracy(B_m) - confidence(B_m)|)
    
    Args:
        predictions: Predicted probabilities.
        labels: Ground truth labels.
        n_bins: Number of bins for discretization.
        
    Returns:
        Tuple of (ECE score, bin data for reliability diagram).
    """
    predictions = np.array(predictions)
    labels = np.array(labels)
    
    bin_boundaries = np.linspace(0, 1, n_bins + 1)
    bins_data = []
    ece = 0.0
    n = len(predictions)
    
    for i in range(n_bins):
        lower = bin_boundaries[i]
        upper = bin_boundaries[i + 1]
        
        # Find samples in this bin
        in_bin = (predictions > lower) & (predictions <= upper)
        count = np.sum(in_bin)
        
        if count > 0:
            accuracy = np.mean(labels[in_bin])
            confidence = np.mean(predictions[in_bin])
            
            ece += (count / n) * abs(accuracy - confidence)
            
            bins_data.append({
                "bin_lower": float(lower),
                "bin_upper": float(upper),
                "count": int(count),
                "accuracy": float(accuracy),
                "confidence": float(confidence),
                "gap": float(abs(accuracy - confidence)),
            })
        else:
            bins_data.append({
                "bin_lower": float(lower),
                "bin_upper": float(upper),
                "count": 0,
                "accuracy": 0.0,
                "confidence": 0.0,
                "gap": 0.0,
            })
    
    return float(ece), bins_data


# =============================================================================
# Calibrator
# =============================================================================

class Calibrator:
    """Main calibration manager.
    
    Handles:
    - Training calibration on validation data
    - Applying calibration to predictions
    - Persistence of calibration parameters
    - Incremental recalibration as new samples arrive
    """
    
    PARAMS_FILE = "calibration_params.json"
    SAMPLES_FILE = "calibration_samples.json"
    RECALIBRATION_THRESHOLD = 10  # Recalibrate after N new samples
    
    def __init__(self):
        self._settings = get_settings()
        self._params: dict[str, CalibrationParams] = {}  # source -> params
        self._pending_samples: dict[str, list[CalibrationSample]] = {}  # source -> samples
        self._load_params()
        self._load_samples()
    
    def _get_params_path(self) -> Path:
        """Get path to calibration parameters file."""
        return get_project_root() / "data" / self.PARAMS_FILE
    
    def _load_params(self) -> None:
        """Load saved calibration parameters."""
        path = self._get_params_path()
        
        if path.exists():
            try:
                with open(path) as f:
                    data = json.load(f)
                
                for source, params_dict in data.items():
                    self._params[source] = CalibrationParams.from_dict(params_dict)
                
                logger.info(
                    "Loaded calibration params",
                    sources=list(self._params.keys()),
                )
            except Exception as e:
                logger.warning("Failed to load calibration params", error=str(e))
    
    def _save_params(self) -> None:
        """Save calibration parameters."""
        path = self._get_params_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        
        data = {
            source: params.to_dict()
            for source, params in self._params.items()
        }
        
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
    
    def _get_samples_path(self) -> Path:
        """Get path to pending samples file."""
        return get_project_root() / "data" / self.SAMPLES_FILE
    
    def _load_samples(self) -> None:
        """Load pending calibration samples."""
        path = self._get_samples_path()
        
        if path.exists():
            try:
                with open(path) as f:
                    data = json.load(f)
                
                for source, samples_data in data.items():
                    self._pending_samples[source] = [
                        CalibrationSample(
                            predicted_prob=s["predicted_prob"],
                            actual_label=s["actual_label"],
                            logit=s.get("logit"),
                            source=s.get("source", source),
                        )
                        for s in samples_data
                    ]
            except Exception as e:
                logger.warning("Failed to load calibration samples", error=str(e))
    
    def _save_samples(self) -> None:
        """Save pending calibration samples."""
        path = self._get_samples_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        
        data = {
            source: [
                {
                    "predicted_prob": s.predicted_prob,
                    "actual_label": s.actual_label,
                    "logit": s.logit,
                    "source": s.source,
                }
                for s in samples
            ]
            for source, samples in self._pending_samples.items()
        }
        
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
    
    def add_sample(
        self,
        predicted_prob: float,
        actual_label: int,
        source: str,
        logit: float | None = None,
    ) -> bool:
        """Add a new calibration sample and trigger recalibration if needed.
        
        Call this after each prediction when ground truth becomes available.
        
        Args:
            predicted_prob: Model's predicted probability.
            actual_label: Ground truth label (0 or 1).
            source: Source model identifier.
            logit: Raw logit if available.
            
        Returns:
            True if recalibration was triggered.
        """
        sample = CalibrationSample(
            predicted_prob=predicted_prob,
            actual_label=actual_label,
            logit=logit,
            source=source,
        )
        
        if source not in self._pending_samples:
            self._pending_samples[source] = []
        
        self._pending_samples[source].append(sample)
        self._save_samples()
        
        # Check if recalibration needed
        if self.needs_recalibration(source):
            self._recalibrate(source)
            return True
        
        return False
    
    def _recalibrate(self, source: str) -> None:
        """Recalibrate using accumulated samples.
        
        Args:
            source: Source model identifier.
        """
        samples = self._pending_samples.get(source, [])
        
        if len(samples) < self.RECALIBRATION_THRESHOLD:
            return
        
        logger.info(
            "Triggering recalibration",
            source=source,
            samples=len(samples),
        )
        
        # Use temperature scaling by default
        self.fit(samples, source, method="temperature")
        
        # Clear pending samples after recalibration
        self._pending_samples[source] = []
        self._save_samples()
    
    def fit(
        self,
        samples: list[CalibrationSample],
        source: str,
        method: str = "temperature",
    ) -> CalibrationParams:
        """Fit calibration on samples.
        
        Args:
            samples: Calibration samples with predictions and labels.
            source: Source identifier (e.g., "llm_extract", "nli_judge").
            method: Calibration method ("platt" or "temperature").
            
        Returns:
            Fitted CalibrationParams.
        """
        if len(samples) < 10:
            logger.warning(
                "Insufficient samples for calibration",
                source=source,
                count=len(samples),
            )
            return CalibrationParams(method=method, source=source)
        
        # Extract data
        if method == "platt":
            # Need logits for Platt scaling
            logits = [
                s.logit if s.logit is not None else self._prob_to_logit(s.predicted_prob)
                for s in samples
            ]
            labels = [s.actual_label for s in samples]
            
            A, B = PlattScaling.fit(logits, labels)
            
            params = CalibrationParams(
                method="platt",
                platt_a=A,
                platt_b=B,
                source=source,
                samples_used=len(samples),
            )
        else:
            # Temperature scaling
            logits = [
                s.logit if s.logit is not None else self._prob_to_logit(s.predicted_prob)
                for s in samples
            ]
            labels = [s.actual_label for s in samples]
            
            T = TemperatureScaling.fit(logits, labels)
            
            params = CalibrationParams(
                method="temperature",
                temperature=T,
                source=source,
                samples_used=len(samples),
            )
        
        # Evaluate improvement
        predictions = [s.predicted_prob for s in samples]
        labels = [s.actual_label for s in samples]
        
        brier_before = brier_score(predictions, labels)
        
        calibrated = [self._apply_params(s.predicted_prob, s.logit, params) for s in samples]
        brier_after = brier_score(calibrated, labels)
        
        params.brier_before = brier_before
        params.brier_after = brier_after
        
        # Save
        self._params[source] = params
        self._save_params()
        
        logger.info(
            "Calibration fitted",
            source=source,
            method=method,
            brier_before=f"{brier_before:.4f}",
            brier_after=f"{brier_after:.4f}",
            improvement=f"{(brier_before - brier_after) / brier_before * 100:.1f}%",
        )
        
        return params
    
    def calibrate(
        self,
        prob: float,
        source: str,
        logit: float | None = None,
    ) -> float:
        """Calibrate a probability.
        
        Args:
            prob: Raw predicted probability.
            source: Source model identifier.
            logit: Raw logit if available.
            
        Returns:
            Calibrated probability.
        """
        if source not in self._params:
            return prob  # No calibration available
        
        params = self._params[source]
        return self._apply_params(prob, logit, params)
    
    def _apply_params(
        self,
        prob: float,
        logit: float | None,
        params: CalibrationParams,
    ) -> float:
        """Apply calibration parameters.
        
        Args:
            prob: Raw probability.
            logit: Raw logit (optional).
            params: Calibration parameters.
            
        Returns:
            Calibrated probability.
        """
        # Convert prob to logit if not provided
        if logit is None:
            logit = self._prob_to_logit(prob)
        
        if params.method == "platt":
            return PlattScaling.transform(logit, params.platt_a, params.platt_b)
        else:
            return TemperatureScaling.transform(logit, params.temperature)
    
    @staticmethod
    def _prob_to_logit(prob: float) -> float:
        """Convert probability to logit."""
        prob = max(1e-10, min(prob, 1 - 1e-10))
        return math.log(prob / (1 - prob))
    
    def evaluate(
        self,
        samples: list[CalibrationSample],
        source: str,
    ) -> CalibrationResult:
        """Evaluate calibration quality.
        
        Args:
            samples: Test samples.
            source: Source model identifier.
            
        Returns:
            CalibrationResult with metrics.
        """
        predictions = [s.predicted_prob for s in samples]
        labels = [s.actual_label for s in samples]
        
        brier_before = brier_score(predictions, labels)
        ece_before, bins = expected_calibration_error(predictions, labels)
        
        result = CalibrationResult(
            brier_score=brier_before,
            expected_calibration_error=ece_before,
            samples_evaluated=len(samples),
            bins=bins,
        )
        
        # Evaluate with calibration if available
        if source in self._params:
            calibrated = [
                self.calibrate(s.predicted_prob, source, s.logit)
                for s in samples
            ]
            
            brier_after = brier_score(calibrated, labels)
            result.brier_score_calibrated = brier_after
            
            if brier_before > 0:
                result.improvement_ratio = (brier_before - brier_after) / brier_before
        
        return result
    
    def get_params(self, source: str) -> CalibrationParams | None:
        """Get calibration parameters for source.
        
        Args:
            source: Source model identifier.
            
        Returns:
            CalibrationParams or None.
        """
        return self._params.get(source)
    
    def needs_recalibration(self, source: str) -> bool:
        """Check if source needs recalibration.
        
        Recalibration is triggered when enough new samples have accumulated.
        
        Args:
            source: Source model identifier.
            
        Returns:
            True if recalibration recommended.
        """
        pending_count = len(self._pending_samples.get(source, []))
        
        # If never calibrated, need at least threshold samples
        if source not in self._params:
            return pending_count >= self.RECALIBRATION_THRESHOLD
        
        # If already calibrated, recalibrate when new samples accumulate
        return pending_count >= self.RECALIBRATION_THRESHOLD
    
    def get_pending_sample_count(self, source: str) -> int:
        """Get number of pending samples for source.
        
        Args:
            source: Source model identifier.
            
        Returns:
            Number of pending samples.
        """
        return len(self._pending_samples.get(source, []))
    
    def get_all_sources(self) -> list[str]:
        """Get all calibrated sources.
        
        Returns:
            List of source identifiers.
        """
        return list(self._params.keys())


# =============================================================================
# Model Escalation Decision
# =============================================================================

class EscalationDecider:
    """Decides whether to escalate from fast to slow model.
    
    Uses calibrated probabilities to make escalation decisions
    based on cost-sensitive thresholds (§3.3.4).
    """
    
    DEFAULT_THRESHOLD = 0.7  # Escalate if confidence < threshold
    
    def __init__(self, calibrator: Calibrator):
        self._calibrator = calibrator
        self._settings = get_settings()
    
    def should_escalate(
        self,
        confidence: float,
        source: str,
        logit: float | None = None,
        threshold: float | None = None,
    ) -> tuple[bool, float]:
        """Decide if model escalation is needed.
        
        Args:
            confidence: Model's confidence/probability.
            source: Source model identifier.
            logit: Raw logit if available.
            threshold: Custom threshold (default from settings).
            
        Returns:
            Tuple of (should_escalate, calibrated_confidence).
        """
        threshold = threshold or self._settings.quality.min_confidence_score
        
        # Get calibrated confidence
        calibrated = self._calibrator.calibrate(confidence, source, logit)
        
        # Escalate if calibrated confidence below threshold
        should_escalate = calibrated < threshold
        
        return should_escalate, calibrated
    
    def get_escalation_stats(self) -> dict[str, Any]:
        """Get escalation statistics.
        
        Returns:
            Statistics about escalation decisions.
        """
        # TODO: Track and return actual escalation stats
        return {
            "sources": self._calibrator.get_all_sources(),
            "threshold": self._settings.quality.min_confidence_score,
        }


# =============================================================================
# Global Instance
# =============================================================================

_calibrator: Calibrator | None = None
_escalation_decider: EscalationDecider | None = None


def get_calibrator() -> Calibrator:
    """Get or create global Calibrator instance."""
    global _calibrator
    if _calibrator is None:
        _calibrator = Calibrator()
    return _calibrator


def get_escalation_decider() -> EscalationDecider:
    """Get or create global EscalationDecider instance."""
    global _escalation_decider
    if _escalation_decider is None:
        _escalation_decider = EscalationDecider(get_calibrator())
    return _escalation_decider


# =============================================================================
# MCP Tool Integration
# =============================================================================

async def calibrate_confidence(
    prob: float,
    source: str,
    logit: float | None = None,
) -> dict[str, Any]:
    """Calibrate a confidence value (for MCP tool use).
    
    Args:
        prob: Raw probability.
        source: Source model.
        logit: Raw logit.
        
    Returns:
        Calibrated result.
    """
    calibrator = get_calibrator()
    calibrated = calibrator.calibrate(prob, source, logit)
    
    params = calibrator.get_params(source)
    
    return {
        "original": prob,
        "calibrated": calibrated,
        "source": source,
        "has_calibration": params is not None,
        "method": params.method if params else None,
    }


async def evaluate_calibration(
    source: str,
    predictions: list[float],
    labels: list[int],
) -> dict[str, Any]:
    """Evaluate calibration for a source (for MCP tool use).
    
    Args:
        source: Source model.
        predictions: Predicted probabilities.
        labels: Ground truth labels.
        
    Returns:
        Evaluation result.
    """
    calibrator = get_calibrator()
    
    samples = [
        CalibrationSample(predicted_prob=p, actual_label=l, source=source)
        for p, l in zip(predictions, labels)
    ]
    
    result = calibrator.evaluate(samples, source)
    
    return result.to_dict()


async def fit_calibration(
    source: str,
    predictions: list[float],
    labels: list[int],
    method: str = "temperature",
) -> dict[str, Any]:
    """Fit calibration for a source (for MCP tool use).
    
    Args:
        source: Source model.
        predictions: Predicted probabilities.
        labels: Ground truth labels.
        method: Calibration method.
        
    Returns:
        Fitted parameters.
    """
    calibrator = get_calibrator()
    
    samples = [
        CalibrationSample(predicted_prob=p, actual_label=l, source=source)
        for p, l in zip(predictions, labels)
    ]
    
    params = calibrator.fit(samples, source, method)
    
    return params.to_dict()


async def check_escalation(
    confidence: float,
    source: str,
    logit: float | None = None,
) -> dict[str, Any]:
    """Check if model escalation is needed (for MCP tool use).
    
    Args:
        confidence: Model confidence.
        source: Source model.
        logit: Raw logit.
        
    Returns:
        Escalation decision.
    """
    decider = get_escalation_decider()
    should_escalate, calibrated = decider.should_escalate(confidence, source, logit)
    
    return {
        "should_escalate": should_escalate,
        "original_confidence": confidence,
        "calibrated_confidence": calibrated,
        "source": source,
    }


async def add_calibration_sample(
    predicted_prob: float,
    actual_label: int,
    source: str,
    logit: float | None = None,
) -> dict[str, Any]:
    """Add a calibration sample and trigger recalibration if needed (for MCP tool use).
    
    Call this after each prediction when ground truth becomes available.
    This enables incremental recalibration as data accumulates.
    
    Args:
        predicted_prob: Model's predicted probability.
        actual_label: Ground truth label (0 or 1).
        source: Source model identifier.
        logit: Raw logit if available.
        
    Returns:
        Status including whether recalibration occurred.
    """
    calibrator = get_calibrator()
    
    recalibrated = calibrator.add_sample(
        predicted_prob=predicted_prob,
        actual_label=actual_label,
        source=source,
        logit=logit,
    )
    
    return {
        "sample_added": True,
        "source": source,
        "recalibrated": recalibrated,
        "pending_samples": calibrator.get_pending_sample_count(source),
        "threshold": Calibrator.RECALIBRATION_THRESHOLD,
    }

