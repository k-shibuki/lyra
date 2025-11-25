"""
Temporal Consistency Checker for Lancet.

Implements §3.3.3 requirement for temporal consistency validation:
- Claim timestamp vs page update date consistency check
- Trust decay for stale claims
- Timestamp integrity verification

This module ensures that claims are temporally consistent with their sources,
detecting cases where claims reference events that occurred after the source
was published (temporal impossibility) or where claims are significantly
outdated relative to current knowledge.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Any, Optional

from src.utils.logging import get_logger

logger = get_logger(__name__)


# =============================================================================
# Constants
# =============================================================================

# Trust decay rates for stale claims (per year)
DEFAULT_DECAY_RATE_PER_YEAR = 0.05  # 5% decay per year

# Maximum age before significant decay applies
MAX_CLAIM_AGE_YEARS = 5

# Threshold for temporal impossibility (claim mentions future event)
TEMPORAL_IMPOSSIBILITY_THRESHOLD_DAYS = 7  # Allow 7 days buffer for timezone issues

# Date extraction patterns
DATE_PATTERNS = [
    # ISO format: 2024-01-15, 2024/01/15
    r'(\d{4})[/-](\d{1,2})[/-](\d{1,2})',
    # Japanese format: 2024年1月15日
    r'(\d{4})年(\d{1,2})月(\d{1,2})日',
    # Month name format: January 15, 2024 or 15 January 2024
    r'(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),?\s+(\d{4})',
    r'(\d{1,2})\s+(?:January|February|March|April|May|June|July|August|September|October|November|December),?\s+(\d{4})',
    # Abbreviated month: Jan 15, 2024
    r'(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+(\d{1,2}),?\s+(\d{4})',
    # Year only: 2024, 令和6年
    r'\b(20\d{2})\b',
    r'令和(\d+)年',
    r'平成(\d+)年',
]

MONTH_MAP = {
    'january': 1, 'february': 2, 'march': 3, 'april': 4,
    'may': 5, 'june': 6, 'july': 7, 'august': 8,
    'september': 9, 'october': 10, 'november': 11, 'december': 12,
    'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4,
    'jun': 6, 'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12,
}


class ConsistencyLevel(str, Enum):
    """Temporal consistency level."""
    CONSISTENT = "consistent"  # Claim timestamp <= page date
    UNCERTAIN = "uncertain"  # Cannot determine (missing dates)
    STALE = "stale"  # Claim is significantly older than current date
    INCONSISTENT = "inconsistent"  # Claim timestamp > page date (temporal impossibility)


@dataclass
class DateExtraction:
    """Extracted date information."""
    year: Optional[int] = None
    month: Optional[int] = None
    day: Optional[int] = None
    source: str = ""  # Where the date was extracted from
    confidence: float = 0.5  # Confidence in extraction
    
    def to_datetime(self) -> Optional[datetime]:
        """Convert to datetime object.
        
        Returns:
            datetime object or None if insufficient data.
        """
        if self.year is None:
            return None
        
        try:
            return datetime(
                year=self.year,
                month=self.month or 1,
                day=self.day or 1,
                tzinfo=timezone.utc,
            )
        except (ValueError, OverflowError):
            return None
    
    def is_complete(self) -> bool:
        """Check if date has year, month, and day.
        
        Returns:
            True if all components are present.
        """
        return all([self.year, self.month, self.day])
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary.
        
        Returns:
            Dictionary representation.
        """
        return {
            "year": self.year,
            "month": self.month,
            "day": self.day,
            "source": self.source,
            "confidence": self.confidence,
            "is_complete": self.is_complete(),
        }


@dataclass
class ConsistencyResult:
    """Result of temporal consistency check."""
    level: ConsistencyLevel
    claim_date: Optional[DateExtraction] = None
    page_date: Optional[DateExtraction] = None
    age_days: Optional[int] = None  # Age of claim in days
    trust_decay: float = 1.0  # Trust decay factor (1.0 = no decay)
    reason: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary.
        
        Returns:
            Dictionary representation.
        """
        return {
            "level": self.level.value,
            "claim_date": self.claim_date.to_dict() if self.claim_date else None,
            "page_date": self.page_date.to_dict() if self.page_date else None,
            "age_days": self.age_days,
            "trust_decay": round(self.trust_decay, 4),
            "reason": self.reason,
            "details": self.details,
        }


# =============================================================================
# Date Extraction
# =============================================================================

class DateExtractor:
    """Extracts dates from text and metadata."""
    
    def __init__(self):
        """Initialize date extractor."""
        self._compiled_patterns = [
            (re.compile(pattern, re.IGNORECASE), pattern)
            for pattern in DATE_PATTERNS
        ]
    
    def extract_from_text(self, text: str) -> list[DateExtraction]:
        """Extract dates from text content.
        
        Args:
            text: Text to extract dates from.
            
        Returns:
            List of extracted dates, ordered by confidence.
        """
        if not text:
            return []
        
        extractions = []
        
        for compiled, pattern in self._compiled_patterns:
            for match in compiled.finditer(text):
                extraction = self._parse_match(match, pattern)
                if extraction and extraction.year:
                    extractions.append(extraction)
        
        # Remove duplicates and sort by confidence
        seen = set()
        unique = []
        for e in extractions:
            key = (e.year, e.month, e.day)
            if key not in seen:
                seen.add(key)
                unique.append(e)
        
        return sorted(unique, key=lambda x: x.confidence, reverse=True)
    
    def _parse_match(
        self,
        match: re.Match,
        pattern: str,
    ) -> Optional[DateExtraction]:
        """Parse a regex match into DateExtraction.
        
        Args:
            match: Regex match object.
            pattern: Original pattern string.
            
        Returns:
            DateExtraction or None.
        """
        groups = match.groups()
        
        try:
            # ISO format: YYYY-MM-DD
            if 'YYYY' in pattern or r'(\d{4})[/-]' in pattern:
                if len(groups) >= 3:
                    return DateExtraction(
                        year=int(groups[0]),
                        month=int(groups[1]),
                        day=int(groups[2]),
                        source="iso_format",
                        confidence=0.95,
                    )
            
            # Japanese format: YYYY年MM月DD日
            if '年' in pattern and '月' in pattern:
                if len(groups) >= 3:
                    return DateExtraction(
                        year=int(groups[0]),
                        month=int(groups[1]),
                        day=int(groups[2]),
                        source="japanese_format",
                        confidence=0.95,
                    )
            
            # Month name formats
            if 'January|February' in pattern or 'Jan|Feb' in pattern:
                matched_text = match.group(0).lower()
                for month_name, month_num in MONTH_MAP.items():
                    if month_name in matched_text:
                        # Find year and day in groups
                        nums = [int(g) for g in groups if g and g.isdigit()]
                        if len(nums) >= 2:
                            year = max(nums)  # Year is usually larger
                            day = min(nums)
                            if year > 1900 and 1 <= day <= 31:
                                return DateExtraction(
                                    year=year,
                                    month=month_num,
                                    day=day,
                                    source="month_name_format",
                                    confidence=0.85,
                                )
                        break
            
            # Year only
            if r'\b(20\d{2})\b' in pattern:
                if groups:
                    year = int(groups[0])
                    if 2000 <= year <= 2100:
                        return DateExtraction(
                            year=year,
                            source="year_only",
                            confidence=0.5,
                        )
            
            # Japanese era: 令和, 平成
            if '令和' in pattern:
                era_year = int(groups[0])
                # 令和1年 = 2019年
                return DateExtraction(
                    year=2018 + era_year,
                    source="reiwa_era",
                    confidence=0.8,
                )
            
            if '平成' in pattern:
                era_year = int(groups[0])
                # 平成1年 = 1989年
                return DateExtraction(
                    year=1988 + era_year,
                    source="heisei_era",
                    confidence=0.8,
                )
                
        except (ValueError, IndexError, TypeError):
            pass
        
        return None
    
    def extract_from_metadata(
        self,
        metadata: dict[str, Any],
    ) -> Optional[DateExtraction]:
        """Extract date from page metadata.
        
        Args:
            metadata: Page metadata dictionary.
            
        Returns:
            DateExtraction or None.
        """
        # Priority order for metadata fields
        date_fields = [
            "published_date",
            "date_published",
            "datePublished",
            "article:published_time",
            "og:published_time",
            "date",
            "created_at",
            "modified_date",
            "date_modified",
            "dateModified",
            "last_modified",
            "lastModified",
            "fetched_at",
        ]
        
        for field_name in date_fields:
            value = metadata.get(field_name)
            if value:
                extraction = self._parse_date_string(str(value), field_name)
                if extraction:
                    return extraction
        
        return None
    
    def _parse_date_string(
        self,
        date_str: str,
        source: str,
    ) -> Optional[DateExtraction]:
        """Parse a date string.
        
        Args:
            date_str: Date string to parse.
            source: Source field name.
            
        Returns:
            DateExtraction or None.
        """
        if not date_str:
            return None
        
        # Try ISO format first
        try:
            dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
            return DateExtraction(
                year=dt.year,
                month=dt.month,
                day=dt.day,
                source=source,
                confidence=0.99,
            )
        except (ValueError, TypeError):
            pass
        
        # Try extracting from text
        extractions = self.extract_from_text(date_str)
        if extractions:
            result = extractions[0]
            result.source = source
            return result
        
        return None


# =============================================================================
# Temporal Consistency Checker
# =============================================================================

class TemporalConsistencyChecker:
    """Checks temporal consistency between claims and sources.
    
    Implements §3.3.3 requirements:
    - Detect claims that reference events after the source was published
    - Apply trust decay for stale claims
    - Validate timestamp integrity
    """
    
    def __init__(
        self,
        decay_rate_per_year: float = DEFAULT_DECAY_RATE_PER_YEAR,
        max_age_years: float = MAX_CLAIM_AGE_YEARS,
        impossibility_threshold_days: int = TEMPORAL_IMPOSSIBILITY_THRESHOLD_DAYS,
    ):
        """Initialize temporal consistency checker.
        
        Args:
            decay_rate_per_year: Trust decay rate per year.
            max_age_years: Maximum age before significant decay.
            impossibility_threshold_days: Buffer days for temporal impossibility.
        """
        self._extractor = DateExtractor()
        self._decay_rate = decay_rate_per_year
        self._max_age_years = max_age_years
        self._impossibility_threshold = timedelta(days=impossibility_threshold_days)
    
    def check_consistency(
        self,
        claim_text: str,
        page_metadata: dict[str, Any],
        current_time: Optional[datetime] = None,
    ) -> ConsistencyResult:
        """Check temporal consistency of a claim against its source.
        
        Args:
            claim_text: The claim text to check.
            page_metadata: Metadata of the source page.
            current_time: Current time for staleness check (default: now).
            
        Returns:
            ConsistencyResult with consistency level and details.
        """
        if current_time is None:
            current_time = datetime.now(timezone.utc)
        
        # Extract dates from claim text
        claim_dates = self._extractor.extract_from_text(claim_text)
        claim_date = claim_dates[0] if claim_dates else None
        
        # Extract date from page metadata
        page_date = self._extractor.extract_from_metadata(page_metadata)
        
        # If we can't extract any dates, return uncertain
        if not claim_date and not page_date:
            return ConsistencyResult(
                level=ConsistencyLevel.UNCERTAIN,
                reason="No dates could be extracted from claim or page",
            )
        
        # Convert to datetime for comparison
        claim_dt = claim_date.to_datetime() if claim_date else None
        page_dt = page_date.to_datetime() if page_date else None
        
        # Check for temporal impossibility
        if claim_dt and page_dt:
            if claim_dt > page_dt + self._impossibility_threshold:
                return ConsistencyResult(
                    level=ConsistencyLevel.INCONSISTENT,
                    claim_date=claim_date,
                    page_date=page_date,
                    reason="Claim references event after page publication (temporal impossibility)",
                    details={
                        "claim_datetime": claim_dt.isoformat(),
                        "page_datetime": page_dt.isoformat(),
                        "difference_days": (claim_dt - page_dt).days,
                    },
                )
        
        # Calculate age and staleness
        reference_date = page_dt or claim_dt
        if reference_date:
            age_days = (current_time - reference_date).days
            age_years = age_days / 365.25
            
            # Calculate trust decay
            if age_years > 0:
                # Exponential decay: trust = e^(-rate * years)
                # Simplified linear approximation for small rates
                decay = max(0.0, 1.0 - (self._decay_rate * min(age_years, self._max_age_years)))
            else:
                decay = 1.0
            
            # Determine if stale
            if age_years > self._max_age_years:
                return ConsistencyResult(
                    level=ConsistencyLevel.STALE,
                    claim_date=claim_date,
                    page_date=page_date,
                    age_days=age_days,
                    trust_decay=decay,
                    reason=f"Claim is significantly outdated ({age_years:.1f} years old)",
                    details={
                        "age_years": round(age_years, 2),
                        "max_age_years": self._max_age_years,
                    },
                )
            
            # Consistent
            return ConsistencyResult(
                level=ConsistencyLevel.CONSISTENT,
                claim_date=claim_date,
                page_date=page_date,
                age_days=age_days,
                trust_decay=decay,
                reason="Claim is temporally consistent with source",
            )
        
        # Uncertain (couldn't determine dates properly)
        return ConsistencyResult(
            level=ConsistencyLevel.UNCERTAIN,
            claim_date=claim_date,
            page_date=page_date,
            reason="Could not determine temporal relationship",
        )
    
    def calculate_trust_decay(
        self,
        age_days: int,
    ) -> float:
        """Calculate trust decay factor based on age.
        
        Args:
            age_days: Age in days.
            
        Returns:
            Trust decay factor (0.0 to 1.0).
        """
        if age_days <= 0:
            return 1.0
        
        age_years = age_days / 365.25
        decay = max(0.0, 1.0 - (self._decay_rate * min(age_years, self._max_age_years)))
        return decay
    
    def batch_check(
        self,
        claims: list[dict[str, Any]],
        page_metadata: dict[str, Any],
        current_time: Optional[datetime] = None,
    ) -> list[ConsistencyResult]:
        """Check temporal consistency for multiple claims.
        
        Args:
            claims: List of claim dictionaries with 'text' key.
            page_metadata: Source page metadata.
            current_time: Current time for staleness check.
            
        Returns:
            List of ConsistencyResult for each claim.
        """
        results = []
        
        for claim in claims:
            claim_text = claim.get("text", claim.get("claim_text", ""))
            result = self.check_consistency(claim_text, page_metadata, current_time)
            results.append(result)
        
        return results
    
    def get_consistency_stats(
        self,
        results: list[ConsistencyResult],
    ) -> dict[str, Any]:
        """Calculate statistics from consistency results.
        
        Args:
            results: List of ConsistencyResult.
            
        Returns:
            Statistics dictionary.
        """
        if not results:
            return {
                "total": 0,
                "consistent": 0,
                "uncertain": 0,
                "stale": 0,
                "inconsistent": 0,
                "consistency_rate": 0.0,
                "average_decay": 1.0,
            }
        
        counts = {level: 0 for level in ConsistencyLevel}
        total_decay = 0.0
        decay_count = 0
        
        for result in results:
            counts[result.level] += 1
            if result.trust_decay < 1.0:
                total_decay += result.trust_decay
                decay_count += 1
        
        total = len(results)
        consistent = counts[ConsistencyLevel.CONSISTENT]
        
        return {
            "total": total,
            "consistent": consistent,
            "uncertain": counts[ConsistencyLevel.UNCERTAIN],
            "stale": counts[ConsistencyLevel.STALE],
            "inconsistent": counts[ConsistencyLevel.INCONSISTENT],
            "consistency_rate": consistent / total if total > 0 else 0.0,
            "average_decay": total_decay / decay_count if decay_count > 0 else 1.0,
        }


# =============================================================================
# Convenience Functions
# =============================================================================

_checker: Optional[TemporalConsistencyChecker] = None


def get_temporal_checker() -> TemporalConsistencyChecker:
    """Get or create the global temporal consistency checker.
    
    Returns:
        TemporalConsistencyChecker instance.
    """
    global _checker
    if _checker is None:
        _checker = TemporalConsistencyChecker()
    return _checker


def check_claim_consistency(
    claim_text: str,
    page_metadata: dict[str, Any],
) -> ConsistencyResult:
    """Check temporal consistency of a claim.
    
    Args:
        claim_text: The claim text.
        page_metadata: Source page metadata.
        
    Returns:
        ConsistencyResult.
    """
    checker = get_temporal_checker()
    return checker.check_consistency(claim_text, page_metadata)


def apply_temporal_decay(
    confidence: float,
    claim_text: str,
    page_metadata: dict[str, Any],
) -> tuple[float, ConsistencyResult]:
    """Apply temporal decay to a confidence score.
    
    Args:
        confidence: Original confidence score.
        claim_text: The claim text.
        page_metadata: Source page metadata.
        
    Returns:
        Tuple of (adjusted_confidence, consistency_result).
    """
    checker = get_temporal_checker()
    result = checker.check_consistency(claim_text, page_metadata)
    
    # Apply decay to confidence
    adjusted = confidence * result.trust_decay
    
    # Additional penalty for inconsistent claims
    if result.level == ConsistencyLevel.INCONSISTENT:
        adjusted *= 0.3  # 70% additional penalty
    elif result.level == ConsistencyLevel.STALE:
        adjusted *= 0.8  # 20% additional penalty
    
    return adjusted, result


def extract_dates_from_text(text: str) -> list[DateExtraction]:
    """Extract dates from text.
    
    Args:
        text: Text to extract dates from.
        
    Returns:
        List of DateExtraction objects.
    """
    extractor = DateExtractor()
    return extractor.extract_from_text(text)

