"""
Content extraction module for Lancet.

Provides HTML/PDF content extraction with OCR support,
page type classification, and content quality analysis.
"""

from src.extractor.content import extract_content, ocr_image
from src.extractor.page_classifier import (
    ClassificationResult,
    PageClassifier,
    PageFeatures,
    PageType,
    classify_page,
    get_classifier,
)
from src.extractor.quality_analyzer import (
    ContentQualityAnalyzer,
    QualityFeatures,
    QualityIssue,
    QualityResult,
    analyze_content_quality,
    get_quality_analyzer,
)

__all__ = [
    # Content extraction
    "extract_content",
    "ocr_image",
    # Page classification
    "PageType",
    "PageFeatures",
    "ClassificationResult",
    "PageClassifier",
    "classify_page",
    "get_classifier",
    # Quality analysis
    "QualityIssue",
    "QualityFeatures",
    "QualityResult",
    "ContentQualityAnalyzer",
    "analyze_content_quality",
    "get_quality_analyzer",
]




