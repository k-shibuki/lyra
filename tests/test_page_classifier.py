"""
Unit tests for PageClassifier (§3.1.2).

Tests page type classification for:
- article: News articles, blog posts
- knowledge: Wiki pages, documentation
- notice: Official announcements, press releases
- forum: Discussion boards, Q&A
- login_wall: Pages requiring authentication
- index: Category pages, search results

## Test Perspectives Table
| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---------|----------------------|---------------------------------------|-----------------|-------|
| TC-PT-01 | PageType values | Equivalence – enum | All types defined | - |
| TC-PF-01 | Extract features from HTML | Equivalence – extraction | PageFeatures populated | - |
| TC-PC-01 | Classify article page | Equivalence – article | type=article | - |
| TC-PC-02 | Classify knowledge page | Equivalence – knowledge | type=knowledge | - |
| TC-PC-03 | Classify notice page | Equivalence – notice | type=notice | - |
| TC-PC-04 | Classify forum page | Equivalence – forum | type=forum | - |
| TC-PC-05 | Classify login wall | Equivalence – login | type=login_wall | - |
| TC-PC-06 | Classify index page | Equivalence – index | type=index | - |
| TC-PC-07 | Classify empty page | Boundary – empty | Default type | - |
| TC-CR-01 | ClassificationResult creation | Equivalence – result | Type with confidence | - |
| TC-CR-02 | Result serialization | Equivalence – to_dict | Dictionary output | - |
| TC-CF-01 | classify_page function | Equivalence – convenience | Returns result | - |
| TC-CF-02 | get_classifier singleton | Equivalence – singleton | Returns classifier | - |
"""

import pytest

# All tests in this module are unit tests (no external dependencies)
pytestmark = pytest.mark.unit
from src.extractor.page_classifier import (
    ClassificationResult,
    PageClassifier,
    PageType,
    classify_page,
    get_classifier,
)


@pytest.fixture
def classifier():
    """Create a PageClassifier instance for testing."""
    return PageClassifier()


# ============================================================
# Article classification tests
# ============================================================

class TestArticleClassification:
    """Tests for article page type detection."""


    def test_article_with_article_tag(self, classifier):
        """Article tag is a strong indicator of article type."""
        html = """
        <html>
        <body>
            <article>
                <h1>Breaking News: Important Discovery</h1>
                <time datetime="2024-01-15">January 15, 2024</time>
                <span class="author">John Smith</span>
                <p>This is the first paragraph of the article.</p>
                <p>This is the second paragraph with more details.</p>
                <p>This is the third paragraph.</p>
                <p>This is the fourth paragraph.</p>
                <p>This is the fifth paragraph with conclusion.</p>
            </article>
        </body>
        </html>
        """
        result = classifier.classify(html, "https://example.com/news/2024/01/15/breaking-news")

        assert result.page_type == PageType.ARTICLE
        assert result.confidence > 0.3
        assert result.features["structure"]["has_article_tag"] is True
        assert result.features["semantic"]["has_date"] is True


    def test_article_with_og_type(self, classifier):
        """og:type=article metadata should boost article classification."""
        html = """
        <html>
        <head>
            <meta property="og:type" content="article">
            <meta property="article:published_time" content="2024-01-15">
        </head>
        <body>
            <main>
                <h1>Blog Post Title</h1>
                <p>Introduction paragraph.</p>
                <p>Main content paragraph.</p>
                <p>More content here.</p>
                <p>Conclusion paragraph.</p>
                <p>Final thoughts.</p>
            </main>
        </body>
        </html>
        """
        result = classifier.classify(html, "https://blog.example.com/post/123")

        assert result.page_type == PageType.ARTICLE
        assert result.features["meta"]["meta_og_type"] == "article"


    def test_article_url_hint(self, classifier):
        """URL patterns like /blog/ or /article/ hint at article type."""
        html = """
        <html>
        <body>
            <div class="post-content">
                <h1>My Blog Post</h1>
                <p>Content paragraph one.</p>
                <p>Content paragraph two.</p>
                <p>Content paragraph three.</p>
                <p>Content paragraph four.</p>
                <p>Content paragraph five.</p>
            </div>
        </body>
        </html>
        """
        result = classifier.classify(html, "https://example.com/blog/my-post")

        assert "blog" in result.features["meta"]["url_hints"]


# ============================================================
# Knowledge/Wiki classification tests
# ============================================================

class TestKnowledgeClassification:
    """Tests for knowledge/wiki page type detection."""


    def test_wiki_with_toc(self, classifier):
        """Table of contents is a strong wiki/knowledge indicator."""
        html = """
        <html>
        <body>
            <div class="mw-content">
                <h1>Python Programming Language</h1>
                <div id="toc" class="toc">
                    <h2>Contents</h2>
                    <ul>
                        <li><a href="#history">History</a></li>
                        <li><a href="#features">Features</a></li>
                        <li><a href="#syntax">Syntax</a></li>
                    </ul>
                </div>
                <h2 id="history">History</h2>
                <p>Python was created by Guido van Rossum.</p>
                <h2 id="features">Features</h2>
                <p>Python is known for its simplicity.</p>
                <h2 id="syntax">Syntax</h2>
                <p>Python uses indentation for blocks.</p>
            </div>
        </body>
        </html>
        """
        result = classifier.classify(html, "https://en.wikipedia.org/wiki/Python")

        assert result.page_type == PageType.KNOWLEDGE
        assert result.features["knowledge"]["has_toc"] is True


    def test_wiki_with_mediawiki_structure(self, classifier):
        """MediaWiki class patterns indicate wiki pages."""
        html = """
        <html>
        <body>
            <div id="mw-content-text" class="mw-body-content">
                <table class="infobox">
                    <tr><th>Name</th><td>Example</td></tr>
                </table>
                <p>This is a wiki article about Example.</p>
                <span class="mw-editsection">[<a href="/edit">edit</a>]</span>
                <h2>Section 1</h2>
                <h2>Section 2</h2>
                <h2>Section 3</h2>
                <h2>Section 4</h2>
                <h2>Section 5</h2>
            </div>
        </body>
        </html>
        """
        result = classifier.classify(html)

        assert result.page_type == PageType.KNOWLEDGE
        assert result.features["knowledge"]["has_wiki_structure"] is True
        assert result.features["knowledge"]["has_edit_links"] is True
        assert result.features["knowledge"]["has_infobox"] is True


    def test_documentation_page(self, classifier):
        """Documentation pages should be classified as knowledge."""
        html = """
        <html>
        <body>
            <div class="documentation">
                <nav class="table-of-contents">
                    <ul>
                        <li><a href="#install">Installation</a></li>
                        <li><a href="#usage">Usage</a></li>
                    </ul>
                </nav>
                <h1>API Documentation</h1>
                <h2 id="install">Installation</h2>
                <p>pip install package</p>
                <h2 id="usage">Usage</h2>
                <p>Import the module and call functions.</p>
                <h2>Configuration</h2>
                <h2>Examples</h2>
                <h2>Reference</h2>
            </div>
        </body>
        </html>
        """
        result = classifier.classify(html, "https://docs.example.com/api/reference")

        assert result.page_type == PageType.KNOWLEDGE
        assert "docs" in result.features["meta"]["url_hints"]


# ============================================================
# Forum classification tests
# ============================================================

class TestForumClassification:
    """Tests for forum/discussion page type detection."""


    def test_forum_with_thread_structure(self, classifier):
        """Thread structure indicates forum pages."""
        html = """
        <html>
        <body>
            <div class="thread">
                <div class="post" data-post-id="1">
                    <img class="avatar" src="/user/1/avatar.png">
                    <div class="post-content">Original question here.</div>
                    <button class="upvote">▲</button>
                    <button class="downvote">▼</button>
                </div>
                <div class="post" data-post-id="2">
                    <img class="avatar" src="/user/2/avatar.png">
                    <div class="post-content">First reply here.</div>
                </div>
            </div>
            <form class="reply-form">
                <textarea name="reply"></textarea>
                <button type="submit">Reply</button>
            </form>
        </body>
        </html>
        """
        result = classifier.classify(html, "https://forum.example.com/thread/12345")

        assert result.page_type == PageType.FORUM
        assert result.features["forum"]["has_thread_structure"] is True
        assert result.features["forum"]["has_reply_form"] is True
        assert result.features["forum"]["has_vote_buttons"] is True
        assert result.features["forum"]["has_user_avatars"] is True


    def test_qa_page(self, classifier):
        """Q&A sites should be classified as forum."""
        html = """
        <html>
        <body>
            <div class="question">
                <h1>How do I do X?</h1>
                <div class="vote-container">
                    <button class="vote-up">▲</button>
                    <span class="score">42</span>
                    <button class="vote-down">▼</button>
                </div>
            </div>
            <div class="answers">
                <div class="answer">
                    <div class="vote-container">
                        <button class="vote-up">▲</button>
                        <span class="score">15</span>
                    </div>
                    <div class="answer-content">You can do it like this...</div>
                </div>
            </div>
            <form id="reply">
                <textarea name="answer" placeholder="Your answer"></textarea>
            </form>
        </body>
        </html>
        """
        result = classifier.classify(html, "https://qa.example.com/questions/12345")

        assert result.page_type == PageType.FORUM
        assert result.features["forum"]["has_vote_buttons"] is True


# ============================================================
# Login wall classification tests
# ============================================================

class TestLoginWallClassification:
    """Tests for login wall/paywall page type detection."""


    def test_login_form_detection(self, classifier):
        """Login form with password field should classify as login_wall."""
        html = """
        <html>
        <body>
            <div class="login-container">
                <h1>Sign In</h1>
                <form id="login-form" action="/auth/login" method="POST">
                    <input type="text" name="username" placeholder="Username">
                    <input type="password" name="password" placeholder="Password">
                    <button type="submit">Sign In</button>
                </form>
                <a href="/forgot-password">Forgot password?</a>
            </div>
        </body>
        </html>
        """
        result = classifier.classify(html, "https://example.com/login")

        assert result.page_type == PageType.LOGIN_WALL
        assert result.confidence > 0.4
        assert result.features["login"]["has_login_form"] is True
        assert result.features["login"]["has_password_field"] is True


    def test_paywall_detection(self, classifier):
        """Paywall indicators should classify as login_wall."""
        html = """
        <html>
        <body>
            <article>
                <h1>Premium Content</h1>
                <p>This is a preview of the article...</p>
            </article>
            <div class="paywall">
                <h2>Subscribe to continue reading</h2>
                <p>This content is for premium members only.</p>
                <button class="subscribe-btn">Subscribe Now</button>
            </div>
        </body>
        </html>
        """
        result = classifier.classify(html)

        assert result.page_type == PageType.LOGIN_WALL
        assert result.features["login"]["has_paywall_indicator"] is True


    def test_japanese_members_only(self, classifier):
        """Japanese members-only pages should be detected."""
        html = """
        <html>
        <body>
            <div class="members-only">
                <h1>有料会員専用コンテンツ</h1>
                <p>このコンテンツは有料会員限定です。</p>
                <form action="/login" method="POST">
                    <input type="email" name="email">
                    <input type="password" name="password">
                    <button type="submit">ログイン</button>
                </form>
            </div>
        </body>
        </html>
        """
        result = classifier.classify(html)

        assert result.page_type == PageType.LOGIN_WALL
        assert result.features["login"]["has_paywall_indicator"] is True


# ============================================================
# Index classification tests
# ============================================================

class TestIndexClassification:
    """Tests for index/listing page type detection."""


    def test_category_page(self, classifier):
        """Category pages with many links should classify as index."""
        html = """
        <html>
        <body>
            <nav class="breadcrumb">
                <a href="/">Home</a> > <a href="/category">Category</a>
            </nav>
            <h1>Category: Technology</h1>
            <ul class="article-list">
                <li><a href="/article/1">Article 1</a></li>
                <li><a href="/article/2">Article 2</a></li>
                <li><a href="/article/3">Article 3</a></li>
                <li><a href="/article/4">Article 4</a></li>
                <li><a href="/article/5">Article 5</a></li>
                <li><a href="/article/6">Article 6</a></li>
                <li><a href="/article/7">Article 7</a></li>
                <li><a href="/article/8">Article 8</a></li>
                <li><a href="/article/9">Article 9</a></li>
                <li><a href="/article/10">Article 10</a></li>
                <li><a href="/article/11">Article 11</a></li>
                <li><a href="/article/12">Article 12</a></li>
            </ul>
            <nav class="pagination">
                <a href="?page=1">1</a>
                <a href="?page=2">2</a>
                <a href="?page=3">3</a>
            </nav>
        </body>
        </html>
        """
        result = classifier.classify(html, "https://example.com/category/technology")

        assert result.page_type == PageType.INDEX
        assert result.features["semantic"]["has_pagination"] is True
        assert result.features["semantic"]["has_breadcrumb"] is True
        assert result.features["content"]["list_item_count"] >= 10


    def test_search_results(self, classifier):
        """Search results pages should classify as index."""
        html = """
        <html>
        <body>
            <h1>Search Results for "python"</h1>
            <div class="results">
                <div class="result-item">
                    <a href="/doc/1">Python Documentation</a>
                    <p>Official Python documentation...</p>
                </div>
                <div class="result-item">
                    <a href="/doc/2">Python Tutorial</a>
                    <p>Learn Python programming...</p>
                </div>
            </div>
            <a href="/search?q=python&page=2" rel="next">Next</a>
        </body>
        </html>
        """
        result = classifier.classify(html, "https://example.com/search?q=python")

        assert result.page_type == PageType.INDEX
        assert result.features["semantic"]["has_pagination"] is True


    def test_archive_page(self, classifier):
        """Archive pages should classify as index."""
        html = """
        <html>
        <body>
            <h1>Archive: 2024</h1>
            <ul class="archive-list">
                <li><a href="/2024/01/post1">January Post 1</a></li>
                <li><a href="/2024/01/post2">January Post 2</a></li>
                <li><a href="/2024/02/post3">February Post 1</a></li>
                <li><a href="/2024/02/post4">February Post 2</a></li>
                <li><a href="/2024/03/post5">March Post 1</a></li>
                <li><a href="/2024/03/post6">March Post 2</a></li>
                <li><a href="/2024/04/post7">April Post 1</a></li>
                <li><a href="/2024/04/post8">April Post 2</a></li>
                <li><a href="/2024/05/post9">May Post 1</a></li>
                <li><a href="/2024/05/post10">May Post 2</a></li>
            </ul>
        </body>
        </html>
        """
        result = classifier.classify(html, "https://example.com/archive/2024")

        assert result.page_type == PageType.INDEX
        assert "archive" in result.features["meta"]["url_hints"]


# ============================================================
# Notice classification tests
# ============================================================

class TestNoticeClassification:
    """Tests for notice/announcement page type detection."""


    def test_press_release(self, classifier):
        """Press release pages should classify as notice."""
        html = """
        <html>
        <body>
            <main>
                <time datetime="2024-01-15">2024年1月15日</time>
                <span class="category">プレスリリース</span>
                <h1>新製品発表のお知らせ</h1>
                <p>このたび、弊社は新製品を発表いたします。</p>
                <p>詳細は以下のとおりです。</p>
            </main>
        </body>
        </html>
        """
        result = classifier.classify(html, "https://example.com/press/2024/01/new-product")

        assert result.page_type == PageType.NOTICE
        assert "press" in result.features["meta"]["url_hints"]


    def test_official_announcement(self, classifier):
        """Official announcements should classify as notice."""
        html = """
        <html>
        <body>
            <article>
                <header>
                    <span class="category">お知らせ</span>
                    <time datetime="2024-03-01">2024年3月1日</time>
                </header>
                <h1>サービスメンテナンスのお知らせ</h1>
                <p>システムメンテナンスを実施します。</p>
            </article>
        </body>
        </html>
        """
        result = classifier.classify(html, "https://example.com/notice/maintenance")

        assert result.page_type in [PageType.NOTICE, PageType.ARTICLE]
        assert result.features["semantic"]["has_date"] is True


# ============================================================
# Edge cases and feature extraction tests
# ============================================================

class TestFeatureExtraction:
    """Tests for feature extraction accuracy."""


    def test_text_to_html_ratio(self, classifier):
        """Text-to-HTML ratio should be calculated correctly."""
        # High text ratio (article-like)
        html_high = """
        <html><body>
        <p>This is a long paragraph with lots of text content that makes up
        the majority of the page content without many HTML tags.</p>
        <p>Another paragraph with substantial text content.</p>
        </body></html>
        """
        result_high = classifier.classify(html_high)

        assert result_high.features["ratios"]["text_to_html_ratio"] > 0.3


    def test_link_density(self, classifier):
        """Link density should be calculated correctly."""
        # High link density (index-like)
        html = """
        <html><body>
        <ul>
            <li><a href="/1">Link 1 with some text</a></li>
            <li><a href="/2">Link 2 with some text</a></li>
            <li><a href="/3">Link 3 with some text</a></li>
            <li><a href="/4">Link 4 with some text</a></li>
            <li><a href="/5">Link 5 with some text</a></li>
        </ul>
        </body></html>
        """
        result = classifier.classify(html)

        assert result.features["ratios"]["link_density"] > 0.5


    def test_empty_html(self, classifier):
        """Empty or minimal HTML should classify as OTHER."""
        html = "<html><body></body></html>"
        result = classifier.classify(html)

        assert result.page_type == PageType.OTHER
        assert result.features["content"]["paragraph_count"] == 0


    def test_heading_count(self, classifier):
        """Heading count should be extracted correctly."""
        html = """
        <html><body>
        <h1>Title</h1>
        <h2>Section 1</h2>
        <h3>Subsection 1.1</h3>
        <h2>Section 2</h2>
        <h3>Subsection 2.1</h3>
        <h3>Subsection 2.2</h3>
        </body></html>
        """
        result = classifier.classify(html)

        assert result.features["content"]["heading_count"] == 6


class TestClassifierUtilities:
    """Tests for classifier utility functions."""

    def test_get_classifier_singleton(self):
        """get_classifier should return the same instance."""
        classifier1 = get_classifier()
        classifier2 = get_classifier()

        assert classifier1 is classifier2


    def test_classify_page_convenience(self):
        """classify_page convenience function should work."""
        html = "<html><body><article><p>Content</p></article></body></html>"
        result = classify_page(html, "https://example.com/article/1")

        assert isinstance(result, ClassificationResult)
        assert isinstance(result.page_type, PageType)
        assert 0.0 <= result.confidence <= 1.0


    def test_url_hint_extraction(self, classifier):
        """URL hints should be extracted from various URL patterns."""
        # Wiki URL
        result_wiki = classifier.classify(
            "<html><body></body></html>",
            "https://en.wikipedia.org/wiki/Python"
        )
        assert "knowledge" in result_wiki.features["meta"]["url_hints"]

        # Forum URL
        result_forum = classifier.classify(
            "<html><body></body></html>",
            "https://forum.example.com/thread/123"
        )
        assert "forum" in result_forum.features["meta"]["url_hints"]


    def test_reason_generation(self, classifier):
        """Classification reasons should be generated."""
        html = """
        <html><body>
        <article>
            <time datetime="2024-01-01">2024-01-01</time>
            <span class="author">Author Name</span>
            <p>Content paragraph.</p>
        </article>
        </body></html>
        """
        result = classifier.classify(html)

        assert result.reason  # Should have a reason
        # Reason should be a meaningful explanation (at least 10 chars)
        assert len(result.reason) >= 10, f"Expected reason >=10 chars, got: {result.reason}"


class TestMixedSignals:
    """Tests for pages with mixed classification signals."""


    def test_article_with_comments(self, classifier):
        """Articles with comments should still classify as article."""
        html = """
        <html><body>
        <article>
            <h1>Blog Post Title</h1>
            <time datetime="2024-01-15">Jan 15, 2024</time>
            <span class="author">John Doe</span>
            <p>Main article content here.</p>
            <p>More article content.</p>
            <p>Even more content.</p>
            <p>Additional paragraph.</p>
            <p>Final paragraph.</p>
        </article>
        <section id="comments">
            <h2>Comments</h2>
            <div class="comment">Great article!</div>
        </section>
        </body></html>
        """
        result = classifier.classify(html, "https://blog.example.com/post/123")

        # Should still classify as article despite comments section
        assert result.page_type == PageType.ARTICLE


    def test_wiki_with_navigation(self, classifier):
        """Wiki pages with navigation should classify as knowledge."""
        html = """
        <html><body>
        <nav class="sidebar">
            <ul>
                <li><a href="/page1">Page 1</a></li>
                <li><a href="/page2">Page 2</a></li>
            </ul>
        </nav>
        <main class="mw-body">
            <div id="toc">
                <h2>Contents</h2>
                <ul><li>Section 1</li></ul>
            </div>
            <h1>Wiki Article</h1>
            <span class="mw-editsection">[edit]</span>
            <p>Wiki content here.</p>
            <h2>Section 1</h2>
            <h2>Section 2</h2>
            <h2>Section 3</h2>
            <h2>Section 4</h2>
        </main>
        </body></html>
        """
        result = classifier.classify(html)

        # Should classify as knowledge due to wiki structure
        assert result.page_type == PageType.KNOWLEDGE


class TestJapaneseContent:
    """Tests for Japanese content classification."""


    def test_japanese_toc(self, classifier):
        """Japanese 目次 (table of contents) should be detected."""
        html = """
        <html><body>
        <div class="article">
            <h1>技術ドキュメント</h1>
            <div class="toc">
                <h2>目次</h2>
                <ul>
                    <li><a href="#intro">はじめに</a></li>
                    <li><a href="#usage">使用方法</a></li>
                </ul>
            </div>
            <h2 id="intro">はじめに</h2>
            <p>このドキュメントについて説明します。</p>
            <h2 id="usage">使用方法</h2>
            <h2>設定</h2>
            <h2>参考</h2>
            <h2>関連情報</h2>
        </div>
        </body></html>
        """
        result = classifier.classify(html)

        assert result.page_type == PageType.KNOWLEDGE
        assert result.features["knowledge"]["has_toc"] is True


    def test_japanese_registration_required(self, classifier):
        """Japanese 登録が必要 (registration required) should trigger login_wall."""
        html = """
        <html><body>
        <div class="restricted">
            <h1>会員専用ページ</h1>
            <p>このページを閲覧するには登録が必要です。</p>
            <form action="/login">
                <input type="email" name="email">
                <input type="password" name="password">
                <button>ログイン</button>
            </form>
        </div>
        </body></html>
        """
        result = classifier.classify(html)

        assert result.page_type == PageType.LOGIN_WALL


# ============================================================
# Academic classification tests
# ============================================================

class TestAcademicClassification:
    """Tests for academic paper page type detection."""

    def test_arxiv_paper(self, classifier):
        """arXiv-style academic paper should classify as academic."""
        html = """
        <html><body>
        <div class="paper">
            <h1>Deep Learning for Natural Language Processing</h1>
            <div class="authors">
                <span class="author-affiliation">Stanford University</span>
            </div>
            <div id="abstract">
                <h2>Abstract</h2>
                <p>We present a novel approach to...</p>
            </div>
            <div class="doi">DOI: 10.1234/example.2024</div>
            <h2>References</h2>
            <div class="citation">[1] Smith et al., 2023</div>
        </div>
        </body></html>
        """
        result = classifier.classify(html, "https://arxiv.org/abs/2401.12345")

        assert result.page_type == PageType.ACADEMIC
        assert result.features["academic"]["has_abstract"] is True
        assert result.features["academic"]["has_doi"] is True

    def test_jstage_paper(self, classifier):
        """J-STAGE academic paper should classify as academic."""
        html = """
        <html><body>
        <article class="journal-article">
            <h1>自然言語処理における深層学習</h1>
            <div class="abstract">
                <h2>要旨</h2>
                <p>本研究では...</p>
            </div>
            <div class="references">
                <h2>参考文献</h2>
                <div class="citation">1. 山田太郎 (2023)</div>
            </div>
        </article>
        </body></html>
        """
        result = classifier.classify(html, "https://jstage.jst.go.jp/article/example")

        assert result.page_type == PageType.ACADEMIC


# ============================================================
# Report classification tests
# ============================================================

class TestReportClassification:
    """Tests for report/whitepaper page type detection."""

    def test_annual_report(self, classifier):
        """Annual report should classify as report."""
        html = """
        <html><body>
        <div class="annual-report">
            <h1>Annual Report 2023</h1>
            <div class="executive-summary">
                <h2>Executive Summary</h2>
                <p>This year we achieved...</p>
            </div>
            <div class="financial">
                <h2>Financial Highlights</h2>
                <p>Revenue: $10M</p>
                <table class="financials">
                    <tr><td>Q1</td><td>$2.5M</td></tr>
                </table>
            </div>
        </div>
        </body></html>
        """
        result = classifier.classify(html, "https://example.com/ir/annual-report-2023")

        assert result.page_type == PageType.REPORT
        assert result.features["report"]["has_executive_summary"] is True

    def test_japanese_disclosure(self, classifier):
        """Japanese financial disclosure should classify as report."""
        html = """
        <html><body>
        <div class="disclosure">
            <h1>決算短信</h1>
            <p>売上高: 100億円</p>
            <p>営業利益: 10億円</p>
            <table>
                <tr><th>四半期</th><th>売上</th></tr>
                <tr><td>Q1</td><td>25億円</td></tr>
                <tr><td>Q2</td><td>25億円</td></tr>
                <tr><td>Q3</td><td>25億円</td></tr>
            </table>
        </div>
        </body></html>
        """
        result = classifier.classify(html)

        assert result.page_type == PageType.REPORT
        assert result.features["report"]["has_financial_data"] is True


# ============================================================
# Legal classification tests
# ============================================================

class TestLegalClassification:
    """Tests for legal document page type detection."""

    def test_statute(self, classifier):
        """Legal statute should classify as legal."""
        html = """
        <html><body>
        <div class="statute">
            <h1>Personal Information Protection Act</h1>
            <div class="law-text">
                <h2>Article 1 (Purpose)</h2>
                <p>The purpose of this Act is to...</p>
                <h2>Article 2 (Definitions)</h2>
                <p>In this Act, the following terms...</p>
            </div>
        </div>
        </body></html>
        """
        result = classifier.classify(html, "https://e-gov.go.jp/law/12345")

        assert result.page_type == PageType.LEGAL
        assert result.features["legal"]["has_legal_structure"] is True

    def test_japanese_law(self, classifier):
        """Japanese law document should classify as legal."""
        html = """
        <html><body>
        <div class="legal-doc">
            <h1>個人情報の保護に関する法律</h1>
            <div class="条文">
                <p>第一条　この法律は...</p>
                <p>第二条　この法律において...</p>
            </div>
        </div>
        </body></html>
        """
        result = classifier.classify(html)

        assert result.page_type == PageType.LEGAL
        assert result.features["legal"]["has_article_numbers"] is True


# ============================================================
# Product classification tests
# ============================================================

class TestProductClassification:
    """Tests for product page type detection."""

    def test_ecommerce_product(self, classifier):
        """E-commerce product page should classify as product."""
        html = """
        <html><body>
        <div class="product-detail">
            <h1>Wireless Bluetooth Headphones</h1>
            <div class="product-gallery">
                <img src="/product/image1.jpg" data-zoom-image="/product/large1.jpg">
            </div>
            <div class="price">$99.99</div>
            <button class="add-to-cart">Add to Cart</button>
            <div class="specifications">
                <h2>Specifications</h2>
                <table>
                    <tr><td>Battery</td><td>30 hours</td></tr>
                </table>
            </div>
        </div>
        </body></html>
        """
        result = classifier.classify(html, "https://shop.example.com/product/headphones")

        assert result.page_type == PageType.PRODUCT
        assert result.features["product"]["has_price"] is True
        assert result.features["product"]["has_add_to_cart"] is True

    def test_japanese_product(self, classifier):
        """Japanese product page should classify as product."""
        html = """
        <html><body>
        <div class="product-page">
            <h1>ワイヤレスヘッドホン</h1>
            <div class="price">¥12,980</div>
            <button>カートに入れる</button>
            <div class="spec">
                <h2>仕様</h2>
                <p>バッテリー: 30時間</p>
            </div>
        </div>
        </body></html>
        """
        result = classifier.classify(html)

        assert result.page_type == PageType.PRODUCT
        assert result.features["product"]["has_price"] is True


# ============================================================
# Profile classification tests
# ============================================================

class TestProfileClassification:
    """Tests for profile page type detection."""

    def test_company_about(self, classifier):
        """Company about page should classify as profile."""
        html = """
        <html><body>
        <div class="about-us">
            <h1>About Our Company</h1>
            <div class="company-info">
                <p>Founded in 2010, we are a leading provider of...</p>
                <p>Established: 2010</p>
            </div>
            <div class="leadership">
                <h2>Leadership Team</h2>
                <div class="team">
                    <div class="executive">CEO: John Smith</div>
                </div>
            </div>
            <div class="contact">
                <h2>Contact Us</h2>
                <p>Phone: 123-456-7890</p>
            </div>
        </div>
        </body></html>
        """
        result = classifier.classify(html, "https://example.com/about/company")

        assert result.page_type == PageType.PROFILE
        assert result.features["profile"]["has_about_section"] is True
        assert result.features["profile"]["has_team_section"] is True

    def test_japanese_company_profile(self, classifier):
        """Japanese company profile should classify as profile."""
        html = """
        <html><body>
        <div class="corporate">
            <h1>会社概要</h1>
            <div class="company-info">
                <p>設立: 2010年</p>
                <p>資本金: 1億円</p>
            </div>
            <div class="team">
                <h2>経営陣</h2>
                <p>代表取締役: 山田太郎</p>
            </div>
            <div class="contact">
                <h2>お問い合わせ</h2>
                <p>TEL: 03-1234-5678</p>
            </div>
        </div>
        </body></html>
        """
        result = classifier.classify(html)

        assert result.page_type == PageType.PROFILE
        assert result.features["profile"]["has_company_info"] is True


# ============================================================
# Other classification tests
# ============================================================

class TestOtherClassification:
    """Tests for OTHER page type (unclassifiable pages)."""

    def test_minimal_content(self, classifier):
        """Minimal content should classify as OTHER."""
        html = """
        <html><body>
        <div>
            <p>Hello World</p>
        </div>
        </body></html>
        """
        result = classifier.classify(html)

        assert result.page_type == PageType.OTHER
        assert "no strong classification signals" in result.reason

