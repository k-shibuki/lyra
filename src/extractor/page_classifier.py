"""
Page Type Classifier for Lyra.

Classifies web pages into types for extraction/traversal strategy selection.

Page Types (§3.1.2):
- article: News articles, blog posts, research papers
- knowledge: Wiki pages, documentation, manuals, FAQs
- notice: Official announcements, press releases, notices
- forum: Discussion boards, Q&A, comment threads
- login_wall: Pages requiring authentication
- index: Category pages, search results, listing pages

The classifier analyzes HTML structure, DOM patterns, and semantic cues
to determine the page type. This enables type-specific extraction and
traversal strategies.
"""

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from urllib.parse import urlparse

from src.utils.logging import get_logger

logger = get_logger(__name__)


class PageType(Enum):
    """Enumeration of page types for classification."""

    ARTICLE = "article"  # News articles, blog posts
    KNOWLEDGE = "knowledge"  # Wiki pages, documentation, FAQs
    NOTICE = "notice"  # Official announcements, press releases
    FORUM = "forum"  # Discussion boards, Q&A, comments
    LOGIN_WALL = "login_wall"  # Pages requiring authentication
    INDEX = "index"  # Category pages, search results, listings
    ACADEMIC = "academic"  # Research papers, academic journals
    REPORT = "report"  # Corporate reports, government reports, white papers
    LEGAL = "legal"  # Laws, regulations, court cases
    PRODUCT = "product"  # Product pages, specifications, manuals
    PROFILE = "profile"  # Person/company profiles
    OTHER = "other"  # Pages not fitting other categories


@dataclass
class ClassificationResult:
    """Result of page type classification."""

    page_type: PageType
    confidence: float  # 0.0 to 1.0
    features: dict[str, Any]
    reason: str


@dataclass
class PageFeatures:
    """Extracted features from HTML for classification."""

    # Structure features
    has_article_tag: bool = False
    has_main_tag: bool = False
    has_nav_tag: bool = False
    has_aside_tag: bool = False
    has_comments_section: bool = False

    # Content features
    heading_count: int = 0
    paragraph_count: int = 0
    link_count: int = 0
    list_item_count: int = 0
    form_count: int = 0
    input_count: int = 0

    # Text ratios
    text_to_html_ratio: float = 0.0
    link_density: float = 0.0

    # Semantic features
    has_breadcrumb: bool = False
    has_pagination: bool = False
    has_date: bool = False
    has_author: bool = False
    has_category: bool = False

    # Login/Auth indicators
    has_login_form: bool = False
    has_password_field: bool = False
    has_paywall_indicator: bool = False

    # Forum indicators
    has_reply_form: bool = False
    has_vote_buttons: bool = False
    has_user_avatars: bool = False
    has_thread_structure: bool = False

    # Wiki/Knowledge indicators
    has_toc: bool = False
    has_wiki_structure: bool = False
    has_edit_links: bool = False
    has_infobox: bool = False

    # Academic indicators
    has_abstract: bool = False
    has_citations: bool = False
    has_doi: bool = False
    has_academic_structure: bool = False

    # Report indicators
    has_executive_summary: bool = False
    has_financial_data: bool = False
    has_charts_tables: bool = False
    has_report_structure: bool = False

    # Legal indicators
    has_legal_structure: bool = False
    has_article_numbers: bool = False
    has_legal_citations: bool = False

    # Product indicators
    has_price: bool = False
    has_add_to_cart: bool = False
    has_specifications: bool = False
    has_product_gallery: bool = False

    # Profile indicators
    has_company_info: bool = False
    has_contact_info: bool = False
    has_team_section: bool = False
    has_about_section: bool = False

    # URL/meta hints
    url_hints: list[str] = field(default_factory=list)
    meta_og_type: str | None = None

    def __post_init__(self) -> None:
        pass


class PageClassifier:
    """Classifier for determining web page types."""

    # URL patterns that hint at page types
    URL_PATTERNS = {
        PageType.ARTICLE: [
            r"/news/",
            r"/article/",
            r"/blog/",
            r"/post/",
            r"/story/",
            r"/entry/",
            r"\d{4}/\d{2}/\d{2}/",
        ],
        PageType.KNOWLEDGE: [
            r"/wiki/",
            r"/docs/",
            r"/documentation/",
            r"/manual/",
            r"/faq/",
            r"/help/",
            r"/guide/",
            r"/reference/",
            r"/how-to/",
            r"/tutorial/",
        ],
        PageType.NOTICE: [
            r"/news/",
            r"/press/",
            r"/announcement/",
            r"/notice/",
            r"/release/",
            r"/update/",
            r"/info/",
            r"/oshirase/",
            r"/topics/",
        ],
        PageType.FORUM: [
            r"/forum/",
            r"/thread/",
            r"/topic/",
            r"/discussion/",
            r"/community/",
            r"/board/",
            r"/questions/",
            r"/answers/",
            r"/qa/",
        ],
        PageType.LOGIN_WALL: [
            r"/login",
            r"/signin",
            r"/auth/",
            r"/register",
            r"/signup",
            r"/member/",
        ],
        PageType.INDEX: [
            r"/category/",
            r"/tag/",
            r"/archive/",
            r"/search",
            r"/list/",
            r"/index",
            r"/page/\d+",
            r"\?page=",
        ],
        PageType.ACADEMIC: [
            r"arxiv\.org",
            r"pubmed",
            r"scholar\.google",
            r"/paper/",
            r"/publication/",
            r"/abstract/",
            r"jstage\.jst\.go\.jp",
            r"cinii\.ac\.jp",
            r"doi\.org",
            r"/journal/",
            r"/proceedings/",
        ],
        PageType.REPORT: [
            r"/report/",
            r"/ir/",
            r"/investor/",
            r"/annual-report",
            r"/whitepaper/",
            r"/white-paper/",
            r"edinet",
            r"/disclosure/",
            r"/yuho/",
            r"/policy/",
            r"/statistics/",
        ],
        PageType.LEGAL: [
            r"/law/",
            r"/legal/",
            r"/regulation/",
            r"/statute/",
            r"/ordinance/",
            r"/judgment/",
            r"e-gov\.go\.jp",
            r"courts\.go\.jp",
            r"/act/",
            r"/code/",
            r"/rule/",
        ],
        PageType.PRODUCT: [
            r"/product/",
            r"/products/",
            r"/item/",
            r"/spec/",
            r"/specification/",
            r"/datasheet/",
            r"/catalog/",
            r"/shop/",
            r"/store/",
        ],
        PageType.PROFILE: [
            r"/about/",
            r"/company/",
            r"/profile/",
            r"/team/",
            r"/staff/",
            r"/people/",
            r"/corporate/",
            r"/organization/",
        ],
    }

    # Class/ID patterns for detection
    LOGIN_PATTERNS = [
        r"login",
        r"signin",
        r"sign-in",
        r"auth",
        r"paywall",
        r"subscribe",
        r"premium",
        r"members?-only",
        r"restricted",
    ]

    FORUM_PATTERNS = [
        r"thread",
        r"post-\d+",
        r"reply",
        r"comment",
        r"discussion",
        r"forum",
        r"topic",
        r"answer",
        r"vote",
        r"upvote",
        r"downvote",
        r"score",
    ]

    WIKI_PATTERNS = [
        r"wiki",
        r"toc",
        r"table-of-contents",
        r"mw-",
        r"infobox",
        r"navbox",
        r"sidebar",
        r"edit-section",
        r"editsection",
        r"references?",
    ]

    ARTICLE_PATTERNS = [
        r"article",
        r"entry",
        r"post-content",
        r"blog-post",
        r"story",
        r"main-content",
        r"byline",
        r"author",
        r"published",
    ]

    INDEX_PATTERNS = [
        r"listing",
        r"list-item",
        r"card",
        r"grid",
        r"gallery",
        r"pagination",
        r"results?",
        r"archive",
        r"category",
    ]

    ACADEMIC_PATTERNS = [
        r"abstract",
        r"citation",
        r"references?",
        r"doi",
        r"issn",
        r"isbn",
        r"arxiv",
        r"author-?affiliation",
        r"peer-review",
        r"journal",
        r"volume",
        r"issue",
    ]

    REPORT_PATTERNS = [
        r"annual-?report",
        r"quarterly",
        r"fiscal",
        r"investor",
        r"disclosure",
        r"financial",
        r"executive-?summary",
        r"whitepaper",
        r"statistics",
        r"survey-?result",
    ]

    LEGAL_PATTERNS = [
        r"statute",
        r"regulation",
        r"ordinance",
        r"judgment",
        r"ruling",
        r"verdict",
        r"article-?\d+",
        r"section-?\d+",
        r"clause",
        r"enacted",
        r"effective-?date",
        r"法令",
    ]

    PRODUCT_PATTERNS = [
        r"product-?detail",
        r"specification",
        r"price",
        r"add-to-cart",
        r"buy-now",
        r"sku",
        r"model-?number",
        r"datasheet",
        r"features?",
        r"compatibility",
    ]

    PROFILE_PATTERNS = [
        r"about-?us",
        r"company-?profile",
        r"overview",
        r"history",
        r"mission",
        r"vision",
        r"ceo",
        r"executive",
        r"leadership",
        r"biography",
        r"corporate-?info",
        r"会社概要",
    ]

    def __init__(self) -> None:
        """Initialize the page classifier."""
        # Compile patterns for efficiency
        self._login_pattern = re.compile("|".join(self.LOGIN_PATTERNS), re.IGNORECASE)
        self._forum_pattern = re.compile("|".join(self.FORUM_PATTERNS), re.IGNORECASE)
        self._wiki_pattern = re.compile("|".join(self.WIKI_PATTERNS), re.IGNORECASE)
        self._article_pattern = re.compile("|".join(self.ARTICLE_PATTERNS), re.IGNORECASE)
        self._index_pattern = re.compile("|".join(self.INDEX_PATTERNS), re.IGNORECASE)

    def classify(
        self,
        html: str,
        url: str | None = None,
    ) -> ClassificationResult:
        """Classify a web page by type.

        Args:
            html: HTML content of the page.
            url: URL of the page (optional, provides hints).

        Returns:
            ClassificationResult with type, confidence, and reasoning.
        """
        # Extract features from HTML
        features = self._extract_features(html, url)

        # Calculate scores for each page type
        scores = self._calculate_scores(features)

        # Determine best match
        best_type, best_score = max(scores.items(), key=lambda x: x[1])

        # Calculate confidence (normalized score)
        total_score = sum(scores.values())
        confidence = best_score / total_score if total_score > 0 else 0.0

        # Generate reasoning
        reason = self._generate_reason(best_type, features, best_score)

        logger.debug(
            "Page classification complete",
            page_type=best_type.value,
            confidence=confidence,
            scores={k.value: v for k, v in scores.items()},
        )

        return ClassificationResult(
            page_type=best_type,
            confidence=confidence,
            features=self._features_to_dict(features),
            reason=reason,
        )

    def _extract_features(
        self,
        html: str,
        url: str | None,
    ) -> PageFeatures:
        """Extract classification features from HTML.

        Args:
            html: HTML content.
            url: Page URL.

        Returns:
            PageFeatures instance.
        """
        features = PageFeatures()

        # Lowercase for pattern matching
        html_lower = html.lower()

        # Structure features
        features.has_article_tag = "<article" in html_lower
        features.has_main_tag = "<main" in html_lower
        features.has_nav_tag = "<nav" in html_lower
        features.has_aside_tag = "<aside" in html_lower
        features.has_comments_section = self._has_comments_section(html_lower)

        # Content counts
        features.heading_count = len(re.findall(r"<h[1-6][^>]*>", html_lower))
        features.paragraph_count = len(re.findall(r"<p[^>]*>", html_lower))
        features.link_count = len(re.findall(r"<a[^>]*href", html_lower))
        features.list_item_count = len(re.findall(r"<li[^>]*>", html_lower))
        features.form_count = len(re.findall(r"<form[^>]*>", html_lower))
        features.input_count = len(re.findall(r"<input[^>]*>", html_lower))

        # Text ratios
        text_content = re.sub(r"<[^>]+>", "", html)
        text_content = re.sub(r"\s+", " ", text_content).strip()
        features.text_to_html_ratio = len(text_content) / len(html) if len(html) > 0 else 0.0

        # Link density
        total_text_len = len(text_content)
        if total_text_len > 0:
            link_text_len = self._extract_link_text_length(html)
            features.link_density = link_text_len / total_text_len

        # Semantic features
        features.has_breadcrumb = self._has_breadcrumb(html_lower)
        features.has_pagination = self._has_pagination(html_lower)
        features.has_date = self._has_date_indicator(html_lower)
        features.has_author = self._has_author_indicator(html_lower)
        features.has_category = self._has_category_indicator(html_lower)

        # Login/Auth indicators
        features.has_login_form = self._has_login_form(html_lower)
        features.has_password_field = (
            'type="password"' in html_lower or "type='password'" in html_lower
        )
        features.has_paywall_indicator = self._has_paywall_indicator(html_lower)

        # Forum indicators
        features.has_reply_form = self._has_reply_form(html_lower)
        features.has_vote_buttons = self._has_vote_buttons(html_lower)
        features.has_user_avatars = self._has_user_avatars(html_lower)
        features.has_thread_structure = self._has_thread_structure(html_lower)

        # Wiki/Knowledge indicators
        features.has_toc = self._has_toc(html_lower)
        features.has_wiki_structure = self._has_wiki_structure(html_lower)
        features.has_edit_links = self._has_edit_links(html_lower)
        features.has_infobox = self._has_infobox(html_lower)

        # Academic indicators
        features.has_abstract = self._has_abstract(html_lower)
        features.has_citations = self._has_citations(html_lower)
        features.has_doi = self._has_doi(html_lower)
        features.has_academic_structure = self._has_academic_structure(html_lower)

        # Report indicators
        features.has_executive_summary = self._has_executive_summary(html_lower)
        features.has_financial_data = self._has_financial_data(html_lower)
        features.has_charts_tables = self._has_charts_tables(html_lower)
        features.has_report_structure = self._has_report_structure(html_lower)

        # Legal indicators
        features.has_legal_structure = self._has_legal_structure(html_lower)
        features.has_article_numbers = self._has_article_numbers(html_lower)
        features.has_legal_citations = self._has_legal_citations(html_lower)

        # Product indicators
        features.has_price = self._has_price(html_lower)
        features.has_add_to_cart = self._has_add_to_cart(html_lower)
        features.has_specifications = self._has_specifications(html_lower)
        features.has_product_gallery = self._has_product_gallery(html_lower)

        # Profile indicators
        features.has_company_info = self._has_company_info(html_lower)
        features.has_contact_info = self._has_contact_info(html_lower)
        features.has_team_section = self._has_team_section(html_lower)
        features.has_about_section = self._has_about_section(html_lower)

        # URL hints
        if url:
            features.url_hints = self._extract_url_hints(url)

        # Meta OG type
        og_match = re.search(
            r'<meta[^>]*property=["\']og:type["\'][^>]*content=["\']([^"\']+)["\']',
            html_lower,
        )
        if og_match:
            features.meta_og_type = og_match.group(1)

        return features

    def _calculate_scores(self, features: PageFeatures) -> dict[PageType, float]:
        """Calculate classification scores for each page type.

        Args:
            features: Extracted page features.

        Returns:
            Dictionary mapping page types to scores.
        """
        scores: dict[PageType, float] = {pt: 0.0 for pt in PageType if pt != PageType.OTHER}

        # LOGIN_WALL - highest priority checks
        if features.has_login_form and features.has_password_field:
            scores[PageType.LOGIN_WALL] += 5.0
        if features.has_paywall_indicator:
            scores[PageType.LOGIN_WALL] += 3.0
        if any("login" in hint or "signin" in hint for hint in features.url_hints):
            scores[PageType.LOGIN_WALL] += 2.0

        # FORUM indicators
        if features.has_thread_structure:
            scores[PageType.FORUM] += 3.0
        if features.has_reply_form:
            scores[PageType.FORUM] += 2.0
        if features.has_vote_buttons:
            scores[PageType.FORUM] += 2.0
        if features.has_user_avatars:
            scores[PageType.FORUM] += 1.5
        if features.has_comments_section:
            scores[PageType.FORUM] += 1.0
            scores[PageType.ARTICLE] += 0.5  # Articles also have comments
        if any("forum" in hint or "thread" in hint for hint in features.url_hints):
            scores[PageType.FORUM] += 2.0

        # KNOWLEDGE/Wiki indicators
        if features.has_toc:
            scores[PageType.KNOWLEDGE] += 3.0
        if features.has_wiki_structure:
            scores[PageType.KNOWLEDGE] += 2.5
        if features.has_edit_links:
            scores[PageType.KNOWLEDGE] += 2.0
        if features.has_infobox:
            scores[PageType.KNOWLEDGE] += 2.0
        if features.heading_count >= 5:
            scores[PageType.KNOWLEDGE] += 1.0
        if any("wiki" in hint or "docs" in hint for hint in features.url_hints):
            scores[PageType.KNOWLEDGE] += 2.5

        # ARTICLE indicators
        if features.has_article_tag:
            scores[PageType.ARTICLE] += 2.5
        if features.has_date and features.has_author:
            scores[PageType.ARTICLE] += 2.0
        elif features.has_date:
            scores[PageType.ARTICLE] += 1.0
            scores[PageType.NOTICE] += 1.0
        if features.paragraph_count >= 5:
            scores[PageType.ARTICLE] += 1.5
        if features.text_to_html_ratio > 0.3:
            scores[PageType.ARTICLE] += 1.0
        if features.meta_og_type == "article":
            scores[PageType.ARTICLE] += 3.0
        if any("article" in hint or "blog" in hint for hint in features.url_hints):
            scores[PageType.ARTICLE] += 2.0

        # NOTICE indicators
        if features.has_category and features.has_date:
            scores[PageType.NOTICE] += 1.5
        if features.paragraph_count >= 2 and features.paragraph_count <= 10:
            scores[PageType.NOTICE] += 0.5
        if any(
            "news" in hint or "notice" in hint or "press" in hint for hint in features.url_hints
        ):
            scores[PageType.NOTICE] += 2.0

        # INDEX indicators
        if features.has_pagination:
            scores[PageType.INDEX] += 2.5
        if features.link_density > 0.4:
            scores[PageType.INDEX] += 2.0
        if features.list_item_count >= 10:
            scores[PageType.INDEX] += 1.5
        if features.has_breadcrumb:
            scores[PageType.INDEX] += 1.0
            scores[PageType.ARTICLE] += 0.5  # Articles also have breadcrumbs
        if features.paragraph_count < 3 and features.link_count > 20:
            scores[PageType.INDEX] += 2.0
        if any(
            "category" in hint or "archive" in hint or "list" in hint for hint in features.url_hints
        ):
            scores[PageType.INDEX] += 2.0

        # ACADEMIC indicators
        if features.has_abstract:
            scores[PageType.ACADEMIC] += 3.0
        if features.has_doi:
            scores[PageType.ACADEMIC] += 3.0
        if features.has_citations:
            scores[PageType.ACADEMIC] += 2.0
        if features.has_academic_structure:
            scores[PageType.ACADEMIC] += 2.0
        if any(
            "academic" in hint or "paper" in hint or "arxiv" in hint for hint in features.url_hints
        ):
            scores[PageType.ACADEMIC] += 2.5

        # REPORT indicators
        if features.has_executive_summary:
            scores[PageType.REPORT] += 3.0
        if features.has_financial_data:
            scores[PageType.REPORT] += 2.5
        if features.has_report_structure:
            scores[PageType.REPORT] += 2.0
        if features.has_charts_tables:
            scores[PageType.REPORT] += 1.5
        if any(
            "report" in hint or "ir" in hint or "investor" in hint for hint in features.url_hints
        ):
            scores[PageType.REPORT] += 2.5

        # LEGAL indicators
        if features.has_legal_structure:
            scores[PageType.LEGAL] += 3.0
        if features.has_article_numbers:
            scores[PageType.LEGAL] += 2.5
        if features.has_legal_citations:
            scores[PageType.LEGAL] += 2.0
        if any(
            "legal" in hint or "law" in hint or "regulation" in hint for hint in features.url_hints
        ):
            scores[PageType.LEGAL] += 2.5

        # PRODUCT indicators
        if features.has_price:
            scores[PageType.PRODUCT] += 2.5
        if features.has_add_to_cart:
            scores[PageType.PRODUCT] += 3.0
        if features.has_specifications:
            scores[PageType.PRODUCT] += 2.0
        if features.has_product_gallery:
            scores[PageType.PRODUCT] += 1.5
        if any(
            "product" in hint or "shop" in hint or "store" in hint for hint in features.url_hints
        ):
            scores[PageType.PRODUCT] += 2.0

        # PROFILE indicators
        if features.has_about_section:
            scores[PageType.PROFILE] += 2.5
        if features.has_company_info:
            scores[PageType.PROFILE] += 2.0
        if features.has_team_section:
            scores[PageType.PROFILE] += 2.0
        if features.has_contact_info:
            scores[PageType.PROFILE] += 1.5
        if any(
            "profile" in hint or "about" in hint or "company" in hint for hint in features.url_hints
        ):
            scores[PageType.PROFILE] += 2.0

        # Ensure minimum score of 0.1 for each type (to avoid division by zero)
        for pt in scores:
            if scores[pt] < 0.1:
                scores[pt] = 0.1

        # If no strong signals, classify as OTHER
        max_score = max(scores.values())
        if max_score <= 0.5:
            return {PageType.OTHER: 1.0}

        return scores

    def _generate_reason(
        self,
        page_type: PageType,
        features: PageFeatures,
        score: float,
    ) -> str:
        """Generate human-readable classification reason.

        Args:
            page_type: Determined page type.
            features: Extracted features.
            score: Classification score.

        Returns:
            Reason string.
        """
        reasons = []

        if page_type == PageType.LOGIN_WALL:
            if features.has_login_form and features.has_password_field:
                reasons.append("login form with password field detected")
            if features.has_paywall_indicator:
                reasons.append("paywall indicator found")

        elif page_type == PageType.FORUM:
            if features.has_thread_structure:
                reasons.append("thread structure detected")
            if features.has_reply_form:
                reasons.append("reply form present")
            if features.has_vote_buttons:
                reasons.append("vote buttons found")

        elif page_type == PageType.KNOWLEDGE:
            if features.has_toc:
                reasons.append("table of contents present")
            if features.has_wiki_structure:
                reasons.append("wiki-like structure detected")
            if features.has_edit_links:
                reasons.append("edit links found")

        elif page_type == PageType.ARTICLE:
            if features.has_article_tag:
                reasons.append("article tag present")
            if features.has_date:
                reasons.append("publication date found")
            if features.has_author:
                reasons.append("author information present")
            if features.paragraph_count >= 5:
                reasons.append(f"{features.paragraph_count} paragraphs")

        elif page_type == PageType.NOTICE:
            if features.has_date:
                reasons.append("date information present")
            reasons.append("notice/announcement structure")

        elif page_type == PageType.INDEX:
            if features.has_pagination:
                reasons.append("pagination detected")
            if features.link_density > 0.4:
                reasons.append(f"high link density ({features.link_density:.2f})")
            if features.list_item_count >= 10:
                reasons.append(f"{features.list_item_count} list items")

        elif page_type == PageType.ACADEMIC:
            if features.has_abstract:
                reasons.append("abstract section found")
            if features.has_doi:
                reasons.append("DOI identifier present")
            if features.has_citations:
                reasons.append("citations/references section")
            if features.has_academic_structure:
                reasons.append("academic paper structure")

        elif page_type == PageType.REPORT:
            if features.has_executive_summary:
                reasons.append("executive summary present")
            if features.has_financial_data:
                reasons.append("financial data found")
            if features.has_report_structure:
                reasons.append("report structure detected")

        elif page_type == PageType.LEGAL:
            if features.has_legal_structure:
                reasons.append("legal document structure")
            if features.has_article_numbers:
                reasons.append("article/section numbering")
            if features.has_legal_citations:
                reasons.append("legal citations present")

        elif page_type == PageType.PRODUCT:
            if features.has_price:
                reasons.append("price information found")
            if features.has_add_to_cart:
                reasons.append("add to cart functionality")
            if features.has_specifications:
                reasons.append("product specifications")

        elif page_type == PageType.PROFILE:
            if features.has_about_section:
                reasons.append("about section present")
            if features.has_company_info:
                reasons.append("company information found")
            if features.has_team_section:
                reasons.append("team/leadership section")

        elif page_type == PageType.OTHER:
            reasons.append("no strong classification signals")

        if features.url_hints:
            relevant_hints = [h for h in features.url_hints if h]
            if relevant_hints:
                reasons.append(f"URL hints: {', '.join(relevant_hints[:3])}")

        return "; ".join(reasons) if reasons else "default classification"

    # Helper methods for feature extraction

    def _has_comments_section(self, html: str) -> bool:
        """Check for comments section indicators."""
        patterns = [
            r'id=["\']comments["\']',
            r'class=["\'][^"\']*comment',
            r'class=["\'][^"\']*disqus',
            r"<div[^>]*data-comments",
        ]
        return any(re.search(p, html) for p in patterns)

    def _extract_link_text_length(self, html: str) -> int:
        """Extract total length of link text."""
        link_pattern = re.compile(r"<a[^>]*>(.*?)</a>", re.DOTALL | re.IGNORECASE)
        total_length = 0
        for match in link_pattern.finditer(html):
            link_text = re.sub(r"<[^>]+>", "", match.group(1))
            total_length += len(link_text.strip())
        return total_length

    def _has_breadcrumb(self, html: str) -> bool:
        """Check for breadcrumb navigation."""
        patterns = [
            r'class=["\'][^"\']*breadcrumb',
            r'aria-label=["\']breadcrumb',
            r'class=["\'][^"\']*パンくず',  # Japanese
            r'itemtype=["\'][^"\']*BreadcrumbList',
        ]
        return any(re.search(p, html) for p in patterns)

    def _has_pagination(self, html: str) -> bool:
        """Check for pagination elements."""
        patterns = [
            r'class=["\'][^"\']*pagination',
            r'class=["\'][^"\']*pager',
            r'class=["\'][^"\']*page-numbers',
            r'aria-label=["\']pagination',
            r'rel=["\']next["\']',
            r'rel=["\']prev["\']',
        ]
        return any(re.search(p, html) for p in patterns)

    def _has_date_indicator(self, html: str) -> bool:
        """Check for date/time indicators."""
        patterns = [
            r"<time[^>]*datetime",
            r'class=["\'][^"\']*date',
            r'class=["\'][^"\']*published',
            r'itemprop=["\']datePublished',
            r'property=["\']article:published_time',
        ]
        return any(re.search(p, html) for p in patterns)

    def _has_author_indicator(self, html: str) -> bool:
        """Check for author indicators."""
        patterns = [
            r'class=["\'][^"\']*author',
            r'class=["\'][^"\']*byline',
            r'itemprop=["\']author',
            r'rel=["\']author',
            r'property=["\']article:author',
        ]
        return any(re.search(p, html) for p in patterns)

    def _has_category_indicator(self, html: str) -> bool:
        """Check for category/tag indicators."""
        patterns = [
            r'class=["\'][^"\']*category',
            r'class=["\'][^"\']*tag',
            r'rel=["\']tag',
            r'property=["\']article:tag',
        ]
        return any(re.search(p, html) for p in patterns)

    def _has_login_form(self, html: str) -> bool:
        """Check for login form indicators."""
        patterns = [
            r"<form[^>]*login",
            r"<form[^>]*signin",
            r"<form[^>]*auth",
            r'id=["\']login',
            r'class=["\'][^"\']*login-form',
        ]
        return any(re.search(p, html) for p in patterns)

    def _has_paywall_indicator(self, html: str) -> bool:
        """Check for paywall/subscription indicators."""
        patterns = [
            r'class=["\'][^"\']*paywall',
            r'class=["\'][^"\']*subscribe',
            r'class=["\'][^"\']*premium',
            r'class=["\'][^"\']*members-only',
            r"data-paywall",
            r"登録が必要",  # Japanese: registration required
            r"有料会員",  # Japanese: paid member
        ]
        return any(re.search(p, html) for p in patterns)

    def _has_reply_form(self, html: str) -> bool:
        """Check for reply/comment form."""
        patterns = [
            r"<form[^>]*reply",
            r"<form[^>]*comment",
            r'id=["\']reply',
            r'class=["\'][^"\']*reply-form',
            r'class=["\'][^"\']*comment-form',
            r"<textarea[^>]*comment",
        ]
        return any(re.search(p, html) for p in patterns)

    def _has_vote_buttons(self, html: str) -> bool:
        """Check for voting/rating buttons."""
        patterns = [
            r'class=["\'][^"\']*vote',
            r'class=["\'][^"\']*upvote',
            r'class=["\'][^"\']*downvote',
            r'class=["\'][^"\']*like-button',
            r'class=["\'][^"\']*rating',
            r'aria-label=["\'][^"\']*vote',
        ]
        return any(re.search(p, html) for p in patterns)

    def _has_user_avatars(self, html: str) -> bool:
        """Check for user avatar indicators (forum/social)."""
        patterns = [
            r'class=["\'][^"\']*avatar',
            r'class=["\'][^"\']*user-icon',
            r'class=["\'][^"\']*profile-pic',
            r'class=["\'][^"\']*user-image',
        ]
        return any(re.search(p, html) for p in patterns)

    def _has_thread_structure(self, html: str) -> bool:
        """Check for threaded discussion structure."""
        patterns = [
            r'class=["\'][^"\']*thread',
            r'class=["\'][^"\']*post-list',
            r'class=["\'][^"\']*comment-thread',
            r'class=["\'][^"\']*nested-comment',
            r'class=["\'][^"\']*reply-list',
        ]
        return any(re.search(p, html) for p in patterns)

    def _has_toc(self, html: str) -> bool:
        """Check for table of contents."""
        patterns = [
            r'class=["\'][^"\']*toc',
            r'class=["\'][^"\']*table-of-contents',
            r'id=["\']toc["\']',
            r'id=["\']table-of-contents',
            r'class=["\'][^"\']*mw-toc',  # MediaWiki TOC
            r"目次",  # Japanese: table of contents
        ]
        return any(re.search(p, html) for p in patterns)

    def _has_wiki_structure(self, html: str) -> bool:
        """Check for wiki-like structure."""
        patterns = [
            r'class=["\'][^"\']*mw-',  # MediaWiki
            r'class=["\'][^"\']*wiki',
            r'id=["\']mw-',
            r'class=["\'][^"\']*wikitable',
        ]
        return any(re.search(p, html) for p in patterns)

    def _has_edit_links(self, html: str) -> bool:
        """Check for edit links (wiki indicator)."""
        patterns = [
            r'class=["\'][^"\']*edit-?section',  # edit-section or editsection
            r'class=["\'][^"\']*mw-editsection',  # MediaWiki edit section
            r'class=["\'][^"\']*edit-link',
            r'title=["\'][^"\']*edit',
            r">編集<",  # Japanese: edit
            r"action=edit",
            r"\[edit\]",  # Plain text edit link
        ]
        return any(re.search(p, html) for p in patterns)

    def _has_infobox(self, html: str) -> bool:
        """Check for infobox (wiki/knowledge indicator)."""
        patterns = [
            r'class=["\'][^"\']*infobox',
            r'class=["\'][^"\']*sidebar',
            r'class=["\'][^"\']*factbox',
            r'class=["\'][^"\']*summary-box',
        ]
        return any(re.search(p, html) for p in patterns)

    # Academic feature helpers

    def _has_abstract(self, html: str) -> bool:
        """Check for abstract section (academic papers)."""
        patterns = [
            r'class=["\'][^"\']*abstract',
            r'id=["\']abstract',
            r"<h[1-6][^>]*>abstract</h",
            r"<h[1-6][^>]*>要旨</h",  # Japanese
            r"<h[1-6][^>]*>概要</h",  # Japanese
        ]
        return any(re.search(p, html) for p in patterns)

    def _has_citations(self, html: str) -> bool:
        """Check for citations/references section."""
        patterns = [
            r'class=["\'][^"\']*citation',
            r'class=["\'][^"\']*reference',
            r'id=["\']references',
            r"<h[1-6][^>]*>references</h",
            r"<h[1-6][^>]*>参考文献</h",  # Japanese
            r"<h[1-6][^>]*>引用</h",  # Japanese
        ]
        return any(re.search(p, html) for p in patterns)

    def _has_doi(self, html: str) -> bool:
        """Check for DOI (Digital Object Identifier)."""
        patterns = [
            r"doi\.org/",
            r"doi:\s*10\.",
            r'class=["\'][^"\']*doi',
            r'10\.\d{4,}/[^\s"\'<>]+',  # DOI pattern
        ]
        return any(re.search(p, html) for p in patterns)

    def _has_academic_structure(self, html: str) -> bool:
        """Check for academic paper structure."""
        patterns = [
            r'class=["\'][^"\']*author-affiliation',
            r'class=["\'][^"\']*journal',
            r'class=["\'][^"\']*volume',
            r"issn|isbn",
            r"peer-review",
            r"<meta[^>]*citation",
        ]
        return any(re.search(p, html) for p in patterns)

    # Report feature helpers

    def _has_executive_summary(self, html: str) -> bool:
        """Check for executive summary section."""
        patterns = [
            r'class=["\'][^"\']*executive-summary',
            r"<h[1-6][^>]*>executive summary</h",
            r"<h[1-6][^>]*>エグゼクティブサマリー</h",
            r"<h[1-6][^>]*>要約</h",
        ]
        return any(re.search(p, html) for p in patterns)

    def _has_financial_data(self, html: str) -> bool:
        """Check for financial data indicators."""
        patterns = [
            r'class=["\'][^"\']*financial',
            r'class=["\'][^"\']*revenue',
            r'class=["\'][^"\']*earnings',
            r"決算|売上|利益|財務",  # Japanese financial terms
            r"quarter|fiscal|fy\d{2,4}",
        ]
        return any(re.search(p, html) for p in patterns)

    def _has_charts_tables(self, html: str) -> bool:
        """Check for charts/tables (report indicator)."""
        table_count = len(re.findall(r"<table[^>]*>", html))
        chart_patterns = [
            r'class=["\'][^"\']*chart',
            r'class=["\'][^"\']*graph',
            r"<canvas",
            r'<svg[^>]*class=["\'][^"\']*chart',
        ]
        has_charts = any(re.search(p, html) for p in chart_patterns)
        return table_count >= 3 or has_charts

    def _has_report_structure(self, html: str) -> bool:
        """Check for report document structure."""
        patterns = [
            r'class=["\'][^"\']*report',
            r'class=["\'][^"\']*whitepaper',
            r'class=["\'][^"\']*disclosure',
            r"有価証券報告書|決算短信|年次報告",  # Japanese report types
        ]
        return any(re.search(p, html) for p in patterns)

    # Legal feature helpers

    def _has_legal_structure(self, html: str) -> bool:
        """Check for legal document structure."""
        patterns = [
            r'class=["\'][^"\']*statute',
            r'class=["\'][^"\']*regulation',
            r'class=["\'][^"\']*law-text',
            r'class=["\'][^"\']*legal-doc',
            r"法令|条例|規則|判例",  # Japanese legal terms
        ]
        return any(re.search(p, html) for p in patterns)

    def _has_article_numbers(self, html: str) -> bool:
        """Check for article/section numbering (legal docs)."""
        patterns = [
            r"第[一二三四五六七八九十百千]+条",  # Japanese article numbers
            r"article\s+\d+",
            r"section\s+\d+",
            r"§\s*\d+",
        ]
        return any(re.search(p, html) for p in patterns)

    def _has_legal_citations(self, html: str) -> bool:
        """Check for legal citations."""
        patterns = [
            r"\d+\s+u\.?s\.?\s+\d+",  # US case citations
            r"平成\d+年.*判決",  # Japanese court decisions
            r"令和\d+年.*判決",
            r'class=["\'][^"\']*case-citation',
        ]
        return any(re.search(p, html) for p in patterns)

    # Product feature helpers

    def _has_price(self, html: str) -> bool:
        """Check for price information."""
        patterns = [
            r'class=["\'][^"\']*price',
            r"¥\s*[\d,]+",  # Japanese Yen
            r"\$\s*[\d,]+\.?\d*",  # US Dollar
            r"€\s*[\d,]+",  # Euro
            r'itemprop=["\']price',
        ]
        return any(re.search(p, html) for p in patterns)

    def _has_add_to_cart(self, html: str) -> bool:
        """Check for add-to-cart functionality."""
        patterns = [
            r"add-to-cart",
            r"add_to_cart",
            r'class=["\'][^"\']*cart',
            r'class=["\'][^"\']*buy-now',
            r"カートに入れる",  # Japanese
            r"購入する",  # Japanese
        ]
        return any(re.search(p, html) for p in patterns)

    def _has_specifications(self, html: str) -> bool:
        """Check for product specifications."""
        patterns = [
            r'class=["\'][^"\']*spec',
            r'class=["\'][^"\']*specification',
            r'class=["\'][^"\']*product-detail',
            r"仕様|スペック",  # Japanese
        ]
        return any(re.search(p, html) for p in patterns)

    def _has_product_gallery(self, html: str) -> bool:
        """Check for product image gallery."""
        patterns = [
            r'class=["\'][^"\']*product-gallery',
            r'class=["\'][^"\']*product-image',
            r'class=["\'][^"\']*gallery-thumb',
            r"data-zoom-image",
        ]
        return any(re.search(p, html) for p in patterns)

    # Profile feature helpers

    def _has_company_info(self, html: str) -> bool:
        """Check for company information."""
        patterns = [
            r'class=["\'][^"\']*company-info',
            r'class=["\'][^"\']*corporate',
            r"会社概要|企業情報|会社情報",  # Japanese
            r"founded|established|since\s+\d{4}",
        ]
        return any(re.search(p, html) for p in patterns)

    def _has_contact_info(self, html: str) -> bool:
        """Check for contact information."""
        patterns = [
            r'class=["\'][^"\']*contact',
            r'class=["\'][^"\']*address',
            r"お問い合わせ|連絡先",  # Japanese
            r"tel:|phone:|fax:",
        ]
        return any(re.search(p, html) for p in patterns)

    def _has_team_section(self, html: str) -> bool:
        """Check for team/leadership section."""
        patterns = [
            r'class=["\'][^"\']*team',
            r'class=["\'][^"\']*leadership',
            r'class=["\'][^"\']*executive',
            r"経営陣|役員|チーム",  # Japanese
        ]
        return any(re.search(p, html) for p in patterns)

    def _has_about_section(self, html: str) -> bool:
        """Check for about section."""
        patterns = [
            r'class=["\'][^"\']*about',
            r'id=["\']about',
            r"<h[1-6][^>]*>about\s*(us)?</h",
            r"私たちについて|当社について",  # Japanese
        ]
        return any(re.search(p, html) for p in patterns)

    def _extract_url_hints(self, url: str) -> list[str]:
        """Extract classification hints from URL.

        Args:
            url: Page URL.

        Returns:
            List of hint strings.
        """
        hints = []

        try:
            parsed = urlparse(url)
            path = parsed.path.lower()
            # Also check hostname for patterns like docs.example.com
            hostname = parsed.netloc.lower()
            full_url = hostname + path

            for page_type, patterns in self.URL_PATTERNS.items():
                for pattern in patterns:
                    if re.search(pattern, full_url):
                        hints.append(page_type.value)
                        break

            # Check for common path segments
            segments = path.split("/")
            for seg in segments:
                if seg in [
                    "news",
                    "blog",
                    "article",
                    "wiki",
                    "docs",
                    "forum",
                    "thread",
                    "category",
                    "tag",
                    "archive",
                    "press",
                    "notice",
                    "announcement",
                    "release",
                ]:
                    hints.append(seg)

            # Check hostname for subdomains like docs., blog., forum.
            hostname_parts = hostname.split(".")
            if hostname_parts:
                subdomain = hostname_parts[0]
                if subdomain in [
                    "docs",
                    "blog",
                    "forum",
                    "wiki",
                    "help",
                    "support",
                    "community",
                    "news",
                ]:
                    hints.append(subdomain)
        except Exception as e:
            logger.debug("URL hint extraction failed", error=str(e))

        return hints

    def _features_to_dict(self, features: PageFeatures) -> dict[str, Any]:
        """Convert PageFeatures to dictionary for serialization.

        Args:
            features: PageFeatures instance.

        Returns:
            Dictionary representation.
        """
        return {
            "structure": {
                "has_article_tag": features.has_article_tag,
                "has_main_tag": features.has_main_tag,
                "has_nav_tag": features.has_nav_tag,
                "has_aside_tag": features.has_aside_tag,
                "has_comments_section": features.has_comments_section,
            },
            "content": {
                "heading_count": features.heading_count,
                "paragraph_count": features.paragraph_count,
                "link_count": features.link_count,
                "list_item_count": features.list_item_count,
                "form_count": features.form_count,
                "input_count": features.input_count,
            },
            "ratios": {
                "text_to_html_ratio": round(features.text_to_html_ratio, 3),
                "link_density": round(features.link_density, 3),
            },
            "semantic": {
                "has_breadcrumb": features.has_breadcrumb,
                "has_pagination": features.has_pagination,
                "has_date": features.has_date,
                "has_author": features.has_author,
                "has_category": features.has_category,
            },
            "login": {
                "has_login_form": features.has_login_form,
                "has_password_field": features.has_password_field,
                "has_paywall_indicator": features.has_paywall_indicator,
            },
            "forum": {
                "has_reply_form": features.has_reply_form,
                "has_vote_buttons": features.has_vote_buttons,
                "has_user_avatars": features.has_user_avatars,
                "has_thread_structure": features.has_thread_structure,
            },
            "knowledge": {
                "has_toc": features.has_toc,
                "has_wiki_structure": features.has_wiki_structure,
                "has_edit_links": features.has_edit_links,
                "has_infobox": features.has_infobox,
            },
            "academic": {
                "has_abstract": features.has_abstract,
                "has_citations": features.has_citations,
                "has_doi": features.has_doi,
                "has_academic_structure": features.has_academic_structure,
            },
            "report": {
                "has_executive_summary": features.has_executive_summary,
                "has_financial_data": features.has_financial_data,
                "has_charts_tables": features.has_charts_tables,
                "has_report_structure": features.has_report_structure,
            },
            "legal": {
                "has_legal_structure": features.has_legal_structure,
                "has_article_numbers": features.has_article_numbers,
                "has_legal_citations": features.has_legal_citations,
            },
            "product": {
                "has_price": features.has_price,
                "has_add_to_cart": features.has_add_to_cart,
                "has_specifications": features.has_specifications,
                "has_product_gallery": features.has_product_gallery,
            },
            "profile": {
                "has_company_info": features.has_company_info,
                "has_contact_info": features.has_contact_info,
                "has_team_section": features.has_team_section,
                "has_about_section": features.has_about_section,
            },
            "meta": {
                "url_hints": features.url_hints,
                "meta_og_type": features.meta_og_type,
            },
        }


# Singleton instance
_classifier: PageClassifier | None = None


def get_classifier() -> PageClassifier:
    """Get or create the singleton PageClassifier instance.

    Returns:
        PageClassifier instance.
    """
    global _classifier
    if _classifier is None:
        _classifier = PageClassifier()
    return _classifier


def classify_page(
    html: str,
    url: str | None = None,
) -> ClassificationResult:
    """Classify a web page by type.

    Convenience function that uses the singleton classifier.

    Args:
        html: HTML content of the page.
        url: URL of the page (optional).

    Returns:
        ClassificationResult with type, confidence, and features.
    """
    classifier = get_classifier()
    return classifier.classify(html, url)
