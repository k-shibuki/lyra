"""
Tests for profile health audit (§4.3.1).

Tests cover:
- Fingerprint collection and comparison
- Drift detection for various attributes
- Repair action determination
- Baseline management
- Audit logging

## Test Perspectives Table
| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---------|----------------------|---------------------------------------|-----------------|-------|
| TC-FP-01 | FingerprintData creation | Equivalence – normal | All fields stored | - |
| TC-FP-02 | FingerprintData serialization | Equivalence – to_dict | Dictionary with all fields | - |
| TC-FP-03 | FingerprintData deserialization | Equivalence – from_dict | Object correctly populated | - |
| TC-FP-04 | Compare identical fingerprints | Boundary – same | No drift detected | - |
| TC-FP-05 | Compare with UA drift | Equivalence – detection | UA drift detected | - |
| TC-FP-06 | Compare with font drift | Equivalence – detection | Font drift detected | - |
| TC-FP-07 | Compare with canvas drift | Equivalence – detection | Canvas drift detected | - |
| TC-PA-01 | Audit healthy profile | Equivalence – healthy | AuditStatus.HEALTHY | - |
| TC-PA-02 | Audit with minor drift | Equivalence – warning | AuditStatus.WARNING | - |
| TC-PA-03 | Audit with major drift | Equivalence – critical | AuditStatus.CRITICAL | - |
| TC-PA-04 | Determine repair actions | Equivalence – repairs | Correct actions returned | - |
| TC-PA-05 | Execute repair | Equivalence – execution | Repair applied | - |
| TC-BL-01 | Save baseline | Equivalence – persistence | Baseline saved to file | - |
| TC-BL-02 | Load baseline | Equivalence – loading | Baseline loaded from file | - |
| TC-BL-03 | Update baseline | Equivalence – mutation | Baseline updated | - |
| TC-CF-01 | get_profile_auditor | Equivalence – singleton | Returns auditor instance | - |
| TC-CF-02 | perform_health_check | Equivalence – convenience | Returns audit result | - |
"""

import json

import pytest

# All tests in this module are unit tests (no external dependencies)
pytestmark = pytest.mark.unit
# E402: Intentionally import after pytestmark for test configuration
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

from src.crawler.profile_audit import (
    AuditResult,
    AuditStatus,
    DriftInfo,
    FingerprintData,
    ProfileAuditor,
    RepairAction,
    RepairStatus,
    perform_health_check,
)

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def sample_fingerprint() -> FingerprintData:
    """Create a sample fingerprint for testing."""
    return FingerprintData(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        ua_major_version="120",
        fonts={"Arial", "Verdana", "Times New Roman", "Meiryo"},
        language="ja-JP",
        timezone="Asia/Tokyo",
        canvas_hash="abc123def456",
        audio_hash="789xyz",
        screen_resolution="1920x1080",
        color_depth=24,
        platform="Win32",
        plugins_count=3,
        timestamp=time.time(),
    )


@pytest.fixture
def drifted_fingerprint(sample_fingerprint: FingerprintData) -> FingerprintData:
    """Create a fingerprint with UA version drift."""
    return FingerprintData(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        ua_major_version="121",  # Changed from 120
        fonts=sample_fingerprint.fonts,
        language=sample_fingerprint.language,
        timezone=sample_fingerprint.timezone,
        canvas_hash=sample_fingerprint.canvas_hash,
        audio_hash=sample_fingerprint.audio_hash,
        screen_resolution=sample_fingerprint.screen_resolution,
        color_depth=sample_fingerprint.color_depth,
        platform=sample_fingerprint.platform,
        plugins_count=sample_fingerprint.plugins_count,
        timestamp=time.time(),
    )


@pytest.fixture
def auditor(tmp_path: Path) -> ProfileAuditor:
    """Create a ProfileAuditor with temporary directory."""
    return ProfileAuditor(profile_dir=tmp_path)


@pytest.fixture
def mock_page() -> AsyncMock:
    """Create a mock Playwright page."""
    page = AsyncMock()
    page.evaluate = AsyncMock()
    page.goto = AsyncMock()
    page.close = AsyncMock()
    return page


# =============================================================================
# FingerprintData Tests
# =============================================================================


class TestFingerprintData:
    """Tests for FingerprintData dataclass."""

    def test_to_dict(self, sample_fingerprint: FingerprintData) -> None:
        """Test serialization to dictionary."""
        data = sample_fingerprint.to_dict()

        assert data["user_agent"] == sample_fingerprint.user_agent
        assert data["ua_major_version"] == "120"
        assert "Arial" in data["fonts"]
        assert data["language"] == "ja-JP"
        assert data["timezone"] == "Asia/Tokyo"

    def test_from_dict(self, sample_fingerprint: FingerprintData) -> None:
        """Test deserialization from dictionary."""
        data = sample_fingerprint.to_dict()
        restored = FingerprintData.from_dict(data)

        assert restored.user_agent == sample_fingerprint.user_agent
        assert restored.ua_major_version == sample_fingerprint.ua_major_version
        assert restored.fonts == sample_fingerprint.fonts
        assert restored.language == sample_fingerprint.language

    def test_fonts_sorted_in_dict(self, sample_fingerprint: FingerprintData) -> None:
        """Test that fonts are sorted when serialized."""
        data = sample_fingerprint.to_dict()

        # Should be sorted alphabetically
        assert data["fonts"] == sorted(sample_fingerprint.fonts)

    def test_empty_fingerprint(self) -> None:
        """Test default empty fingerprint."""
        fp = FingerprintData()

        assert fp.user_agent == ""
        assert fp.fonts == set()
        assert fp.timestamp == 0.0


# =============================================================================
# Drift Detection Tests
# =============================================================================


class TestDriftDetection:
    """Tests for drift detection logic."""

    def test_no_drift_identical_fingerprints(
        self,
        auditor: ProfileAuditor,
        sample_fingerprint: FingerprintData,
    ) -> None:
        """Test that identical fingerprints show no drift."""
        drifts = auditor.compare_fingerprints(
            sample_fingerprint,
            sample_fingerprint,
        )

        assert len(drifts) == 0

    def test_ua_version_drift(
        self,
        auditor: ProfileAuditor,
        sample_fingerprint: FingerprintData,
        drifted_fingerprint: FingerprintData,
    ) -> None:
        """Test UA major version drift detection."""
        drifts = auditor.compare_fingerprints(
            sample_fingerprint,
            drifted_fingerprint,
        )

        assert len(drifts) == 1
        assert drifts[0].attribute == "ua_major_version"
        assert drifts[0].baseline_value == "120"
        assert drifts[0].current_value == "121"
        assert drifts[0].severity == "high"
        assert drifts[0].repair_action == RepairAction.RESTART_BROWSER

    def test_language_drift(
        self,
        auditor: ProfileAuditor,
        sample_fingerprint: FingerprintData,
    ) -> None:
        """Test language drift detection."""
        changed = FingerprintData(
            user_agent=sample_fingerprint.user_agent,
            ua_major_version=sample_fingerprint.ua_major_version,
            fonts=sample_fingerprint.fonts,
            language="en-US",  # Changed
            timezone=sample_fingerprint.timezone,
            canvas_hash=sample_fingerprint.canvas_hash,
            audio_hash=sample_fingerprint.audio_hash,
            timestamp=time.time(),
        )

        drifts = auditor.compare_fingerprints(sample_fingerprint, changed)

        assert len(drifts) == 1
        assert drifts[0].attribute == "language"
        assert drifts[0].baseline_value == "ja-JP"
        assert drifts[0].current_value == "en-US"

    def test_timezone_drift(
        self,
        auditor: ProfileAuditor,
        sample_fingerprint: FingerprintData,
    ) -> None:
        """Test timezone drift detection."""
        changed = FingerprintData(
            user_agent=sample_fingerprint.user_agent,
            ua_major_version=sample_fingerprint.ua_major_version,
            fonts=sample_fingerprint.fonts,
            language=sample_fingerprint.language,
            timezone="America/New_York",  # Changed
            canvas_hash=sample_fingerprint.canvas_hash,
            audio_hash=sample_fingerprint.audio_hash,
            timestamp=time.time(),
        )

        drifts = auditor.compare_fingerprints(sample_fingerprint, changed)

        assert len(drifts) == 1
        assert drifts[0].attribute == "timezone"

    def test_font_drift_significant(
        self,
        auditor: ProfileAuditor,
        sample_fingerprint: FingerprintData,
    ) -> None:
        """Test significant font set drift detection (>20% difference)."""
        # Remove most fonts (significant drift)
        changed = FingerprintData(
            user_agent=sample_fingerprint.user_agent,
            ua_major_version=sample_fingerprint.ua_major_version,
            fonts={"Arial"},  # Only 1 of 4 fonts
            language=sample_fingerprint.language,
            timezone=sample_fingerprint.timezone,
            canvas_hash=sample_fingerprint.canvas_hash,
            audio_hash=sample_fingerprint.audio_hash,
            timestamp=time.time(),
        )

        drifts = auditor.compare_fingerprints(sample_fingerprint, changed)

        font_drifts = [d for d in drifts if d.attribute == "fonts"]
        assert len(font_drifts) == 1
        assert font_drifts[0].repair_action == RepairAction.RESYNC_FONTS

    def test_font_drift_minor_allowed(
        self,
        auditor: ProfileAuditor,
        sample_fingerprint: FingerprintData,
    ) -> None:
        """Test that minor font differences are tolerated (<20%)."""
        # Add one font (minor change, <20% difference)
        changed = FingerprintData(
            user_agent=sample_fingerprint.user_agent,
            ua_major_version=sample_fingerprint.ua_major_version,
            fonts=sample_fingerprint.fonts | {"NewFont"},  # 5 fonts, 4 overlap
            language=sample_fingerprint.language,
            timezone=sample_fingerprint.timezone,
            canvas_hash=sample_fingerprint.canvas_hash,
            audio_hash=sample_fingerprint.audio_hash,
            timestamp=time.time(),
        )

        drifts = auditor.compare_fingerprints(sample_fingerprint, changed)

        # Should not detect drift since overlap is > 80%
        font_drifts = [d for d in drifts if d.attribute == "fonts"]
        assert len(font_drifts) == 0

    def test_canvas_hash_drift(
        self,
        auditor: ProfileAuditor,
        sample_fingerprint: FingerprintData,
    ) -> None:
        """Test canvas fingerprint drift detection."""
        changed = FingerprintData(
            user_agent=sample_fingerprint.user_agent,
            ua_major_version=sample_fingerprint.ua_major_version,
            fonts=sample_fingerprint.fonts,
            language=sample_fingerprint.language,
            timezone=sample_fingerprint.timezone,
            canvas_hash="different_hash",  # Changed
            audio_hash=sample_fingerprint.audio_hash,
            timestamp=time.time(),
        )

        drifts = auditor.compare_fingerprints(sample_fingerprint, changed)

        assert len(drifts) == 1
        assert drifts[0].attribute == "canvas_hash"
        assert drifts[0].severity == "low"

    def test_multiple_drifts(
        self,
        auditor: ProfileAuditor,
        sample_fingerprint: FingerprintData,
    ) -> None:
        """Test detection of multiple simultaneous drifts."""
        changed = FingerprintData(
            user_agent="Mozilla/5.0 Chrome/121.0.0.0",
            ua_major_version="121",  # Changed
            fonts={"Arial"},  # Significant change
            language="en-US",  # Changed
            timezone="America/New_York",  # Changed
            canvas_hash="different",  # Changed
            audio_hash="different",  # Changed
            timestamp=time.time(),
        )

        drifts = auditor.compare_fingerprints(sample_fingerprint, changed)

        # Should detect multiple drifts
        assert len(drifts) >= 4

        drift_attributes = {d.attribute for d in drifts}
        assert "ua_major_version" in drift_attributes
        assert "language" in drift_attributes
        assert "timezone" in drift_attributes


# =============================================================================
# Repair Action Tests
# =============================================================================


class TestRepairActions:
    """Tests for repair action determination."""

    def test_no_repair_for_no_drifts(self, auditor: ProfileAuditor) -> None:
        """Test that no repair is needed when no drifts exist."""
        actions = auditor.determine_repair_actions([])

        assert actions == [RepairAction.NONE]

    def test_restart_browser_for_ua_drift(self, auditor: ProfileAuditor) -> None:
        """Test browser restart is recommended for UA drift."""
        drifts = [
            DriftInfo(
                attribute="ua_major_version",
                baseline_value="120",
                current_value="121",
                severity="high",
                repair_action=RepairAction.RESTART_BROWSER,
            )
        ]

        actions = auditor.determine_repair_actions(drifts)

        assert RepairAction.RESTART_BROWSER in actions

    def test_resync_fonts_for_font_drift(self, auditor: ProfileAuditor) -> None:
        """Test font resync is recommended for font drift."""
        drifts = [
            DriftInfo(
                attribute="fonts",
                baseline_value="missing=[]",
                current_value="added=[]",
                severity="medium",
                repair_action=RepairAction.RESYNC_FONTS,
            )
        ]

        actions = auditor.determine_repair_actions(drifts)

        assert RepairAction.RESYNC_FONTS in actions

    def test_multiple_actions_ordered(self, auditor: ProfileAuditor) -> None:
        """Test that multiple repair actions are ordered by severity."""
        drifts = [
            DriftInfo(
                attribute="fonts",
                baseline_value="",
                current_value="",
                repair_action=RepairAction.RESYNC_FONTS,
            ),
            DriftInfo(
                attribute="ua_major_version",
                baseline_value="120",
                current_value="121",
                repair_action=RepairAction.RESTART_BROWSER,
            ),
        ]

        actions = auditor.determine_repair_actions(drifts)

        # RESYNC_FONTS comes before RESTART_BROWSER in severity order
        assert len(actions) == 2
        assert actions[0] == RepairAction.RESYNC_FONTS
        assert actions[1] == RepairAction.RESTART_BROWSER


# =============================================================================
# Baseline Management Tests
# =============================================================================


class TestBaselineManagement:
    """Tests for baseline fingerprint management."""

    def test_save_and_load_baseline(
        self,
        auditor: ProfileAuditor,
        sample_fingerprint: FingerprintData,
    ) -> None:
        """Test saving and loading baseline fingerprint."""
        auditor._save_baseline(sample_fingerprint)

        # Create new auditor instance to test loading
        new_auditor = ProfileAuditor(profile_dir=auditor._profile_dir)

        assert new_auditor._baseline is not None
        assert new_auditor._baseline.ua_major_version == "120"
        assert new_auditor._baseline.language == "ja-JP"

    def test_reset_baseline(
        self,
        auditor: ProfileAuditor,
        sample_fingerprint: FingerprintData,
    ) -> None:
        """Test resetting baseline fingerprint."""
        auditor._save_baseline(sample_fingerprint)
        assert auditor._baseline is not None

        auditor.reset_baseline()

        assert auditor._baseline is None
        assert not auditor._get_baseline_path().exists()

    def test_baseline_file_format(
        self,
        auditor: ProfileAuditor,
        sample_fingerprint: FingerprintData,
    ) -> None:
        """Test that baseline is saved as valid JSON."""
        auditor._save_baseline(sample_fingerprint)

        baseline_path = auditor._get_baseline_path()
        with open(baseline_path) as f:
            data = json.load(f)

        assert "user_agent" in data
        assert "ua_major_version" in data
        assert "fonts" in data
        assert isinstance(data["fonts"], list)  # Fonts are stored as list


# =============================================================================
# Audit Execution Tests
# =============================================================================


class TestAuditExecution:
    """Tests for audit execution."""

    @pytest.mark.asyncio
    async def test_audit_establishes_baseline_on_first_run(
        self,
        auditor: ProfileAuditor,
        mock_page: AsyncMock,
    ) -> None:
        """Test that first audit establishes baseline."""
        mock_page.evaluate.return_value = {
            "user_agent": "Chrome/120",
            "ua_major_version": "120",
            "fonts": ["Arial"],
            "language": "ja-JP",
            "timezone": "Asia/Tokyo",
            "canvas_hash": "abc",
            "audio_hash": "xyz",
            "screen_resolution": "1920x1080",
            "color_depth": 24,
            "platform": "Win32",
            "plugins_count": 3,
            "timestamp": time.time(),
        }

        result = await auditor.audit(mock_page, force=True)

        assert result.status == AuditStatus.PASS
        assert auditor._baseline is not None
        assert auditor._baseline.ua_major_version == "120"

    @pytest.mark.asyncio
    async def test_audit_detects_drift_from_baseline(
        self,
        auditor: ProfileAuditor,
        mock_page: AsyncMock,
        sample_fingerprint: FingerprintData,
    ) -> None:
        """Test that audit detects drift from baseline."""
        # Set baseline
        auditor._save_baseline(sample_fingerprint)

        # Return different fingerprint
        mock_page.evaluate.return_value = {
            "user_agent": "Chrome/121",
            "ua_major_version": "121",  # Different
            "fonts": list(sample_fingerprint.fonts),
            "language": sample_fingerprint.language,
            "timezone": sample_fingerprint.timezone,
            "canvas_hash": sample_fingerprint.canvas_hash,
            "audio_hash": sample_fingerprint.audio_hash,
            "screen_resolution": "1920x1080",
            "color_depth": 24,
            "platform": "Win32",
            "plugins_count": 3,
            "timestamp": time.time(),
        }

        result = await auditor.audit(mock_page, force=True)

        assert result.status == AuditStatus.DRIFT
        assert len(result.drifts) >= 1
        assert result.drifts[0].attribute == "ua_major_version"

    @pytest.mark.asyncio
    async def test_audit_skipped_within_interval(
        self,
        auditor: ProfileAuditor,
        mock_page: AsyncMock,
        sample_fingerprint: FingerprintData,
    ) -> None:
        """Test that audit is skipped if called too quickly."""
        auditor._save_baseline(sample_fingerprint)
        auditor._last_audit_time = time.time()  # Just audited

        result = await auditor.audit(mock_page, force=False)

        assert result.status == AuditStatus.SKIPPED
        mock_page.evaluate.assert_not_called()

    @pytest.mark.asyncio
    async def test_audit_force_bypasses_interval(
        self,
        auditor: ProfileAuditor,
        mock_page: AsyncMock,
        sample_fingerprint: FingerprintData,
    ) -> None:
        """Test that force=True bypasses minimum interval."""
        auditor._save_baseline(sample_fingerprint)
        auditor._last_audit_time = time.time()  # Just audited

        mock_page.evaluate.return_value = sample_fingerprint.to_dict()

        result = await auditor.audit(mock_page, force=True)

        assert result.status in (AuditStatus.PASS, AuditStatus.DRIFT)
        mock_page.evaluate.assert_called_once()

    @pytest.mark.asyncio
    async def test_audit_handles_errors_gracefully(
        self,
        auditor: ProfileAuditor,
        mock_page: AsyncMock,
    ) -> None:
        """Test that audit handles errors without crashing."""
        mock_page.evaluate.side_effect = Exception("JavaScript error")

        result = await auditor.audit(mock_page, force=True)

        assert result.status == AuditStatus.FAIL
        assert result.error == "JavaScript error"


# =============================================================================
# Audit Logging Tests
# =============================================================================


class TestAuditLogging:
    """Tests for audit log functionality."""

    @pytest.mark.asyncio
    async def test_audit_logs_to_file(
        self,
        auditor: ProfileAuditor,
        mock_page: AsyncMock,
    ) -> None:
        """Test that audits are logged to file."""
        mock_page.evaluate.return_value = {
            "user_agent": "Chrome/120",
            "ua_major_version": "120",
            "fonts": ["Arial"],
            "language": "ja-JP",
            "timezone": "Asia/Tokyo",
            "canvas_hash": "abc",
            "audio_hash": "xyz",
            "timestamp": time.time(),
        }

        await auditor.audit(mock_page, force=True)

        log_path = auditor._get_audit_log_path()
        assert log_path.exists()

        with open(log_path) as f:
            lines = f.readlines()

        assert len(lines) == 1
        log_entry = json.loads(lines[0])
        assert "timestamp" in log_entry
        assert "status" in log_entry

    @pytest.mark.asyncio
    async def test_multiple_audits_append_to_log(
        self,
        auditor: ProfileAuditor,
        mock_page: AsyncMock,
    ) -> None:
        """Test that multiple audits append to log file."""
        mock_page.evaluate.return_value = {
            "user_agent": "Chrome/120",
            "ua_major_version": "120",
            "fonts": ["Arial"],
            "language": "ja-JP",
            "timezone": "Asia/Tokyo",
            "canvas_hash": "abc",
            "audio_hash": "xyz",
            "timestamp": time.time(),
        }

        await auditor.audit(mock_page, force=True)
        auditor._last_audit_time = 0  # Reset for next audit
        await auditor.audit(mock_page, force=True)

        log_path = auditor._get_audit_log_path()
        with open(log_path) as f:
            lines = f.readlines()

        assert len(lines) == 2


# =============================================================================
# Statistics Tests
# =============================================================================


class TestAuditorStats:
    """Tests for auditor statistics."""

    @pytest.mark.asyncio
    async def test_stats_track_audit_count(
        self,
        auditor: ProfileAuditor,
        mock_page: AsyncMock,
    ) -> None:
        """Test that stats track audit count."""
        mock_page.evaluate.return_value = {
            "user_agent": "Chrome/120",
            "ua_major_version": "120",
            "fonts": [],
            "language": "ja-JP",
            "timezone": "Asia/Tokyo",
            "timestamp": time.time(),
        }

        await auditor.audit(mock_page, force=True)

        stats = auditor.get_stats()
        assert stats["audit_count"] == 1
        assert stats["has_baseline"] is True

    def test_stats_initial_state(self, auditor: ProfileAuditor) -> None:
        """Test initial stats state."""
        stats = auditor.get_stats()

        assert stats["audit_count"] == 0
        assert stats["repair_count"] == 0
        assert stats["has_baseline"] is False
        assert stats["baseline_age_hours"] is None


# =============================================================================
# Integration Tests
# =============================================================================


class TestPerformHealthCheck:
    """Tests for the convenience function."""

    @pytest.mark.asyncio
    async def test_perform_health_check_function(
        self, mock_page: AsyncMock, tmp_path: Path
    ) -> None:
        """Test the perform_health_check convenience function."""
        with patch("src.crawler.profile_audit._profile_auditor", None):
            with patch("src.crawler.profile_audit.get_profile_auditor") as mock_get:
                auditor = ProfileAuditor(profile_dir=tmp_path)
                mock_get.return_value = auditor

                mock_page.evaluate.return_value = {
                    "user_agent": "Chrome/120",
                    "ua_major_version": "120",
                    "fonts": [],
                    "language": "ja-JP",
                    "timezone": "Asia/Tokyo",
                    "timestamp": time.time(),
                }

                result = await perform_health_check(
                    page=mock_page,
                    force=True,
                    auto_repair=False,
                )

                assert result.status == AuditStatus.PASS


# =============================================================================
# AuditResult Tests
# =============================================================================


class TestAuditResult:
    """Tests for AuditResult serialization."""

    def test_audit_result_to_dict(self, sample_fingerprint: FingerprintData) -> None:
        """Test AuditResult serialization."""
        result = AuditResult(
            status=AuditStatus.DRIFT,
            baseline=sample_fingerprint,
            current=sample_fingerprint,
            drifts=[
                DriftInfo(
                    attribute="ua_major_version",
                    baseline_value="120",
                    current_value="121",
                    severity="high",
                    repair_action=RepairAction.RESTART_BROWSER,
                )
            ],
            repair_actions=[RepairAction.RESTART_BROWSER],
            repair_status=RepairStatus.SUCCESS,
            error=None,
            duration_ms=100.5,
            retry_count=1,
            timestamp=time.time(),
        )

        data = result.to_dict()

        assert data["status"] == "drift"
        assert len(data["drifts"]) == 1
        assert data["drifts"][0]["attribute"] == "ua_major_version"
        assert data["repair_status"] == "success"
        assert data["retry_count"] == 1
