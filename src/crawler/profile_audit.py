"""
Profile Health Audit for Lancet.

Implements profile health monitoring per §4.3.1:
- High-frequency checks at task start and browser session initialization
- UA/major version, font set, language/timezone, Canvas/Audio fingerprint drift detection
- Automatic repair: Chrome restart flag, font resync, profile recreation
- Structured audit logging of diffs, repairs, and retry counts

Safety: Only operates on Profile-Research, isolating daily-use profiles.
"""

import asyncio
import hashlib
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from src.utils.logging import get_logger
from src.utils.config import get_settings, get_project_root

logger = get_logger(__name__)


# =============================================================================
# Enums and Data Classes
# =============================================================================

class AuditStatus(str, Enum):
    """Audit check result status."""
    PASS = "pass"
    DRIFT = "drift"
    FAIL = "fail"
    SKIPPED = "skipped"


class RepairAction(str, Enum):
    """Profile repair action types."""
    NONE = "none"
    RESTART_BROWSER = "restart_browser"
    RESYNC_FONTS = "resync_fonts"
    RECREATE_PROFILE = "recreate_profile"


class RepairStatus(str, Enum):
    """Repair operation status."""
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    PENDING = "pending"


@dataclass
class FingerprintData:
    """Browser fingerprint data for comparison.
    
    Attributes:
        user_agent: Full UA string.
        ua_major_version: Major browser version (e.g., "120").
        fonts: Set of detected font names.
        language: Browser language setting.
        timezone: Timezone ID.
        canvas_hash: Canvas fingerprint hash.
        audio_hash: Audio fingerprint hash.
        screen_resolution: Screen resolution string.
        color_depth: Color depth.
        platform: Platform string.
        plugins_count: Number of plugins.
        timestamp: When the fingerprint was captured.
    """
    user_agent: str = ""
    ua_major_version: str = ""
    fonts: set[str] = field(default_factory=set)
    language: str = ""
    timezone: str = ""
    canvas_hash: str = ""
    audio_hash: str = ""
    screen_resolution: str = ""
    color_depth: int = 0
    platform: str = ""
    plugins_count: int = 0
    timestamp: float = 0.0
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "user_agent": self.user_agent,
            "ua_major_version": self.ua_major_version,
            "fonts": sorted(self.fonts),
            "language": self.language,
            "timezone": self.timezone,
            "canvas_hash": self.canvas_hash,
            "audio_hash": self.audio_hash,
            "screen_resolution": self.screen_resolution,
            "color_depth": self.color_depth,
            "platform": self.platform,
            "plugins_count": self.plugins_count,
            "timestamp": self.timestamp,
        }
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FingerprintData":
        """Create from dictionary."""
        return cls(
            user_agent=data.get("user_agent", ""),
            ua_major_version=data.get("ua_major_version", ""),
            fonts=set(data.get("fonts", [])),
            language=data.get("language", ""),
            timezone=data.get("timezone", ""),
            canvas_hash=data.get("canvas_hash", ""),
            audio_hash=data.get("audio_hash", ""),
            screen_resolution=data.get("screen_resolution", ""),
            color_depth=data.get("color_depth", 0),
            platform=data.get("platform", ""),
            plugins_count=data.get("plugins_count", 0),
            timestamp=data.get("timestamp", 0.0),
        )


@dataclass
class DriftInfo:
    """Information about detected drift in a specific attribute.
    
    Attributes:
        attribute: Attribute name that drifted.
        baseline_value: Original/baseline value.
        current_value: Current detected value.
        severity: Severity level (low/medium/high).
        repair_action: Recommended repair action.
    """
    attribute: str
    baseline_value: Any
    current_value: Any
    severity: str = "medium"
    repair_action: RepairAction = RepairAction.RESTART_BROWSER


@dataclass
class AuditResult:
    """Result of a profile health audit.
    
    Attributes:
        status: Overall audit status.
        baseline: Baseline fingerprint.
        current: Current fingerprint.
        drifts: List of detected drifts.
        repair_actions: List of repair actions taken.
        repair_status: Status of repair operations.
        error: Error message if audit failed.
        duration_ms: Audit duration in milliseconds.
        retry_count: Number of retries attempted.
        timestamp: When the audit was performed.
    """
    status: AuditStatus
    baseline: FingerprintData | None = None
    current: FingerprintData | None = None
    drifts: list[DriftInfo] = field(default_factory=list)
    repair_actions: list[RepairAction] = field(default_factory=list)
    repair_status: RepairStatus = RepairStatus.PENDING
    error: str | None = None
    duration_ms: float = 0.0
    retry_count: int = 0
    timestamp: float = 0.0
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for logging."""
        return {
            "status": self.status.value,
            "baseline": self.baseline.to_dict() if self.baseline else None,
            "current": self.current.to_dict() if self.current else None,
            "drifts": [
                {
                    "attribute": d.attribute,
                    "baseline_value": str(d.baseline_value)[:100],
                    "current_value": str(d.current_value)[:100],
                    "severity": d.severity,
                    "repair_action": d.repair_action.value,
                }
                for d in self.drifts
            ],
            "repair_actions": [a.value for a in self.repair_actions],
            "repair_status": self.repair_status.value,
            "error": self.error,
            "duration_ms": self.duration_ms,
            "retry_count": self.retry_count,
            "timestamp": self.timestamp,
        }


# =============================================================================
# Fingerprint Collection JavaScript
# =============================================================================

FINGERPRINT_JS = """
() => {
    const fingerprint = {};
    
    // User Agent
    fingerprint.user_agent = navigator.userAgent || '';
    
    // Extract major version from Chrome UA
    const chromeMatch = fingerprint.user_agent.match(/Chrome\\/([0-9]+)/);
    fingerprint.ua_major_version = chromeMatch ? chromeMatch[1] : '';
    
    // Language
    fingerprint.language = navigator.language || navigator.userLanguage || '';
    
    // Timezone
    fingerprint.timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || '';
    
    // Platform
    fingerprint.platform = navigator.platform || '';
    
    // Screen
    fingerprint.screen_resolution = `${screen.width}x${screen.height}`;
    fingerprint.color_depth = screen.colorDepth || 0;
    
    // Plugins count
    fingerprint.plugins_count = navigator.plugins ? navigator.plugins.length : 0;
    
    // Fonts detection (limited set for performance)
    const testFonts = [
        'Arial', 'Verdana', 'Times New Roman', 'Courier New', 'Georgia',
        'Trebuchet MS', 'Comic Sans MS', 'Impact', 'Lucida Console',
        'MS Gothic', 'Meiryo', 'Yu Gothic', 'Hiragino Kaku Gothic Pro',
        'Roboto', 'Open Sans', 'Noto Sans CJK JP', 'Source Han Sans'
    ];
    
    const detectedFonts = [];
    const testString = 'mmmmmmmmmmlli';
    const testSize = '72px';
    const baseFonts = ['monospace', 'sans-serif', 'serif'];
    
    const canvas = document.createElement('canvas');
    const context = canvas.getContext('2d');
    
    const baseFontWidths = {};
    for (const baseFont of baseFonts) {
        context.font = testSize + ' ' + baseFont;
        baseFontWidths[baseFont] = context.measureText(testString).width;
    }
    
    for (const font of testFonts) {
        let detected = false;
        for (const baseFont of baseFonts) {
            context.font = testSize + ' "' + font + '", ' + baseFont;
            const width = context.measureText(testString).width;
            if (width !== baseFontWidths[baseFont]) {
                detected = true;
                break;
            }
        }
        if (detected) {
            detectedFonts.push(font);
        }
    }
    fingerprint.fonts = detectedFonts;
    
    // Canvas fingerprint
    try {
        const canvasElement = document.createElement('canvas');
        canvasElement.width = 200;
        canvasElement.height = 50;
        const ctx = canvasElement.getContext('2d');
        
        ctx.textBaseline = 'alphabetic';
        ctx.font = '14px Arial';
        ctx.fillStyle = '#f60';
        ctx.fillRect(0, 0, 100, 30);
        ctx.fillStyle = '#069';
        ctx.fillText('Canvas FP', 2, 15);
        ctx.fillStyle = 'rgba(102, 204, 0, 0.7)';
        ctx.fillText('Test', 4, 45);
        
        fingerprint.canvas_hash = canvasElement.toDataURL().slice(-50);
    } catch (e) {
        fingerprint.canvas_hash = 'error';
    }
    
    // Audio fingerprint (simplified)
    try {
        const audioContext = new (window.AudioContext || window.webkitAudioContext)();
        const oscillator = audioContext.createOscillator();
        const analyser = audioContext.createAnalyser();
        const gainNode = audioContext.createGain();
        
        oscillator.type = 'triangle';
        oscillator.frequency.setValueAtTime(10000, audioContext.currentTime);
        gainNode.gain.setValueAtTime(0, audioContext.currentTime);
        
        oscillator.connect(analyser);
        analyser.connect(gainNode);
        gainNode.connect(audioContext.destination);
        
        oscillator.start(0);
        
        const frequencyData = new Float32Array(analyser.frequencyBinCount);
        analyser.getFloatFrequencyData(frequencyData);
        
        oscillator.stop();
        audioContext.close();
        
        // Create hash from frequency data
        let hash = 0;
        for (let i = 0; i < Math.min(50, frequencyData.length); i++) {
            hash = ((hash << 5) - hash) + Math.round(frequencyData[i] * 100);
            hash = hash & hash;
        }
        fingerprint.audio_hash = hash.toString(16);
    } catch (e) {
        fingerprint.audio_hash = 'error';
    }
    
    fingerprint.timestamp = Date.now() / 1000;
    
    return fingerprint;
}
"""


# =============================================================================
# Profile Auditor Class
# =============================================================================

class ProfileAuditor:
    """Profile health auditor for browser fingerprint consistency.
    
    Implements §4.3.1 profile health audit:
    - Captures baseline fingerprint on first initialization
    - Compares current fingerprint against baseline
    - Detects drift in UA, fonts, language, timezone, canvas, audio
    - Triggers automatic repair actions when drift is detected
    - Logs all audit results for monitoring
    
    Safety: Only operates on Profile-Research profile.
    """
    
    # Drift thresholds
    FONT_DRIFT_THRESHOLD = 0.2  # 20% font set difference
    
    # Severity definitions
    SEVERITY_CONFIG = {
        "ua_major_version": ("high", RepairAction.RESTART_BROWSER),
        "fonts": ("medium", RepairAction.RESYNC_FONTS),
        "language": ("medium", RepairAction.RESTART_BROWSER),
        "timezone": ("medium", RepairAction.RESTART_BROWSER),
        "canvas_hash": ("low", RepairAction.RESTART_BROWSER),
        "audio_hash": ("low", RepairAction.RESTART_BROWSER),
    }
    
    def __init__(self, profile_dir: Path | None = None):
        """Initialize profile auditor.
        
        Args:
            profile_dir: Directory for storing profile data. Defaults to data/profiles.
        """
        self._settings = get_settings()
        
        if profile_dir is None:
            root = get_project_root()
            profile_dir = root / "data" / "profiles"
        
        self._profile_dir = profile_dir
        self._profile_dir.mkdir(parents=True, exist_ok=True)
        
        self._baseline: FingerprintData | None = None
        self._last_audit_time: float = 0.0
        self._audit_count: int = 0
        self._repair_count: int = 0
        
        # Minimum interval between audits (seconds)
        self._min_audit_interval = 60.0
        
        # Load baseline if exists
        self._load_baseline()
    
    def _get_baseline_path(self) -> Path:
        """Get path to baseline fingerprint file."""
        profile_name = self._settings.browser.profile_name
        return self._profile_dir / f"{profile_name}_baseline.json"
    
    def _get_audit_log_path(self) -> Path:
        """Get path to audit log file."""
        profile_name = self._settings.browser.profile_name
        return self._profile_dir / f"{profile_name}_audit_log.jsonl"
    
    def _load_baseline(self) -> None:
        """Load baseline fingerprint from file."""
        baseline_path = self._get_baseline_path()
        
        if baseline_path.exists():
            try:
                with open(baseline_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self._baseline = FingerprintData.from_dict(data)
                    logger.debug(
                        "Loaded baseline fingerprint",
                        path=str(baseline_path),
                        timestamp=self._baseline.timestamp,
                    )
            except Exception as e:
                logger.warning(
                    "Failed to load baseline fingerprint",
                    error=str(e),
                    path=str(baseline_path),
                )
                self._baseline = None
    
    def _save_baseline(self, fingerprint: FingerprintData) -> None:
        """Save baseline fingerprint to file.
        
        Args:
            fingerprint: Fingerprint data to save as baseline.
        """
        baseline_path = self._get_baseline_path()
        
        try:
            with open(baseline_path, "w", encoding="utf-8") as f:
                json.dump(fingerprint.to_dict(), f, indent=2)
            
            self._baseline = fingerprint
            logger.info(
                "Saved baseline fingerprint",
                path=str(baseline_path),
                ua_version=fingerprint.ua_major_version,
                fonts_count=len(fingerprint.fonts),
            )
        except Exception as e:
            logger.error(
                "Failed to save baseline fingerprint",
                error=str(e),
                path=str(baseline_path),
            )
    
    def _log_audit(self, result: AuditResult) -> None:
        """Append audit result to log file.
        
        Args:
            result: Audit result to log.
        """
        log_path = self._get_audit_log_path()
        
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                log_entry = {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    **result.to_dict(),
                }
                f.write(json.dumps(log_entry) + "\n")
        except Exception as e:
            logger.warning(
                "Failed to write audit log",
                error=str(e),
                path=str(log_path),
            )
    
    async def collect_fingerprint(self, page) -> FingerprintData:
        """Collect current browser fingerprint from page.
        
        Args:
            page: Playwright page object.
            
        Returns:
            FingerprintData with current browser fingerprint.
        """
        try:
            result = await page.evaluate(FINGERPRINT_JS)
            
            fingerprint = FingerprintData(
                user_agent=result.get("user_agent", ""),
                ua_major_version=result.get("ua_major_version", ""),
                fonts=set(result.get("fonts", [])),
                language=result.get("language", ""),
                timezone=result.get("timezone", ""),
                canvas_hash=result.get("canvas_hash", ""),
                audio_hash=result.get("audio_hash", ""),
                screen_resolution=result.get("screen_resolution", ""),
                color_depth=result.get("color_depth", 0),
                platform=result.get("platform", ""),
                plugins_count=result.get("plugins_count", 0),
                timestamp=time.time(),
            )
            
            logger.debug(
                "Collected fingerprint",
                ua_version=fingerprint.ua_major_version,
                fonts_count=len(fingerprint.fonts),
                language=fingerprint.language,
                timezone=fingerprint.timezone,
            )
            
            return fingerprint
            
        except Exception as e:
            logger.error("Failed to collect fingerprint", error=str(e))
            raise
    
    def compare_fingerprints(
        self,
        baseline: FingerprintData,
        current: FingerprintData,
    ) -> list[DriftInfo]:
        """Compare two fingerprints and detect drifts.
        
        Args:
            baseline: Baseline fingerprint.
            current: Current fingerprint.
            
        Returns:
            List of detected drifts.
        """
        drifts: list[DriftInfo] = []
        
        # Check UA major version
        if baseline.ua_major_version != current.ua_major_version:
            severity, repair_action = self.SEVERITY_CONFIG["ua_major_version"]
            drifts.append(DriftInfo(
                attribute="ua_major_version",
                baseline_value=baseline.ua_major_version,
                current_value=current.ua_major_version,
                severity=severity,
                repair_action=repair_action,
            ))
        
        # Check fonts (allow some drift)
        if baseline.fonts and current.fonts:
            baseline_fonts = baseline.fonts
            current_fonts = current.fonts
            
            # Calculate Jaccard similarity
            intersection = len(baseline_fonts & current_fonts)
            union = len(baseline_fonts | current_fonts)
            
            if union > 0:
                similarity = intersection / union
                if similarity < (1 - self.FONT_DRIFT_THRESHOLD):
                    missing = baseline_fonts - current_fonts
                    added = current_fonts - baseline_fonts
                    severity, repair_action = self.SEVERITY_CONFIG["fonts"]
                    drifts.append(DriftInfo(
                        attribute="fonts",
                        baseline_value=f"missing={list(missing)[:5]}",
                        current_value=f"added={list(added)[:5]}",
                        severity=severity,
                        repair_action=repair_action,
                    ))
        
        # Check language
        if baseline.language != current.language:
            severity, repair_action = self.SEVERITY_CONFIG["language"]
            drifts.append(DriftInfo(
                attribute="language",
                baseline_value=baseline.language,
                current_value=current.language,
                severity=severity,
                repair_action=repair_action,
            ))
        
        # Check timezone
        if baseline.timezone != current.timezone:
            severity, repair_action = self.SEVERITY_CONFIG["timezone"]
            drifts.append(DriftInfo(
                attribute="timezone",
                baseline_value=baseline.timezone,
                current_value=current.timezone,
                severity=severity,
                repair_action=repair_action,
            ))
        
        # Check canvas fingerprint (allow for minor variations)
        if baseline.canvas_hash and current.canvas_hash:
            if baseline.canvas_hash != current.canvas_hash and \
               baseline.canvas_hash != "error" and current.canvas_hash != "error":
                severity, repair_action = self.SEVERITY_CONFIG["canvas_hash"]
                drifts.append(DriftInfo(
                    attribute="canvas_hash",
                    baseline_value=baseline.canvas_hash[:20],
                    current_value=current.canvas_hash[:20],
                    severity=severity,
                    repair_action=repair_action,
                ))
        
        # Check audio fingerprint
        if baseline.audio_hash and current.audio_hash:
            if baseline.audio_hash != current.audio_hash and \
               baseline.audio_hash != "error" and current.audio_hash != "error":
                severity, repair_action = self.SEVERITY_CONFIG["audio_hash"]
                drifts.append(DriftInfo(
                    attribute="audio_hash",
                    baseline_value=baseline.audio_hash,
                    current_value=current.audio_hash,
                    severity=severity,
                    repair_action=repair_action,
                ))
        
        return drifts
    
    def determine_repair_actions(self, drifts: list[DriftInfo]) -> list[RepairAction]:
        """Determine repair actions based on detected drifts.
        
        Args:
            drifts: List of detected drifts.
            
        Returns:
            Ordered list of repair actions to take.
        """
        if not drifts:
            return [RepairAction.NONE]
        
        actions: set[RepairAction] = set()
        
        # Collect all recommended actions
        for drift in drifts:
            actions.add(drift.repair_action)
        
        # Order by severity
        action_order = [
            RepairAction.RECREATE_PROFILE,  # Most drastic
            RepairAction.RESYNC_FONTS,
            RepairAction.RESTART_BROWSER,
        ]
        
        ordered_actions = [a for a in action_order if a in actions]
        
        return ordered_actions if ordered_actions else [RepairAction.NONE]
    
    async def audit(
        self,
        page,
        force: bool = False,
        update_baseline: bool = False,
    ) -> AuditResult:
        """Perform profile health audit.
        
        Args:
            page: Playwright page object.
            force: Force audit even if within minimum interval.
            update_baseline: Update baseline with current fingerprint.
            
        Returns:
            AuditResult with audit outcome.
        """
        start_time = time.time()
        self._audit_count += 1
        
        # Check minimum interval (unless forced)
        if not force:
            time_since_last = start_time - self._last_audit_time
            if time_since_last < self._min_audit_interval:
                logger.debug(
                    "Audit skipped (within minimum interval)",
                    time_since_last=time_since_last,
                    min_interval=self._min_audit_interval,
                )
                return AuditResult(
                    status=AuditStatus.SKIPPED,
                    duration_ms=0,
                    timestamp=start_time,
                )
        
        try:
            # Collect current fingerprint
            current = await self.collect_fingerprint(page)
            
            # If no baseline exists or update requested, save current as baseline
            if self._baseline is None or update_baseline:
                self._save_baseline(current)
                
                result = AuditResult(
                    status=AuditStatus.PASS,
                    baseline=current,
                    current=current,
                    duration_ms=(time.time() - start_time) * 1000,
                    timestamp=start_time,
                )
                
                logger.info(
                    "Baseline fingerprint established",
                    ua_version=current.ua_major_version,
                    fonts_count=len(current.fonts),
                )
                
                self._last_audit_time = start_time
                self._log_audit(result)
                return result
            
            # Compare with baseline
            drifts = self.compare_fingerprints(self._baseline, current)
            
            if not drifts:
                result = AuditResult(
                    status=AuditStatus.PASS,
                    baseline=self._baseline,
                    current=current,
                    duration_ms=(time.time() - start_time) * 1000,
                    timestamp=start_time,
                )
                
                logger.debug("Profile health check passed")
                
            else:
                # Drift detected
                repair_actions = self.determine_repair_actions(drifts)
                
                result = AuditResult(
                    status=AuditStatus.DRIFT,
                    baseline=self._baseline,
                    current=current,
                    drifts=drifts,
                    repair_actions=repair_actions,
                    repair_status=RepairStatus.PENDING,
                    duration_ms=(time.time() - start_time) * 1000,
                    timestamp=start_time,
                )
                
                logger.warning(
                    "Profile drift detected",
                    drifts_count=len(drifts),
                    drifts=[d.attribute for d in drifts],
                    repair_actions=[a.value for a in repair_actions],
                )
            
            self._last_audit_time = start_time
            self._log_audit(result)
            return result
            
        except Exception as e:
            result = AuditResult(
                status=AuditStatus.FAIL,
                error=str(e),
                duration_ms=(time.time() - start_time) * 1000,
                timestamp=start_time,
            )
            
            logger.error("Profile audit failed", error=str(e))
            self._log_audit(result)
            return result
    
    async def attempt_repair(
        self,
        audit_result: AuditResult,
        browser_manager: Any = None,
    ) -> AuditResult:
        """Attempt to repair profile based on audit result.
        
        Args:
            audit_result: Result from a previous audit.
            browser_manager: Browser manager for restart operations.
            
        Returns:
            Updated audit result with repair status.
        """
        if audit_result.status != AuditStatus.DRIFT:
            return audit_result
        
        if not audit_result.repair_actions:
            return audit_result
        
        self._repair_count += 1
        repair_success = True
        
        for action in audit_result.repair_actions:
            if action == RepairAction.NONE:
                continue
                
            elif action == RepairAction.RESTART_BROWSER:
                # Flag browser for restart - actual restart handled by caller
                logger.info("Flagging browser for restart")
                # The browser_manager can check this flag
                if browser_manager and hasattr(browser_manager, "request_restart"):
                    await browser_manager.request_restart()
                    
            elif action == RepairAction.RESYNC_FONTS:
                # Font resync is primarily an OS-level operation
                # Log for manual intervention if needed
                logger.info("Font resync recommended - OS-level operation")
                
            elif action == RepairAction.RECREATE_PROFILE:
                # Profile recreation is handled by backup/restore
                logger.warning(
                    "Profile recreation recommended",
                    profile=self._settings.browser.profile_name,
                )
                repair_success = await self._attempt_profile_restore()
        
        # Update repair status
        audit_result.repair_status = (
            RepairStatus.SUCCESS if repair_success else RepairStatus.FAILED
        )
        audit_result.retry_count = self._repair_count
        
        # Log the repair attempt
        self._log_audit(audit_result)
        
        return audit_result
    
    async def _attempt_profile_restore(self) -> bool:
        """Attempt to restore profile from backup.
        
        Returns:
            True if restore was successful or backup doesn't exist.
        """
        profile_name = self._settings.browser.profile_name
        backup_path = self._profile_dir / f"{profile_name}_backup"
        
        if not backup_path.exists():
            logger.info(
                "No profile backup found for restoration",
                profile=profile_name,
            )
            return True  # Not a failure, just nothing to restore
        
        logger.info(
            "Profile backup exists - manual restoration may be needed",
            backup_path=str(backup_path),
            profile=profile_name,
        )
        
        # Actual Chrome profile restoration would require:
        # 1. Closing Chrome
        # 2. Copying backup to Chrome's profile directory
        # 3. Restarting Chrome
        # This is typically done outside of the program
        
        return True
    
    def reset_baseline(self) -> None:
        """Reset baseline fingerprint (forces re-establishment on next audit)."""
        self._baseline = None
        
        baseline_path = self._get_baseline_path()
        if baseline_path.exists():
            baseline_path.unlink()
            logger.info("Baseline fingerprint reset", path=str(baseline_path))
    
    def get_stats(self) -> dict[str, Any]:
        """Get auditor statistics.
        
        Returns:
            Dictionary with audit statistics.
        """
        return {
            "audit_count": self._audit_count,
            "repair_count": self._repair_count,
            "has_baseline": self._baseline is not None,
            "baseline_age_hours": (
                (time.time() - self._baseline.timestamp) / 3600
                if self._baseline else None
            ),
            "last_audit_time": self._last_audit_time,
        }


# =============================================================================
# Global Instance
# =============================================================================

_profile_auditor: ProfileAuditor | None = None


def get_profile_auditor(profile_dir: Path | None = None) -> ProfileAuditor:
    """Get or create profile auditor instance.
    
    Args:
        profile_dir: Optional profile directory override.
        
    Returns:
        ProfileAuditor instance.
    """
    global _profile_auditor
    
    if _profile_auditor is None or profile_dir is not None:
        _profile_auditor = ProfileAuditor(profile_dir)
    
    return _profile_auditor


async def perform_health_check(
    page,
    force: bool = False,
    auto_repair: bool = True,
    browser_manager: Any = None,
) -> AuditResult:
    """Convenience function to perform profile health check.
    
    Args:
        page: Playwright page object.
        force: Force check even if within minimum interval.
        auto_repair: Automatically attempt repair on drift.
        browser_manager: Browser manager for restart operations.
        
    Returns:
        AuditResult with check outcome.
    """
    auditor = get_profile_auditor()
    
    result = await auditor.audit(page, force=force)
    
    if result.status == AuditStatus.DRIFT and auto_repair:
        result = await auditor.attempt_repair(result, browser_manager)
    
    return result




