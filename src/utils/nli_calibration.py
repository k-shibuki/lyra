"""
NLI confidence calibration for Lyra.

Implements probability calibration for NLI model outputs:
- Platt scaling (logistic regression on logits)
- Temperature scaling (single parameter scaling)
- Brier score evaluation
- Parameter history and rollback support

Note: Per ADR-0011, calibration training (fit) is performed by offline scripts,
not MCP tools. MCP tools only provide state inspection (get_stats, get_evaluations)
and rollback functionality.

References:
- ADR-0011: LoRA Fine-tuning Strategy (MCP tooling rejected for training)
- Acceptance Criteria (Brier score improvement ≥20%)
"""

import json
import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from src.utils.config import get_project_root, get_settings
from src.utils.logging import get_logger

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
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


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
    fitted_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    version: int = 1  # Version number for history tracking

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
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CalibrationParams":
        """Create from dictionary."""
        fitted_at = data.get("fitted_at")
        if isinstance(fitted_at, str):
            fitted_at = datetime.fromisoformat(fitted_at.replace("Z", "+00:00"))
        else:
            fitted_at = datetime.now(UTC)

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
            version=data.get("version", 1),
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


@dataclass
class RollbackEvent:
    """Record of a calibration rollback event."""

    source: str
    from_version: int
    to_version: int
    reason: str  # "degradation" or "manual"
    brier_before_rollback: float
    brier_after_rollback: float
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "source": self.source,
            "from_version": self.from_version,
            "to_version": self.to_version,
            "reason": self.reason,
            "brier_before_rollback": self.brier_before_rollback,
            "brier_after_rollback": self.brier_after_rollback,
            "timestamp": self.timestamp.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RollbackEvent":
        """Create from dictionary."""
        timestamp = data.get("timestamp")
        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        else:
            timestamp = datetime.now(UTC)

        return cls(
            source=data.get("source", ""),
            from_version=data.get("from_version", 0),
            to_version=data.get("to_version", 0),
            reason=data.get("reason", ""),
            brier_before_rollback=data.get("brier_before_rollback", 0.0),
            brier_after_rollback=data.get("brier_after_rollback", 0.0),
            timestamp=timestamp,
        )


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
        logits_arr: np.ndarray[Any, np.dtype[np.float64]] = np.array(logits, dtype=np.float64)
        labels_arr: np.ndarray[Any, np.dtype[np.float64]] = np.array(labels, dtype=np.float64)

        # Initialize parameters
        A = 0.0
        B = 0.0

        for _ in range(max_iter):
            # Forward pass
            z = A * logits_arr + B
            p = 1.0 / (1.0 + np.exp(-z))

            # Clip for numerical stability
            p = np.clip(p, 1e-10, 1 - 1e-10)

            # Gradients
            error = p - labels_arr
            grad_A = np.mean(error * logits_arr)
            grad_B = np.mean(error)

            # Update
            A -= float(lr * grad_A)
            B -= float(lr * grad_B)

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
        logits_arr: np.ndarray = np.array(logits, dtype=np.float64)
        labels_arr: np.ndarray = np.array(labels, dtype=np.float64)

        # Start with T=1
        T: float = 1.0

        for _ in range(max_iter):
            # Scaled logits
            scaled = logits_arr / T

            # Probabilities (binary case)
            p = 1.0 / (1.0 + np.exp(-scaled))
            p = np.clip(p, 1e-10, 1 - 1e-10)

            # Gradient of NLL w.r.t. T
            # d/dT sigmoid(x/T) = sigmoid(x/T) * (1 - sigmoid(x/T)) * (-x/T^2)
            sigmoid_grad = p * (1 - p) * (-logits_arr / (T * T))

            # NLL gradient
            grad = float(np.mean(-(labels_arr / p - (1 - labels_arr) / (1 - p)) * sigmoid_grad))

            # Update
            T -= lr * grad
            T = max(0.1, min(T, 10.0))  # Clip to reasonable range

        return T

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
        Brier score. Returns NaN for empty inputs.
    """
    if not predictions or not labels:
        return float("nan")

    predictions_arr: np.ndarray[Any, np.dtype[Any]] = np.array(predictions)
    labels_arr: np.ndarray[Any, np.dtype[Any]] = np.array(labels)

    return float(np.mean((predictions_arr - labels_arr) ** 2))


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
    predictions_arr: np.ndarray[Any, np.dtype[Any]] = np.array(predictions)
    labels_arr: np.ndarray[Any, np.dtype[Any]] = np.array(labels)

    bin_boundaries = np.linspace(0, 1, n_bins + 1)
    bins_data = []
    ece = 0.0
    n = len(predictions)

    for i in range(n_bins):
        lower = bin_boundaries[i]
        upper = bin_boundaries[i + 1]

        # Find samples in this bin
        in_bin = (predictions_arr > lower) & (predictions_arr <= upper)
        count = np.sum(in_bin)

        if count > 0:
            accuracy = np.mean(labels_arr[in_bin])
            confidence = np.mean(predictions_arr[in_bin])

            ece += (count / n) * abs(accuracy - confidence)

            bins_data.append(
                {
                    "bin_lower": float(lower),
                    "bin_upper": float(upper),
                    "count": int(count),
                    "accuracy": float(accuracy),
                    "confidence": float(confidence),
                    "gap": float(abs(accuracy - confidence)),
                }
            )
        else:
            bins_data.append(
                {
                    "bin_lower": float(lower),
                    "bin_upper": float(upper),
                    "count": 0,
                    "accuracy": 0.0,
                    "confidence": 0.0,
                    "gap": 0.0,
                }
            )

    return float(ece), bins_data


# =============================================================================
# Calibration History Manager
# =============================================================================


class CalibrationHistory:
    """Manages calibration parameter history for rollback support.

    Implements requirements:
    - Parameter history preservation (up to max_history entries per source)
    - Degradation detection (Brier score worsening)
    - Automatic rollback to previous good parameters
    """

    HISTORY_FILE = "calibration_history.json"
    ROLLBACK_LOG_FILE = "calibration_rollback_log.json"
    DEFAULT_MAX_HISTORY = 10  # Keep last N parameter sets per source
    DEGRADATION_THRESHOLD = 0.05  # 5% Brier score increase triggers rollback

    def __init__(self, max_history: int = DEFAULT_MAX_HISTORY):
        """Initialize calibration history manager.

        Args:
            max_history: Maximum number of parameter sets to keep per source.
        """
        self._max_history = max_history
        self._history: dict[str, list[CalibrationParams]] = {}  # source -> [params]
        self._rollback_log: list[RollbackEvent] = []
        self._load_history()
        self._load_rollback_log()

    def _get_history_path(self) -> Path:
        """Get path to history file."""
        return get_project_root() / "data" / self.HISTORY_FILE

    def _get_rollback_log_path(self) -> Path:
        """Get path to rollback log file."""
        return get_project_root() / "data" / self.ROLLBACK_LOG_FILE

    def _load_history(self) -> None:
        """Load parameter history from file."""
        path = self._get_history_path()

        if path.exists():
            try:
                with open(path) as f:
                    data = json.load(f)

                for source, params_list in data.items():
                    self._history[source] = [CalibrationParams.from_dict(p) for p in params_list]

                logger.debug(
                    "Loaded calibration history",
                    sources=list(self._history.keys()),
                    total_entries=sum(len(v) for v in self._history.values()),
                )
            except Exception as e:
                logger.warning("Failed to load calibration history", error=str(e))

    def _save_history(self) -> None:
        """Save parameter history to file."""
        path = self._get_history_path()
        path.parent.mkdir(parents=True, exist_ok=True)

        data = {
            source: [p.to_dict() for p in params_list]
            for source, params_list in self._history.items()
        }

        with open(path, "w") as f:
            json.dump(data, f, indent=2)

    def _load_rollback_log(self) -> None:
        """Load rollback event log from file."""
        path = self._get_rollback_log_path()

        if path.exists():
            try:
                with open(path) as f:
                    data = json.load(f)

                self._rollback_log = [RollbackEvent.from_dict(e) for e in data]
            except Exception as e:
                logger.warning("Failed to load rollback log", error=str(e))

    def _save_rollback_log(self) -> None:
        """Save rollback event log to file."""
        path = self._get_rollback_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)

        data = [e.to_dict() for e in self._rollback_log]

        with open(path, "w") as f:
            json.dump(data, f, indent=2)

    def add_params(self, params: CalibrationParams) -> None:
        """Add new calibration parameters to history.

        Args:
            params: Calibration parameters to add.
        """
        source = params.source

        if source not in self._history:
            self._history[source] = []

        # Assign version number
        if self._history[source]:
            params.version = self._history[source][-1].version + 1
        else:
            params.version = 1

        self._history[source].append(params)

        # Trim history to max size
        if len(self._history[source]) > self._max_history:
            self._history[source] = self._history[source][-self._max_history :]

        self._save_history()

        logger.debug(
            "Added params to history",
            source=source,
            version=params.version,
            history_size=len(self._history[source]),
        )

    def get_history(self, source: str) -> list[CalibrationParams]:
        """Get parameter history for a source.

        Args:
            source: Source model identifier.

        Returns:
            List of historical parameter sets (oldest first).
        """
        return self._history.get(source, [])

    def get_latest(self, source: str) -> CalibrationParams | None:
        """Get most recent parameters for a source.

        Args:
            source: Source model identifier.

        Returns:
            Latest CalibrationParams or None.
        """
        history = self._history.get(source, [])
        return history[-1] if history else None

    def get_previous(self, source: str) -> CalibrationParams | None:
        """Get second-most recent parameters for a source.

        Args:
            source: Source model identifier.

        Returns:
            Previous CalibrationParams or None.
        """
        history = self._history.get(source, [])
        return history[-2] if len(history) >= 2 else None

    def get_by_version(self, source: str, version: int) -> CalibrationParams | None:
        """Get parameters by version number.

        Args:
            source: Source model identifier.
            version: Version number to retrieve.

        Returns:
            CalibrationParams with matching version or None.
        """
        for params in self._history.get(source, []):
            if params.version == version:
                return params
        return None

    def check_degradation(
        self,
        source: str,
        new_brier: float,
    ) -> tuple[bool, float]:
        """Check if new calibration shows degradation.

        Implements degradation detection.

        Args:
            source: Source model identifier.
            new_brier: Brier score with new calibration.

        Returns:
            Tuple of (is_degraded, degradation_ratio).
            degradation_ratio is (new - old) / old (positive = worse).
        """
        previous = self.get_previous(source)

        if previous is None or previous.brier_after is None:
            return False, 0.0

        old_brier = previous.brier_after

        if old_brier <= 0:
            return False, 0.0

        degradation_ratio = (new_brier - old_brier) / old_brier
        is_degraded = degradation_ratio > self.DEGRADATION_THRESHOLD

        if is_degraded:
            logger.warning(
                "Calibration degradation detected",
                source=source,
                old_brier=f"{old_brier:.4f}",
                new_brier=f"{new_brier:.4f}",
                degradation=f"{degradation_ratio * 100:.1f}%",
            )

        return is_degraded, degradation_ratio

    def rollback(
        self,
        source: str,
        reason: str = "degradation",
    ) -> CalibrationParams | None:
        """Rollback to previous calibration parameters.

        Implements automatic rollback.

        Args:
            source: Source model identifier.
            reason: Reason for rollback ("degradation" or "manual").

        Returns:
            Rolled-back CalibrationParams or None if no previous available.
        """
        history = self._history.get(source, [])

        if len(history) < 2:
            logger.warning(
                "Cannot rollback: insufficient history",
                source=source,
                history_size=len(history),
            )
            return None

        # Current (to be rolled back from)
        current = history[-1]
        # Previous (to rollback to)
        previous = history[-2]

        # Record rollback event
        event = RollbackEvent(
            source=source,
            from_version=current.version,
            to_version=previous.version,
            reason=reason,
            brier_before_rollback=current.brier_after or 0.0,
            brier_after_rollback=previous.brier_after or 0.0,
        )
        self._rollback_log.append(event)
        self._save_rollback_log()

        # Remove the current (bad) parameters from history
        self._history[source] = history[:-1]
        self._save_history()

        logger.info(
            "Calibration rolled back",
            source=source,
            from_version=current.version,
            to_version=previous.version,
            reason=reason,
        )

        return previous

    def rollback_to_version(
        self,
        source: str,
        target_version: int,
        reason: str = "manual",
    ) -> CalibrationParams | None:
        """Rollback to a specific version.

        Args:
            source: Source model identifier.
            target_version: Version number to rollback to.
            reason: Reason for rollback.

        Returns:
            Target CalibrationParams or None if not found.
        """
        history = self._history.get(source, [])

        if not history:
            return None

        target_idx = None
        for i, params in enumerate(history):
            if params.version == target_version:
                target_idx = i
                break

        if target_idx is None:
            logger.warning(
                "Rollback target version not found",
                source=source,
                target_version=target_version,
            )
            return None

        current = history[-1]
        target = history[target_idx]

        # Record rollback event
        event = RollbackEvent(
            source=source,
            from_version=current.version,
            to_version=target.version,
            reason=reason,
            brier_before_rollback=current.brier_after or 0.0,
            brier_after_rollback=target.brier_after or 0.0,
        )
        self._rollback_log.append(event)
        self._save_rollback_log()

        # Keep only up to target version
        self._history[source] = history[: target_idx + 1]
        self._save_history()

        logger.info(
            "Calibration rolled back to specific version",
            source=source,
            from_version=current.version,
            to_version=target.version,
            reason=reason,
        )

        return target

    def get_rollback_log(
        self,
        source: str | None = None,
        limit: int = 100,
    ) -> list[RollbackEvent]:
        """Get rollback event history.

        Args:
            source: Optional source filter.
            limit: Maximum events to return.

        Returns:
            List of RollbackEvents (most recent first).
        """
        events = self._rollback_log

        if source:
            events = [e for e in events if e.source == source]

        return list(reversed(events[-limit:]))

    def get_stats(self) -> dict[str, Any]:
        """Get calibration history statistics.

        Returns:
            Dictionary with history statistics.
        """
        return {
            "sources": {
                source: {
                    "history_size": len(params_list),
                    "latest_version": params_list[-1].version if params_list else 0,
                    "latest_brier": params_list[-1].brier_after if params_list else None,
                }
                for source, params_list in self._history.items()
            },
            "total_rollbacks": len(self._rollback_log),
            "max_history_per_source": self._max_history,
        }


# =============================================================================
# Calibrator
# =============================================================================


class Calibrator:
    """Main calibration manager.

    Handles:
    - Training calibration on validation data (via fit())
    - Applying calibration to predictions
    - Persistence of calibration parameters
    - Degradation detection on fit() (rollback if Brier worsens by >5%)
    """

    PARAMS_FILE = "calibration_params.json"

    def __init__(self, enable_auto_rollback: bool = True):
        """Initialize calibrator.

        Args:
            enable_auto_rollback: Enable rollback on degradation when fit() is called.
        """
        self._settings = get_settings()
        self._params: dict[str, CalibrationParams] = {}  # source -> params
        self._history = CalibrationHistory()
        self._enable_auto_rollback = enable_auto_rollback
        self._load_params()

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

        data = {source: params.to_dict() for source, params in self._params.items()}

        with open(path, "w") as f:
            json.dump(data, f, indent=2)

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

        # Check for degradation before saving
        is_degraded, degradation_ratio = self._history.check_degradation(source, brier_after)

        if is_degraded and self._enable_auto_rollback:
            # Rollback to previous parameters
            logger.warning(
                "Auto-rollback triggered due to degradation",
                source=source,
                new_brier=f"{brier_after:.4f}",
                degradation=f"{degradation_ratio * 100:.1f}%",
            )

            rollback_params = self._history.rollback(source, reason="degradation")

            if rollback_params:
                self._params[source] = rollback_params
                self._save_params()
                return rollback_params

        # Add to history (before updating current params)
        self._history.add_params(params)

        # Update current params
        self._params[source] = params
        self._save_params()

        improvement_pct = (
            (brier_before - brier_after) / brier_before * 100 if brier_before > 0 else 0.0
        )

        logger.info(
            "Calibration fitted",
            source=source,
            method=method,
            version=params.version,
            brier_before=f"{brier_before:.4f}",
            brier_after=f"{brier_after:.4f}",
            improvement=f"{improvement_pct:.1f}%",
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
            calibrated = [self.calibrate(s.predicted_prob, source, s.logit) for s in samples]

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

    def get_all_sources(self) -> list[str]:
        """Get all calibrated sources.

        Returns:
            List of source identifiers.
        """
        return list(self._params.keys())

    # =========================================================================
    # Rollback Methods
    # =========================================================================

    def rollback(
        self,
        source: str,
        reason: str = "manual",
    ) -> CalibrationParams | None:
        """Rollback to previous calibration parameters.

        Args:
            source: Source model identifier.
            reason: Reason for rollback.

        Returns:
            Rolled-back CalibrationParams or None.
        """
        rollback_params = self._history.rollback(source, reason)

        if rollback_params:
            self._params[source] = rollback_params
            self._save_params()
            return rollback_params

        return None

    def rollback_to_version(
        self,
        source: str,
        version: int,
        reason: str = "manual",
    ) -> CalibrationParams | None:
        """Rollback to a specific version.

        Args:
            source: Source model identifier.
            version: Target version number.
            reason: Reason for rollback.

        Returns:
            Target CalibrationParams or None.
        """
        rollback_params = self._history.rollback_to_version(source, version, reason)

        if rollback_params:
            self._params[source] = rollback_params
            self._save_params()
            return rollback_params

        return None

    def get_history(self, source: str) -> list[CalibrationParams]:
        """Get calibration parameter history for a source.

        Args:
            source: Source model identifier.

        Returns:
            List of historical parameter sets.
        """
        return self._history.get_history(source)

    def get_rollback_log(
        self,
        source: str | None = None,
        limit: int = 100,
    ) -> list[RollbackEvent]:
        """Get rollback event history.

        Args:
            source: Optional source filter.
            limit: Maximum events to return.

        Returns:
            List of RollbackEvents.
        """
        return self._history.get_rollback_log(source, limit)

    def get_history_stats(self) -> dict[str, Any]:
        """Get calibration history statistics.

        Returns:
            Dictionary with history statistics.
        """
        return self._history.get_stats()

    def set_auto_rollback(self, enabled: bool) -> None:
        """Enable or disable automatic rollback.

        Args:
            enabled: Whether to enable auto-rollback.
        """
        self._enable_auto_rollback = enabled
        logger.info("Auto-rollback setting updated", enabled=enabled)


# =============================================================================
# Global Instance
# =============================================================================

_calibrator: Calibrator | None = None


def get_calibrator() -> Calibrator:
    """Get or create global Calibrator instance."""
    global _calibrator
    if _calibrator is None:
        _calibrator = Calibrator()
    return _calibrator


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
        CalibrationSample(predicted_prob=p, actual_label=label, source=source)
        for p, label in zip(predictions, labels, strict=False)
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
        CalibrationSample(predicted_prob=p, actual_label=label, source=source)
        for p, label in zip(predictions, labels, strict=False)
    ]

    params = calibrator.fit(samples, source, method)

    return params.to_dict()


async def rollback_calibration(
    source: str,
    version: int | None = None,
    reason: str = "manual",
) -> dict[str, Any]:
    """Rollback calibration to a previous version (for MCP tool use).

    Implements rollback functionality.

    Args:
        source: Source model identifier.
        version: Target version to rollback to. If None, rollback to previous.
        reason: Reason for rollback.

    Returns:
        Rollback result including new active parameters.
    """
    calibrator = get_calibrator()

    if version is not None:
        params = calibrator.rollback_to_version(source, version, reason)
    else:
        params = calibrator.rollback(source, reason)

    if params is None:
        return {
            "ok": False,
            "source": source,
            "reason": "no_previous_version",
        }

    return {
        "ok": True,
        "source": source,
        "rolled_back_to_version": params.version,
        "brier_after": params.brier_after,
        "method": params.method,
    }


async def get_calibration_history(
    source: str,
) -> dict[str, Any]:
    """Get calibration parameter history for a source (for MCP tool use).

    Args:
        source: Source model identifier.

    Returns:
        History with all parameter versions.
    """
    calibrator = get_calibrator()

    history = calibrator.get_history(source)

    return {
        "source": source,
        "versions": [
            {
                "version": p.version,
                "method": p.method,
                "brier_before": p.brier_before,
                "brier_after": p.brier_after,
                "samples_used": p.samples_used,
                "fitted_at": p.fitted_at.isoformat(),
            }
            for p in history
        ],
        "total_versions": len(history),
    }


async def get_rollback_events(
    source: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Get rollback event history (for MCP tool use).

    Args:
        source: Optional source filter.
        limit: Maximum events to return.

    Returns:
        List of rollback events.
    """
    calibrator = get_calibrator()

    events = calibrator.get_rollback_log(source, limit)

    return {
        "events": [e.to_dict() for e in events],
        "total_events": len(events),
        "filter_source": source,
    }


async def get_calibration_stats() -> dict[str, Any]:
    """Get calibration and history statistics (for MCP tool use).

    Returns:
        Comprehensive calibration statistics.
    """
    calibrator = get_calibrator()

    history_stats = calibrator.get_history_stats()

    current_params = {}
    for source in calibrator.get_all_sources():
        params = calibrator.get_params(source)
        if params:
            current_params[source] = {
                "version": params.version,
                "method": params.method,
                "brier_after": params.brier_after,
                "samples_used": params.samples_used,
            }

    return {
        "current_params": current_params,
        "history": history_stats,
        "degradation_threshold": CalibrationHistory.DEGRADATION_THRESHOLD,
    }


async def save_evaluation_result(
    source: str,
    result: CalibrationResult,
    calibration_version: int | None = None,
) -> dict[str, Any]:
    """Persist evaluation result to calibration_evaluations table.

    This enables historical tracking of calibration quality over time.
    Called after evaluate() to store the evaluation metrics.

    Args:
        source: Source model identifier (e.g., "nli_judge").
        result: CalibrationResult from evaluate().
        calibration_version: Version of calibration params used (optional).

    Returns:
        Dict with ok status and evaluation_id.
    """
    import uuid

    from src.storage.database import get_database

    evaluation_id = f"eval_{uuid.uuid4().hex[:12]}"
    evaluated_at = datetime.now(UTC).isoformat()

    try:
        db = await get_database()

        # Serialize bins to JSON
        bins_json = json.dumps(result.bins) if result.bins else "[]"

        await db.execute(
            """
            INSERT INTO calibration_evaluations (
                id, source, brier_score, brier_score_calibrated,
                improvement_ratio, expected_calibration_error,
                samples_evaluated, bins_json, calibration_version, evaluated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                evaluation_id,
                source,
                result.brier_score,
                result.brier_score_calibrated,
                result.improvement_ratio,
                result.expected_calibration_error,
                result.samples_evaluated,
                bins_json,
                calibration_version,
                evaluated_at,
            ),
        )
        # Note: Database uses auto-commit mode (isolation_level=None), no explicit commit needed

        logger.info(
            "Saved calibration evaluation",
            evaluation_id=evaluation_id,
            source=source,
            brier_score=f"{result.brier_score:.4f}",
            samples=result.samples_evaluated,
        )

        return {
            "ok": True,
            "evaluation_id": evaluation_id,
            "source": source,
            "brier_score": result.brier_score,
            "brier_score_calibrated": result.brier_score_calibrated,
            "improvement_ratio": result.improvement_ratio,
        }

    except Exception as e:
        logger.error("Failed to save evaluation result", source=source, error=str(e))
        return {
            "ok": False,
            "error": str(e),
        }


# =============================================================================
# Unified Calibration API
# =============================================================================
#
# NOTE: Batch evaluation and visualization are handled by scripts, not MCP tools.
# The calibration_evaluations table remains for historical data and script access.
# See ADR-0011 for LoRA fine-tuning design and script usage.
#


async def calibration_metrics_action(
    action: str, data: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Unified calibration metrics API for MCP.

    This is the single entry point for calibration metrics operations (except rollback).

    Batch evaluation and visualization are handled by scripts, not MCP tools.
    See ADR-0011 for LoRA fine-tuning design and script usage.

    Args:
        action: One of "get_stats", "get_evaluations"
        data: Action-specific data (optional for get_stats)

    Returns:
        Action result with ok: bool and action-specific fields

    Actions:
        - get_stats: Get calibration statistics (no data required)
        - get_evaluations: Get evaluation history
            data: {source?: str, limit?: int, since?: str}

    Note:
        Ground-truth collection is done via feedback(edge_correct),
        which accumulates samples in nli_corrections table.

    Raises:
        ValueError: If action is invalid or required data is missing
    """
    if data is None:
        data = {}

    try:
        if action == "get_stats":
            result = await get_calibration_stats()
            return {"ok": True, "action": "get_stats", **result}

        elif action == "get_evaluations":
            # Query evaluation history from database
            from src.storage.database import get_database

            db = await get_database()
            source = data.get("source")
            limit = data.get("limit", 50)
            since = data.get("since")

            query = "SELECT * FROM calibration_evaluations WHERE 1=1"
            params: list[Any] = []

            if source is not None:
                query += " AND source = ?"
                params.append(source)

            if since is not None:
                query += " AND evaluated_at >= ?"
                params.append(since)

            query += " ORDER BY evaluated_at DESC LIMIT ?"
            params.append(limit)

            cursor = await db.execute(query, params)
            rows = await cursor.fetchall()

            evaluations = []
            for row in rows:
                # Handle both dict-like and tuple rows
                if hasattr(row, "keys"):
                    row_data = dict(row)
                else:
                    columns = [
                        "id",
                        "source",
                        "brier_score",
                        "brier_score_calibrated",
                        "improvement_ratio",
                        "expected_calibration_error",
                        "samples_evaluated",
                        "bins_json",
                        "calibration_version",
                        "evaluated_at",
                        "created_at",
                    ]
                    row_data = dict(zip(columns, row, strict=False))

                evaluations.append(
                    {
                        "evaluation_id": row_data["id"],
                        "source": row_data["source"],
                        "brier_score": row_data["brier_score"],
                        "brier_score_calibrated": row_data["brier_score_calibrated"],
                        "improvement_ratio": row_data["improvement_ratio"] or 0.0,
                        "expected_calibration_error": row_data["expected_calibration_error"],
                        "samples_evaluated": row_data["samples_evaluated"],
                        "calibration_version": row_data["calibration_version"],
                        "evaluated_at": row_data["evaluated_at"],
                    }
                )

            # Count total evaluations
            count_query = "SELECT COUNT(*) FROM calibration_evaluations"
            count_params: list[Any] = []
            if source is not None:
                count_query += " WHERE source = ?"
                count_params.append(source)

            count_cursor = await db.execute(count_query, count_params)
            count_row = await count_cursor.fetchone()
            total_count = int(count_row[0]) if count_row else 0

            return {
                "ok": True,
                "action": "get_evaluations",
                "evaluations": evaluations,
                "total_count": total_count,
                "filter_source": source,
                "filter_since": since,
                "returned_count": len(evaluations),
            }

        else:
            return {
                "ok": False,
                "error": "INVALID_PARAMS",
                "message": f"Unknown action: {action}. Valid actions: get_stats, get_evaluations",
            }

    except Exception as e:
        logger.error("calibration_metrics_action failed", action=action, error=str(e))
        return {
            "ok": False,
            "error": "INTERNAL_ERROR",
            "message": str(e),
        }
