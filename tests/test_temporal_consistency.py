"""
Unit tests for Temporal Consistency Checker .

Tests the temporal consistency validation functionality including:
- Date extraction from text and metadata
- Claim vs page date consistency checking
- Trust decay for stale claims
- Temporal impossibility detection

## Test Perspectives Table
| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---------|----------------------|---------------------------------------|-----------------|-------|
| TC-CL-01 | ConsistencyLevel values | Equivalence – enum | All levels defined | - |
| TC-DE-01 | Extract ISO date | Equivalence – ISO | Date extracted | - |
| TC-DE-02 | Extract Japanese date | Equivalence – Japanese | Date extracted | - |
| TC-DE-03 | Extract relative date | Equivalence – relative | Date calculated | - |
| TC-DE-04 | No date in text | Boundary – none | Empty extraction | - |
| TC-DE-05 | Multiple dates | Equivalence – multiple | All dates extracted | - |
| TC-CC-01 | Consistent dates | Equivalence – consistent | level=CONSISTENT | - |
| TC-CC-02 | Stale claim | Equivalence – stale | level=STALE | - |
| TC-CC-03 | Impossible timeline | Equivalence – impossible | level=IMPOSSIBLE | - |
| TC-CC-04 | Future claim | Boundary – future | level=SUSPICIOUS | - |
| TC-TD-01 | Apply decay 30 days | Equivalence – 30d | Confidence reduced | - |
| TC-TD-02 | Apply decay 365 days | Equivalence – 1y | Higher reduction | - |
| TC-TD-03 | No decay for fresh | Boundary – fresh | Confidence unchanged | - |
| TC-CF-01 | get_temporal_checker | Equivalence – singleton | Returns checker | - |
| TC-CF-02 | check_claim_consistency | Equivalence – convenience | Returns result | - |
"""

from typing import Any

import pytest

# All tests in this module are unit tests (no external dependencies)
pytestmark = pytest.mark.unit
# E402: Intentionally import after pytestmark for test configuration
from datetime import UTC, datetime

from src.filter.temporal_consistency import (
    ConsistencyLevel,
    ConsistencyResult,
    DateExtraction,
    DateExtractor,
    TemporalConsistencyChecker,
    apply_temporal_decay,
    check_claim_consistency,
    extract_dates_from_text,
    get_temporal_checker,
)

# =============================================================================
# DateExtraction Tests
# =============================================================================


class TestDateExtraction:
    """Tests for DateExtraction class."""

    def test_to_datetime_complete(self) -> None:
        """Complete date should convert to datetime."""
        extraction = DateExtraction(year=2024, month=6, day=15)
        dt = extraction.to_datetime()

        assert dt is not None
        assert dt.year == 2024
        assert dt.month == 6
        assert dt.day == 15

    def test_to_datetime_year_only(self) -> None:
        """Year-only date should default to January 1."""
        extraction = DateExtraction(year=2024)
        dt = extraction.to_datetime()

        assert dt is not None
        assert dt.year == 2024
        assert dt.month == 1
        assert dt.day == 1

    def test_to_datetime_no_year(self) -> None:
        """No year should return None."""
        extraction = DateExtraction(month=6, day=15)
        assert extraction.to_datetime() is None

    def test_is_complete(self) -> None:
        """is_complete should check all components."""
        complete = DateExtraction(year=2024, month=6, day=15)
        incomplete = DateExtraction(year=2024, month=6)
        year_only = DateExtraction(year=2024)

        assert complete.is_complete() is True
        assert incomplete.is_complete() is False
        assert year_only.is_complete() is False

    def test_to_dict(self) -> None:
        """to_dict should include all fields."""
        extraction = DateExtraction(
            year=2024,
            month=6,
            day=15,
            source="test",
            confidence=0.9,
        )

        d = extraction.to_dict()

        assert d["year"] == 2024
        assert d["month"] == 6
        assert d["day"] == 15
        assert d["source"] == "test"
        assert d["confidence"] == 0.9
        assert d["is_complete"] is True


# =============================================================================
# DateExtractor Tests
# =============================================================================


class TestDateExtractor:
    """Tests for DateExtractor class."""

    @pytest.fixture
    def extractor(self) -> DateExtractor:
        """Create DateExtractor instance."""
        return DateExtractor()

    def test_extract_iso_format(self, extractor: DateExtractor) -> None:
        """Should extract ISO format dates."""
        text = "This happened on 2024-06-15."
        dates = extractor.extract_from_text(text)

        assert len(dates) >= 1
        assert dates[0].year == 2024
        assert dates[0].month == 6
        assert dates[0].day == 15

    def test_extract_iso_format_slash(self, extractor: DateExtractor) -> None:
        """Should extract ISO format with slashes."""
        text = "Date: 2024/01/20"
        dates = extractor.extract_from_text(text)

        assert len(dates) >= 1
        assert dates[0].year == 2024
        assert dates[0].month == 1
        assert dates[0].day == 20

    def test_extract_japanese_format(self, extractor: DateExtractor) -> None:
        """Should extract Japanese date format."""
        text = "2024年6月15日に発表されました。"
        dates = extractor.extract_from_text(text)

        assert len(dates) >= 1
        assert dates[0].year == 2024
        assert dates[0].month == 6
        assert dates[0].day == 15

    def test_extract_year_only(self, extractor: DateExtractor) -> None:
        """Should extract year-only references."""
        text = "This was announced in 2024."
        dates = extractor.extract_from_text(text)

        assert len(dates) >= 1
        assert dates[0].year == 2024
        assert dates[0].month is None

    def test_extract_reiwa_era(self, extractor: DateExtractor) -> None:
        """Should extract Reiwa era dates."""
        text = "令和6年に施行された法律"
        dates = extractor.extract_from_text(text)

        assert len(dates) >= 1
        # Reiwa 6 = 2024
        assert dates[0].year == 2024

    def test_extract_multiple_dates(self, extractor: DateExtractor) -> None:
        """Should extract multiple dates from text."""
        text = "From 2020-01-01 to 2024-12-31."
        dates = extractor.extract_from_text(text)

        assert len(dates) >= 2
        years = {d.year for d in dates}
        assert 2020 in years
        assert 2024 in years

    def test_extract_empty_text(self, extractor: DateExtractor) -> None:
        """Should handle empty text."""
        dates = extractor.extract_from_text("")
        assert dates == []

    def test_extract_no_dates(self, extractor: DateExtractor) -> None:
        """Should handle text with no dates."""
        text = "This is a sentence without any dates."
        dates = extractor.extract_from_text(text)
        assert dates == []

    def test_extract_from_metadata_iso(self, extractor: DateExtractor) -> None:
        """Should extract from ISO metadata."""
        metadata = {"published_date": "2024-06-15T10:30:00Z"}
        extraction = extractor.extract_from_metadata(metadata)

        assert extraction is not None
        assert extraction.year == 2024
        assert extraction.month == 6
        assert extraction.day == 15
        assert extraction.confidence >= 0.95

    def test_extract_from_metadata_priority(self, extractor: DateExtractor) -> None:
        """Should prioritize published_date over modified_date."""
        metadata = {
            "published_date": "2023-01-01",
            "modified_date": "2024-06-15",
        }
        extraction = extractor.extract_from_metadata(metadata)

        assert extraction is not None
        assert extraction.year == 2023

    def test_extract_from_metadata_empty(self, extractor: DateExtractor) -> None:
        """Should handle empty metadata."""
        extraction = extractor.extract_from_metadata({})
        assert extraction is None

    def test_extract_from_metadata_fetched_at(self, extractor: DateExtractor) -> None:
        """Should fall back to fetched_at if no other dates."""
        metadata = {"fetched_at": "2024-06-15T12:00:00Z"}
        extraction = extractor.extract_from_metadata(metadata)

        assert extraction is not None
        assert extraction.year == 2024


# =============================================================================
# TemporalConsistencyChecker Tests
# =============================================================================


class TestTemporalConsistencyChecker:
    """Tests for TemporalConsistencyChecker class."""

    @pytest.fixture
    def checker(self) -> TemporalConsistencyChecker:
        """Create TemporalConsistencyChecker instance."""
        return TemporalConsistencyChecker(
            decay_rate_per_year=0.05,
            max_age_years=5,
            impossibility_threshold_days=7,
        )

    @pytest.fixture
    def current_time(self) -> datetime:
        """Fixed current time for testing."""
        return datetime(2024, 6, 15, tzinfo=UTC)

    def test_consistent_claim(
        self, checker: TemporalConsistencyChecker, current_time: datetime
    ) -> None:
        """Claim dated before page should be consistent."""
        claim_text = "This was announced in 2023."
        page_metadata = {"published_date": "2024-01-01"}

        result = checker.check_consistency(claim_text, page_metadata, current_time)

        assert result.level == ConsistencyLevel.CONSISTENT
        assert result.trust_decay > 0.9

    def test_inconsistent_claim_future_date(
        self, checker: TemporalConsistencyChecker, current_time: datetime
    ) -> None:
        """Claim referencing future event should be inconsistent."""
        claim_text = "This will happen in 2025-12-01."
        page_metadata = {"published_date": "2024-01-01"}

        result = checker.check_consistency(claim_text, page_metadata, current_time)

        assert result.level == ConsistencyLevel.INCONSISTENT
        assert "temporal impossibility" in result.reason.lower()

    def test_stale_claim(self, checker: TemporalConsistencyChecker, current_time: datetime) -> None:
        """Old claim should be marked as stale."""
        claim_text = "This happened in 2015."
        page_metadata = {"published_date": "2015-06-01"}

        result = checker.check_consistency(claim_text, page_metadata, current_time)

        assert result.level == ConsistencyLevel.STALE
        assert result.trust_decay < 0.8
        assert result.age_days is not None
        assert result.age_days > 365 * 5

    def test_uncertain_no_dates(
        self, checker: TemporalConsistencyChecker, current_time: datetime
    ) -> None:
        """Missing dates should result in uncertain."""
        claim_text = "This is a claim without any dates."
        page_metadata: dict[str, Any] = {}

        result = checker.check_consistency(claim_text, page_metadata, current_time)

        assert result.level == ConsistencyLevel.UNCERTAIN

    def test_trust_decay_calculation(self, checker: TemporalConsistencyChecker) -> None:
        """Trust decay should decrease with age."""
        decay_1_year = checker.calculate_trust_decay(365)
        decay_3_years = checker.calculate_trust_decay(365 * 3)
        decay_5_years = checker.calculate_trust_decay(365 * 5)

        assert decay_1_year > decay_3_years
        assert decay_3_years > decay_5_years
        assert decay_5_years > 0

    def test_trust_decay_zero_age(self, checker: TemporalConsistencyChecker) -> None:
        """Zero age should have no decay."""
        decay = checker.calculate_trust_decay(0)
        assert decay == 1.0

    def test_batch_check(self, checker: TemporalConsistencyChecker, current_time: datetime) -> None:
        """Should check multiple claims at once."""
        claims = [
            {"text": "Event in 2023"},
            {"text": "Event in 2010"},  # Old enough to be stale (>5 years from page date)
        ]
        # Use older page date so 2010 claim is stale relative to current_time
        page_metadata = {"published_date": "2010-01-01"}

        results = checker.batch_check(claims, page_metadata, current_time)

        assert len(results) == 2
        # 2023 claim is after 2010 page date, so inconsistent
        assert results[0].level == ConsistencyLevel.INCONSISTENT
        # 2010 claim matches page date but is stale relative to current_time (2024)
        assert results[1].level == ConsistencyLevel.STALE

    def test_batch_check_no_dates(
        self, checker: TemporalConsistencyChecker, current_time: datetime
    ) -> None:
        """Should handle claims with no dates."""
        claims = [
            {"text": "No date mentioned"},
        ]
        # No page metadata either
        page_metadata: dict[str, Any] = {}

        results = checker.batch_check(claims, page_metadata, current_time)

        assert len(results) == 1
        assert results[0].level == ConsistencyLevel.UNCERTAIN

    def test_get_consistency_stats(self, checker: TemporalConsistencyChecker) -> None:
        """Should calculate statistics from results."""
        results = [
            ConsistencyResult(level=ConsistencyLevel.CONSISTENT, trust_decay=1.0),
            ConsistencyResult(level=ConsistencyLevel.CONSISTENT, trust_decay=0.95),
            ConsistencyResult(level=ConsistencyLevel.STALE, trust_decay=0.7),
            ConsistencyResult(level=ConsistencyLevel.UNCERTAIN),
        ]

        stats = checker.get_consistency_stats(results)

        assert stats["total"] == 4
        assert stats["consistent"] == 2
        assert stats["stale"] == 1
        assert stats["uncertain"] == 1
        assert stats["inconsistent"] == 0
        assert stats["consistency_rate"] == 0.5

    def test_get_consistency_stats_empty(self, checker: TemporalConsistencyChecker) -> None:
        """Should handle empty results."""
        stats = checker.get_consistency_stats([])

        assert stats["total"] == 0
        assert stats["consistency_rate"] == 0.0


# =============================================================================
# ConsistencyResult Tests
# =============================================================================


class TestConsistencyResult:
    """Tests for ConsistencyResult class."""

    def test_to_dict(self) -> None:
        """to_dict should include all fields."""
        result = ConsistencyResult(
            level=ConsistencyLevel.CONSISTENT,
            claim_date=DateExtraction(year=2024, month=6, day=15),
            page_date=DateExtraction(year=2024, month=1, day=1),
            age_days=165,
            trust_decay=0.95,
            reason="Test reason",
            details={"key": "value"},
        )

        d = result.to_dict()

        assert d["level"] == "consistent"
        assert d["claim_date"]["year"] == 2024
        assert d["page_date"]["year"] == 2024
        assert d["age_days"] == 165
        assert d["trust_decay"] == 0.95
        assert d["reason"] == "Test reason"
        assert d["details"]["key"] == "value"


# =============================================================================
# Convenience Function Tests
# =============================================================================


class TestConvenienceFunctions:
    """Tests for module-level convenience functions."""

    def test_get_temporal_checker_singleton(self) -> None:
        """get_temporal_checker should return singleton."""
        checker1 = get_temporal_checker()
        checker2 = get_temporal_checker()

        assert checker1 is checker2

    def test_check_claim_consistency(self) -> None:
        """check_claim_consistency should work."""
        result = check_claim_consistency(
            "Event in 2023",
            {"published_date": "2024-01-01"},
        )

        assert result.level == ConsistencyLevel.CONSISTENT

    def test_apply_temporal_decay_consistent(self) -> None:
        """apply_temporal_decay should not heavily penalize consistent claims."""
        confidence, result = apply_temporal_decay(
            0.8,
            "Event in 2023",
            {"published_date": "2024-01-01"},
        )

        assert confidence > 0.7
        assert result.level == ConsistencyLevel.CONSISTENT

    def test_apply_temporal_decay_inconsistent(self) -> None:
        """apply_temporal_decay should heavily penalize inconsistent claims."""
        confidence, result = apply_temporal_decay(
            0.8,
            "Event in 2025-12-01",
            {"published_date": "2024-01-01"},
        )

        assert confidence < 0.3
        assert result.level == ConsistencyLevel.INCONSISTENT

    def test_apply_temporal_decay_stale(self) -> None:
        """apply_temporal_decay should moderately penalize stale claims."""
        confidence, result = apply_temporal_decay(
            0.8,
            "Event in 2015",
            {"published_date": "2015-01-01"},
        )

        assert confidence < 0.7
        assert result.level == ConsistencyLevel.STALE

    def test_extract_dates_from_text(self) -> None:
        """extract_dates_from_text should work."""
        dates = extract_dates_from_text("This happened on 2024-06-15.")

        assert len(dates) >= 1
        assert dates[0].year == 2024


# =============================================================================
# Edge Case Tests
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    @pytest.fixture
    def checker(self) -> TemporalConsistencyChecker:
        """Create TemporalConsistencyChecker instance."""
        return TemporalConsistencyChecker()

    def test_invalid_date_values(self, checker: TemporalConsistencyChecker) -> None:
        """Should handle invalid date values gracefully."""
        claim_text = "Event on 2024-13-45"  # Invalid month/day
        page_metadata = {"published_date": "2024-01-01"}

        # Should not raise exception, return valid result
        result = checker.check_consistency(claim_text, page_metadata)
        assert isinstance(
            result, ConsistencyResult
        ), f"Expected ConsistencyResult, got {type(result)}"

    def test_very_old_date(self, checker: TemporalConsistencyChecker) -> None:
        """Should handle very old dates."""
        claim_text = "Historical event in 1800"
        page_metadata = {"published_date": "2024-01-01"}

        result = checker.check_consistency(claim_text, page_metadata)
        # 1800 is not matched by our patterns (20\d{2})
        assert isinstance(
            result, ConsistencyResult
        ), f"Expected ConsistencyResult, got {type(result)}"

    def test_future_page_date(self, checker: TemporalConsistencyChecker) -> None:
        """Should handle future page dates."""
        claim_text = "Event in 2024"
        page_metadata = {"published_date": "2025-01-01"}
        current_time = datetime(2024, 6, 15, tzinfo=UTC)

        result = checker.check_consistency(claim_text, page_metadata, current_time)
        assert isinstance(
            result, ConsistencyResult
        ), f"Expected ConsistencyResult, got {type(result)}"

    def test_same_date_claim_and_page(self, checker: TemporalConsistencyChecker) -> None:
        """Should handle same date for claim and page."""
        claim_text = "Event on 2024-06-15"
        page_metadata = {"published_date": "2024-06-15"}

        result = checker.check_consistency(claim_text, page_metadata)
        assert result.level == ConsistencyLevel.CONSISTENT

    def test_claim_just_after_page(self, checker: TemporalConsistencyChecker) -> None:
        """Should allow small buffer for timezone issues."""
        # Claim is 3 days after page (within 7-day buffer)
        claim_text = "Event on 2024-06-18"
        page_metadata = {"published_date": "2024-06-15"}

        result = checker.check_consistency(claim_text, page_metadata)
        # Should be consistent due to buffer
        assert result.level == ConsistencyLevel.CONSISTENT

    def test_unicode_text(self, checker: TemporalConsistencyChecker) -> None:
        """Should handle unicode text."""
        claim_text = "令和6年6月15日の発表"
        page_metadata = {"published_date": "2024-07-01"}

        result = checker.check_consistency(claim_text, page_metadata)
        assert isinstance(
            result, ConsistencyResult
        ), f"Expected ConsistencyResult, got {type(result)}"
        # Japanese era year should be parsed as 2024
        assert result.claim_date is not None, "Expected claim_date for Japanese era text"

    def test_mixed_languages(self, checker: TemporalConsistencyChecker) -> None:
        """Should handle mixed language text."""
        claim_text = "On 2024年6月15日, the announcement was made."
        page_metadata = {"published_date": "2024-07-01"}

        result = checker.check_consistency(claim_text, page_metadata)
        assert isinstance(
            result, ConsistencyResult
        ), f"Expected ConsistencyResult, got {type(result)}"


# =============================================================================
# Integration-like Tests
# =============================================================================


class TestIntegrationScenarios:
    """Tests for realistic usage scenarios."""

    @pytest.fixture
    def checker(self) -> TemporalConsistencyChecker:
        """Create TemporalConsistencyChecker instance."""
        return TemporalConsistencyChecker()

    def test_news_article_scenario(self, checker: TemporalConsistencyChecker) -> None:
        """Simulate checking a news article claim."""
        claim_text = "The company announced layoffs in January 2024."
        page_metadata = {
            "published_date": "2024-02-15T10:00:00Z",
            "title": "Tech Company Layoffs Analysis",
            "domain": "example.com",
        }
        current_time = datetime(2024, 6, 15, tzinfo=UTC)

        result = checker.check_consistency(claim_text, page_metadata, current_time)

        assert result.level == ConsistencyLevel.CONSISTENT
        assert result.claim_date is not None
        assert result.page_date is not None

    def test_outdated_research_scenario(self, checker: TemporalConsistencyChecker) -> None:
        """Simulate checking an outdated research claim."""
        claim_text = "According to the 2018 study, the population was 10 million."
        page_metadata = {
            "published_date": "2018-06-01",
            "title": "Population Statistics",
        }
        current_time = datetime(2024, 6, 15, tzinfo=UTC)

        result = checker.check_consistency(claim_text, page_metadata, current_time)

        assert result.level == ConsistencyLevel.STALE
        assert result.age_days is not None
        assert result.age_days > 365 * 5
        assert result.trust_decay < 0.8

    def test_prediction_claim_scenario(self, checker: TemporalConsistencyChecker) -> None:
        """Simulate checking a prediction claim (future date)."""
        claim_text = "The product will launch in December 2025."
        page_metadata = {
            "published_date": "2024-01-15",
            "title": "Product Roadmap",
        }
        current_time = datetime(2024, 6, 15, tzinfo=UTC)

        result = checker.check_consistency(claim_text, page_metadata, current_time)

        # Prediction about future should be flagged as inconsistent
        # because the claim date (2025) is after page date (2024-01)
        assert result.level == ConsistencyLevel.INCONSISTENT

    def test_multiple_claims_from_same_source(self, checker: TemporalConsistencyChecker) -> None:
        """Simulate checking multiple claims from one source."""
        claims = [
            {"text": "The company was founded in 2020."},
            {"text": "Revenue reached $1B in 2023."},
            {"text": "Projected growth for 2026 is 50%."},
        ]
        page_metadata = {"published_date": "2024-01-01"}
        current_time = datetime(2024, 6, 15, tzinfo=UTC)

        results = checker.batch_check(claims, page_metadata, current_time)

        assert len(results) == 3
        # First two should be consistent (dates before page date)
        assert results[0].level == ConsistencyLevel.CONSISTENT
        assert results[1].level == ConsistencyLevel.CONSISTENT
        # Third (2026) should be inconsistent (future prediction in past article)
        assert results[2].level == ConsistencyLevel.INCONSISTENT
