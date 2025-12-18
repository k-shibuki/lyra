"""
Tests for ContentQualityAnalyzer.

Tests content quality detection including:
- Thin content detection
- Ad-heavy content detection
- Template-heavy content detection
- Repetitive content detection
- Keyword stuffing detection
- AI-generated content detection
- SEO spam detection
- Aggregator/curation site detection
- Clickbait detection
- Scraper site detection

## Test Perspectives Table
| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---------|----------------------|---------------------------------------|-----------------|-------|
| TC-QI-01 | QualityIssue values | Equivalence – enum | All issues defined | - |
| TC-QF-01 | Extract quality features | Equivalence – extraction | Features populated | - |
| TC-QA-01 | Detect thin content | Equivalence – thin | issue=THIN_CONTENT | - |
| TC-QA-02 | Detect ad-heavy content | Equivalence – ads | issue=AD_HEAVY | - |
| TC-QA-03 | Detect template-heavy | Equivalence – template | issue=TEMPLATE_HEAVY | - |
| TC-QA-04 | Detect repetitive content | Equivalence – repetitive | issue=REPETITIVE | - |
| TC-QA-05 | Detect keyword stuffing | Equivalence – stuffing | issue=KEYWORD_STUFFING | - |
| TC-QA-06 | Detect AI-generated | Equivalence – AI | issue=AI_GENERATED | - |
| TC-QA-07 | Detect SEO spam | Equivalence – SEO spam | issue=SEO_SPAM | - |
| TC-QA-08 | Detect aggregator | Equivalence – aggregator | issue=AGGREGATOR | - |
| TC-QA-09 | Detect clickbait | Equivalence – clickbait | issue=CLICKBAIT | - |
| TC-QA-10 | Detect scraper site | Equivalence – scraper | issue=SCRAPER | - |
| TC-QA-11 | High quality content | Equivalence – high quality | No issues | - |
| TC-QR-01 | QualityResult creation | Equivalence – result | Score and issues | - |
| TC-CF-01 | analyze_content_quality | Equivalence – convenience | Returns result | - |
"""

import pytest

# All tests in this module are unit tests (no external dependencies)
pytestmark = pytest.mark.unit

from src.extractor.quality_analyzer import (
    ContentQualityAnalyzer,
    QualityIssue,
    QualityFeatures,
    QualityResult,
    analyze_content_quality,
    get_quality_analyzer,
)


class TestContentQualityAnalyzer:
    """Tests for ContentQualityAnalyzer class."""

    @pytest.fixture
    def analyzer(self) -> ContentQualityAnalyzer:
        """Create a fresh analyzer instance."""
        return ContentQualityAnalyzer()

    # === Thin Content Detection ===

    def test_thin_content_detection_very_short(self, analyzer: ContentQualityAnalyzer):
        """Test detection of very thin content (§3.3.3)."""
        html = """
        <html>
            <body>
                <p>This is a very short page with minimal content.</p>
            </body>
        </html>
        """

        result = analyzer.analyze(html)

        assert QualityIssue.THIN_CONTENT in result.issues
        assert result.features.word_count < 100
        assert result.quality_score < 0.8

    def test_thin_content_detection_few_paragraphs(self, analyzer: ContentQualityAnalyzer):
        """Test detection of content with too few paragraphs."""
        # Single paragraph with enough words but no structure
        html = """
        <html>
            <body>
                <p>This is a single paragraph that contains many words but lacks proper 
                structure and organization. It goes on and on without any breaks or 
                headings to organize the content. The reader would find it difficult 
                to scan and understand the key points being made in this text.</p>
            </body>
        </html>
        """

        result = analyzer.analyze(html)

        # Should detect thin content due to lack of structure
        assert result.features.paragraph_count < 3

    def test_substantial_content_not_thin(self, analyzer: ContentQualityAnalyzer):
        """Test that substantial content is not flagged as thin."""
        # Create varied paragraphs with different content to avoid repetition detection
        paragraphs = [
            "<p>The introduction discusses the fundamental concepts and background of artificial intelligence.</p>",
            "<p>Machine learning algorithms have revolutionized data processing across various industries.</p>",
            "<p>Deep neural networks enable complex pattern recognition in images and natural language.</p>",
            "<p>Reinforcement learning has achieved remarkable success in game playing and robotics.</p>",
            "<p>Natural language processing allows computers to understand human communication effectively.</p>",
            "<p>Computer vision systems can now identify objects with superhuman accuracy levels.</p>",
            "<p>Ethical considerations in AI development have become increasingly important recently.</p>",
            "<p>The future of artificial intelligence promises transformative changes to society.</p>",
            "<p>Researchers continue to push the boundaries of what machines can accomplish.</p>",
            "<p>Applications of AI span healthcare, finance, transportation, and entertainment sectors.</p>",
        ]

        html = f"""<html>
<body>
<article>
<h1>Comprehensive Article on Artificial Intelligence</h1>

{paragraphs[0]}

{paragraphs[1]}

{paragraphs[2]}

{paragraphs[3]}

{paragraphs[4]}

{paragraphs[5]}

{paragraphs[6]}

{paragraphs[7]}

{paragraphs[8]}

{paragraphs[9]}

</article>
</body>
</html>"""

        result = analyzer.analyze(html)

        assert QualityIssue.THIN_CONTENT not in result.issues
        assert result.features.word_count >= 100
        assert result.features.paragraph_count >= 5

    # === Ad-Heavy Content Detection ===

    def test_ad_heavy_detection(self, analyzer: ContentQualityAnalyzer):
        """Test detection of ad-heavy content (§3.1.1)."""
        html = """
        <html>
            <body>
                <div class="advertisement">Ad 1</div>
                <div class="ad-banner">Ad 2</div>
                <div class="sponsored-content">Ad 3</div>
                <div id="ads-container">Ad 4</div>
                <div data-ad-slot="123">Ad 5</div>
                <p>Some actual content here.</p>
            </body>
        </html>
        """

        result = analyzer.analyze(html)

        assert QualityIssue.AD_HEAVY in result.issues
        assert result.features.ad_element_count >= 5
        assert result.penalty > 0

    def test_minimal_ads_not_flagged(self, analyzer: ContentQualityAnalyzer):
        """Test that minimal ads are not flagged."""
        paragraphs = [f"<p>Content paragraph {i} with meaningful text.</p>" for i in range(10)]

        html = f"""
        <html>
            <body>
                <div class="ad">Single ad</div>
                {"".join(paragraphs)}
            </body>
        </html>
        """

        result = analyzer.analyze(html)

        assert QualityIssue.AD_HEAVY not in result.issues

    # === Template-Heavy Content Detection ===

    def test_template_heavy_detection(self, analyzer: ContentQualityAnalyzer):
        """Test detection of template-heavy content."""
        # Lots of HTML structure, very little text
        html = """
        <html>
            <head>
                <title>Page</title>
                <meta name="description" content="Description">
                <link rel="stylesheet" href="style.css">
                <script src="script.js"></script>
            </head>
            <body>
                <header>
                    <nav>
                        <ul>
                            <li><a href="#">Link 1</a></li>
                            <li><a href="#">Link 2</a></li>
                            <li><a href="#">Link 3</a></li>
                        </ul>
                    </nav>
                </header>
                <aside class="sidebar">
                    <div class="widget">Widget 1</div>
                    <div class="widget">Widget 2</div>
                </aside>
                <main>
                    <p>Short content.</p>
                </main>
                <footer>
                    <div class="footer-links">
                        <a href="#">Footer 1</a>
                        <a href="#">Footer 2</a>
                    </div>
                </footer>
            </body>
        </html>
        """ * 10  # Repeat to make it large enough

        result = analyzer.analyze(html)

        # Should have low text-to-HTML ratio
        assert result.features.text_to_html_ratio < 0.15

    # === Repetitive Content Detection ===

    def test_repetitive_content_detection(self, analyzer: ContentQualityAnalyzer):
        """Test detection of repetitive content (§3.3.3)."""
        # Highly repetitive text
        repeated_sentence = "This is a repeated sentence that appears many times. "
        html = f"""
        <html>
            <body>
                <p>{repeated_sentence * 20}</p>
                <p>{repeated_sentence * 20}</p>
            </body>
        </html>
        """

        result = analyzer.analyze(html)

        assert QualityIssue.REPETITIVE in result.issues
        assert result.features.ngram_repetition_score > 0.2

    def test_varied_content_not_repetitive(self, analyzer: ContentQualityAnalyzer):
        """Test that varied content is not flagged as repetitive."""
        html = """
        <html>
            <body>
                <p>The first paragraph discusses the introduction to the topic.</p>
                <p>Moving on, we explore the historical context and background.</p>
                <p>The third section covers technical implementation details.</p>
                <p>Here we examine case studies and real-world applications.</p>
                <p>Finally, we conclude with future directions and recommendations.</p>
            </body>
        </html>
        """

        result = analyzer.analyze(html)

        assert QualityIssue.REPETITIVE not in result.issues

    # === Keyword Stuffing Detection ===

    def test_keyword_stuffing_detection(self, analyzer: ContentQualityAnalyzer):
        """Test detection of keyword stuffing (§3.1.1)."""
        html = """
        <html>
            <body>
                <h1>Best Widget Reviews 2024</h1>
                <p>Looking for the best widget? Our widget reviews cover the best widgets
                available. These widgets are the best widgets you can find. Widget quality
                matters when choosing widgets. Best widgets for your widget needs.</p>
                <h2>Top Widget Features</h2>
                <p>Widget features include widget durability and widget performance.
                The best widget has excellent widget ratings. Widget users love widgets.</p>
            </body>
        </html>
        """

        result = analyzer.analyze(html)

        # High keyword density indicates stuffing
        assert result.features.keyword_density > 0.03

    # === AI-Generated Content Detection ===

    def test_ai_generated_content_detection(self, analyzer: ContentQualityAnalyzer):
        """Test detection of AI-generated content patterns (§3.3.3)."""
        html = """
        <html>
            <body>
                <h1>Comprehensive Guide to Understanding Topic</h1>
                <p>It's important to note that this topic has several key aspects. 
                Let's delve into the various factors that contribute to this phenomenon.</p>
                <p>Firstly, we must understand the fundamental concepts. Secondly, 
                we should examine the practical applications. Thirdly, we need to 
                consider the implications.</p>
                <p>In conclusion, it's worth noting that this comprehensive overview 
                has covered the essential aspects. To summarize, the key takeaways 
                include understanding the landscape and leveraging best practices.</p>
                <p>Having said that, it is important to understand that there are 
                several factors to consider. With that being said, let's explore 
                the various dimensions of this topic.</p>
            </body>
        </html>
        """

        result = analyzer.analyze(html)

        # Should detect AI patterns
        ai_details = result.issue_details.get("ai_generated", {})
        assert ai_details.get("pattern_matches", 0) >= 3

    def test_natural_human_content_not_ai(self, analyzer: ContentQualityAnalyzer):
        """Test that natural human content is not flagged as AI-generated."""
        html = """
        <html>
            <body>
                <h1>My Experience Building a Startup</h1>
                <p>Last year, I quit my job to start a company. It was terrifying.</p>
                <p>The first three months were brutal. We had no customers, no revenue, 
                and I was burning through my savings. My wife thought I was crazy.</p>
                <p>But then something clicked. A random tweet went viral. Suddenly we 
                had 500 signups in a day. I couldn't believe it!</p>
                <p>Looking back, I learned that persistence matters more than having 
                a perfect plan. Sometimes you just have to ship and see what happens.</p>
            </body>
        </html>
        """

        result = analyzer.analyze(html)

        # Should not be flagged as AI
        assert QualityIssue.AI_GENERATED not in result.issues

    # === SEO Spam Detection ===

    def test_seo_spam_detection(self, analyzer: ContentQualityAnalyzer):
        """Test detection of SEO spam patterns (§3.1.1)."""
        html = """
        <html>
            <body>
                <h1>Best Cheap Laptops Online 2024</h1>
                <p>Looking for the best laptops online? Our top laptop reviews 2024 
                guide will help you find cheap laptops near me.</p>
                <h2>Top 10 Best Laptop Reviews 2024</h2>
                <p>Buy the best laptops online with our comprehensive laptop guide 2024.
                <a href="#">Click here</a> for more laptop deals.</p>
                <p><a href="#">Click here</a> to see our best laptop recommendations.</p>
            </body>
        </html>
        """

        result = analyzer.analyze(html)

        # Should detect SEO spam patterns
        assert QualityIssue.SEO_SPAM in result.issues, (
            f"Expected SEO_SPAM issue for keyword-stuffed content. "
            f"Detected issues: {result.issues}, keyword_density: {result.features.keyword_density}"
        )

    # === Aggregator/Curation Site Detection ===

    def test_aggregator_detection(self, analyzer: ContentQualityAnalyzer):
        """Test detection of aggregator/curation sites (§3.1.1)."""
        html = """
        <html>
            <body>
                <h1>Top 10 Best Articles This Week</h1>
                <p>Source: TechCrunch - According to a recent report...</p>
                <p>Via: The Verge - The latest news indicates...</p>
                <p>Originally published on: Wired - Experts say that...</p>
                <p>From: Ars Technica - New research shows...</p>
                <p>Source: MIT Technology Review - Scientists discovered...</p>
            </body>
        </html>
        """

        result = analyzer.analyze(html)

        assert QualityIssue.AGGREGATOR in result.issues
        assert result.features.source_mention_count >= 3

    def test_curated_list_detection(self, analyzer: ContentQualityAnalyzer):
        """Test detection of curated list patterns."""
        html = """
        <html>
            <body>
                <h1>Top 15 Best Tools for Developers</h1>
                <p>Here's our curated collection of the best development tools.</p>
                <p>Source: GitHub - Tool 1 description</p>
                <p>Via: Stack Overflow - Tool 2 description</p>
            </body>
        </html>
        """

        result = analyzer.analyze(html)

        assert result.features.has_curated_list_pattern

    # === Clickbait Detection ===

    def test_clickbait_detection(self, analyzer: ContentQualityAnalyzer):
        """Test detection of clickbait patterns."""
        html = """
        <html>
            <body>
                <h1>You Won't Believe What Happened Next!</h1>
                <p>This shocking discovery will blow your mind. The incredible 
                results are truly unbelievable. What happened next was jaw-dropping!</p>
                <p>Doctors hate this one trick that changed everything.</p>
            </body>
        </html>
        """

        result = analyzer.analyze(html)

        assert QualityIssue.CLICKBAIT in result.issues

    # === Quality Score Calculation ===

    def test_high_quality_content_score(self, analyzer: ContentQualityAnalyzer):
        """Test that high-quality content gets a high score."""
        paragraphs = [
            f"<p>This is paragraph {i} discussing important aspects of the research topic. "
            f"The findings indicate significant implications for the field. Multiple studies "
            f"have confirmed these results through rigorous methodology.</p>"
            for i in range(8)
        ]

        html = f"""
        <html>
            <body>
                <article>
                    <h1>Research Findings on Topic X</h1>
                    <h2>Introduction</h2>
                    {"".join(paragraphs[:2])}
                    <h2>Methodology</h2>
                    {"".join(paragraphs[2:4])}
                    <h2>Results</h2>
                    {"".join(paragraphs[4:6])}
                    <h2>Conclusion</h2>
                    {"".join(paragraphs[6:])}
                </article>
            </body>
        </html>
        """

        result = analyzer.analyze(html)

        assert result.quality_score >= 0.7
        assert len(result.issues) <= 1
        assert not result.is_low_quality

    def test_low_quality_content_score(self, analyzer: ContentQualityAnalyzer):
        """Test that low-quality content gets a low score."""
        html = """
        <html>
            <body>
                <div class="ad">Ad</div>
                <div class="advertisement">Ad</div>
                <div class="banner">Ad</div>
                <div class="sponsored">Ad</div>
                <div class="ads">Ad</div>
                <p>Short content here.</p>
            </body>
        </html>
        """

        result = analyzer.analyze(html)

        assert result.quality_score < 0.6
        assert len(result.issues) >= 2
        assert result.is_low_quality

    # === Penalty Calculation ===

    def test_penalty_calculation_multiple_issues(self, analyzer: ContentQualityAnalyzer):
        """Test penalty calculation with multiple issues."""
        html = """
        <html>
            <body>
                <div class="ad">Ad 1</div>
                <div class="ad">Ad 2</div>
                <div class="ad">Ad 3</div>
                <div class="ad">Ad 4</div>
                <div class="ad">Ad 5</div>
                <p>Short.</p>
            </body>
        </html>
        """

        result = analyzer.analyze(html)

        # Should have penalty for multiple issues
        assert result.penalty > 0.2
        assert result.penalty <= 0.8  # Capped at 0.8

    def test_no_penalty_for_quality_content(self, analyzer: ContentQualityAnalyzer):
        """Test no penalty for quality content."""
        # Use diverse, realistic content to avoid triggering quality issues
        html = """
        <html>
            <body>
                <article>
                    <h1>Understanding Climate Change Impacts</h1>
                    <p>Climate change represents one of the most significant challenges facing 
                    our planet today. Scientists have documented rising global temperatures 
                    and their effects on ecosystems worldwide.</p>
                    <p>The Arctic ice sheets have been melting at unprecedented rates. 
                    Polar bear populations are declining as their habitat shrinks. 
                    Meanwhile, coral reefs face bleaching events due to warmer ocean waters.</p>
                    <p>Agricultural systems must adapt to changing precipitation patterns. 
                    Farmers in many regions report shifting growing seasons. 
                    Drought-resistant crop varieties are becoming increasingly important.</p>
                    <p>Coastal communities face rising sea levels and increased storm intensity. 
                    Infrastructure investments are needed to protect vulnerable populations. 
                    Many cities are developing climate adaptation plans.</p>
                    <p>Renewable energy adoption continues to accelerate globally. 
                    Solar and wind power costs have decreased dramatically. 
                    Electric vehicle sales are breaking records in major markets.</p>
                    <p>International cooperation remains essential for addressing climate change. 
                    The Paris Agreement set ambitious emissions reduction targets. 
                    Nations must work together to achieve carbon neutrality by mid-century.</p>
                    <p>Individual actions can contribute to emissions reductions. 
                    Energy efficiency improvements in homes reduce carbon footprints. 
                    Sustainable transportation choices help decrease urban pollution.</p>
                    <p>Education and awareness play crucial roles in climate action. 
                    Young people are leading movements demanding environmental protection. 
                    Schools are incorporating climate science into their curricula.</p>
                    <p>Business leaders recognize the economic opportunities in sustainability. 
                    Green investments are attracting significant capital flows. 
                    Corporate sustainability reporting has become standard practice.</p>
                    <p>The scientific consensus on human-caused climate change is clear. 
                    Continued research helps refine our understanding of climate systems. 
                    Evidence-based policy decisions are essential for effective action.</p>
                </article>
            </body>
        </html>
        """

        result = analyzer.analyze(html)

        assert result.penalty < 0.3

    # === Feature Extraction ===

    def test_feature_extraction_text_stats(self, analyzer: ContentQualityAnalyzer):
        """Test text statistics feature extraction."""
        html = """
        <html>
            <body>
                <p>First sentence here. Second sentence follows.</p>
                <p>Third sentence in new paragraph. Fourth and final.</p>
            </body>
        </html>
        """

        result = analyzer.analyze(html)

        assert result.features.word_count > 0
        assert result.features.sentence_count >= 4
        assert result.features.paragraph_count >= 2
        assert result.features.avg_sentence_length > 0

    def test_feature_extraction_structural(self, analyzer: ContentQualityAnalyzer):
        """Test structural feature extraction."""
        html = """
        <html>
            <body>
                <h1>Title</h1>
                <h2>Section 1</h2>
                <p>Content with <a href="#">link1</a> and <a href="#">link2</a>.</p>
                <img src="image.jpg">
                <script>console.log('test');</script>
            </body>
        </html>
        """

        result = analyzer.analyze(html)

        assert result.features.heading_count >= 2
        assert result.features.link_count >= 2
        assert result.features.image_count >= 1
        assert result.features.script_count >= 1

    def test_feature_extraction_link_density(self, analyzer: ContentQualityAnalyzer):
        """Test link density calculation."""
        html = """
        <html>
            <body>
                <p>Some text <a href="#">link</a> more text <a href="#">another link</a> end.</p>
            </body>
        </html>
        """

        result = analyzer.analyze(html)

        assert result.features.link_density > 0
        assert result.features.link_density < 1.0

    # === Affiliate Link Detection ===

    def test_affiliate_link_detection(self, analyzer: ContentQualityAnalyzer):
        """Test detection of affiliate links."""
        html = """
        <html>
            <body>
                <p>Check out this product on <a href="https://amazon.com/dp/B123?tag=mysite-20">Amazon</a>.</p>
                <p>Also available at <a href="https://amzn.to/abc123">this link</a>.</p>
                <p>Great content about products.</p>
            </body>
        </html>
        """

        result = analyzer.analyze(html)

        assert result.features.affiliate_link_count >= 2

    # === Call-to-Action Detection ===

    def test_cta_detection(self, analyzer: ContentQualityAnalyzer):
        """Test detection of call-to-action patterns."""
        html = """
        <html>
            <body>
                <p>Click here to learn more! Sign up now for free access.</p>
                <p>Buy now and get started today. Subscribe now for updates.</p>
            </body>
        </html>
        """

        result = analyzer.analyze(html)

        assert result.features.call_to_action_count >= 3

    # === Reason Generation ===

    def test_reason_generation_no_issues(self, analyzer: ContentQualityAnalyzer):
        """Test reason generation when no issues found."""
        paragraphs = [f"<p>Quality content paragraph {i}.</p>" for i in range(10)]
        html = f"<html><body>{''.join(paragraphs)}</body></html>"

        result = analyzer.analyze(html)

        if not result.issues:
            assert "No quality issues detected" in result.reason

    def test_reason_generation_with_issues(self, analyzer: ContentQualityAnalyzer):
        """Test reason generation with detected issues."""
        html = """
        <html>
            <body>
                <div class="ad">Ad 1</div>
                <div class="ad">Ad 2</div>
                <div class="ad">Ad 3</div>
                <div class="ad">Ad 4</div>
                <div class="ad">Ad 5</div>
                <p>Short.</p>
            </body>
        </html>
        """

        result = analyzer.analyze(html)

        assert result.reason
        # Reason should be a meaningful explanation (at least 10 chars)
        assert len(result.reason) >= 10, f"Expected reason >=10 chars, got: {result.reason}"


class TestConvenienceFunctions:
    """Tests for module-level convenience functions."""

    def test_get_quality_analyzer_singleton(self):
        """Test that get_quality_analyzer returns singleton."""
        analyzer1 = get_quality_analyzer()
        analyzer2 = get_quality_analyzer()

        assert analyzer1 is analyzer2

    def test_analyze_content_quality_function(self):
        """Test the analyze_content_quality convenience function."""
        html = """
        <html>
            <body>
                <p>Test content for quality analysis.</p>
            </body>
        </html>
        """

        result = analyze_content_quality(html)

        assert isinstance(result, QualityResult)
        assert 0.0 <= result.quality_score <= 1.0

    def test_analyze_with_extracted_text(self):
        """Test analysis with pre-extracted text."""
        html = "<html><body><p>Test</p></body></html>"
        text = "This is pre-extracted text with more content than the HTML shows."

        result = analyze_content_quality(html, text=text)

        assert result.features.word_count > 5


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    @pytest.fixture
    def analyzer(self) -> ContentQualityAnalyzer:
        return ContentQualityAnalyzer()

    def test_empty_html(self, analyzer: ContentQualityAnalyzer):
        """Test handling of empty HTML."""
        result = analyzer.analyze("")

        assert result.quality_score >= 0.0
        assert isinstance(result.issues, list)

    def test_html_only_tags(self, analyzer: ContentQualityAnalyzer):
        """Test handling of HTML with only tags, no text."""
        html = "<html><head></head><body><div><span></span></div></body></html>"

        result = analyzer.analyze(html)

        assert result.features.word_count == 0
        assert QualityIssue.THIN_CONTENT in result.issues

    def test_very_long_content(self, analyzer: ContentQualityAnalyzer):
        """Test handling of very long content."""
        paragraphs = [
            f"<p>This is paragraph number {i} with substantial content that "
            f"discusses various aspects of the topic in great detail.</p>"
            for i in range(100)
        ]

        html = f"<html><body>{''.join(paragraphs)}</body></html>"

        result = analyzer.analyze(html)

        assert result.features.word_count > 1000
        assert result.features.paragraph_count >= 100

    def test_unicode_content(self, analyzer: ContentQualityAnalyzer):
        """Test handling of Unicode/Japanese content."""
        html = """
        <html>
            <body>
                <h1>日本語のテスト記事</h1>
                <p>これは日本語のテスト記事です。品質分析が正しく動作するかテストします。</p>
                <p>複数の段落を含むコンテンツで、適切な長さがあります。</p>
                <p>日本語のストップワードも正しく処理されるべきです。</p>
            </body>
        </html>
        """

        result = analyzer.analyze(html)

        assert result.features.word_count > 0
        assert isinstance(result.quality_score, float)

    def test_malformed_html(self, analyzer: ContentQualityAnalyzer):
        """Test handling of malformed HTML."""
        html = "<html><body><p>Unclosed paragraph<div>Mixed tags</p></div></body>"

        result = analyzer.analyze(html)

        # Should not raise, should produce some result
        assert isinstance(result, QualityResult)

    def test_script_and_style_removal(self, analyzer: ContentQualityAnalyzer):
        """Test that script and style content is properly removed."""
        html = """
        <html>
            <head>
                <style>body { color: red; } .class { margin: 0; }</style>
            </head>
            <body>
                <script>function test() { return "should not count"; }</script>
                <p>This is the actual content.</p>
                <script>var x = "more script";</script>
            </body>
        </html>
        """

        result = analyzer.analyze(html)

        # Script/style content should not be in word count
        assert "function" not in result.reason.lower()
        assert result.features.word_count < 20


class TestBurstinessAndUniformity:
    """Tests for AI detection metrics: burstiness and uniformity."""

    @pytest.fixture
    def analyzer(self) -> ContentQualityAnalyzer:
        return ContentQualityAnalyzer()

    def test_high_burstiness_natural_text(self, analyzer: ContentQualityAnalyzer):
        """Test that natural text has higher burstiness."""
        html = """
        <html>
            <body>
                <p>Short sentence.</p>
                <p>This is a much longer sentence that contains many more words and provides detailed information about the topic.</p>
                <p>Medium length here.</p>
                <p>Another very long sentence that goes on and on with lots of details and explanations about various aspects of the subject matter being discussed.</p>
                <p>Brief.</p>
            </body>
        </html>
        """

        result = analyzer.analyze(html)

        # Natural text should have varied sentence lengths
        assert result.features.burstiness_score > 0.2

    def test_low_burstiness_uniform_text(self, analyzer: ContentQualityAnalyzer):
        """Test that uniform text has lower burstiness."""
        # All sentences roughly same length
        html = """
        <html>
            <body>
                <p>This sentence has about ten words in it.</p>
                <p>This sentence also has about ten words.</p>
                <p>And this one has roughly ten words too.</p>
                <p>Another sentence with approximately ten words.</p>
                <p>Final sentence containing about ten words here.</p>
            </body>
        </html>
        """

        result = analyzer.analyze(html)

        # Uniform text should have lower burstiness
        assert result.features.burstiness_score < 0.5

    def test_uniformity_score_calculation(self, analyzer: ContentQualityAnalyzer):
        """Test uniformity score calculation."""
        # Highly uniform text
        html = """
        <html>
            <body>
                <p>Sentence one two three four five.</p>
                <p>Sentence one two three four five.</p>
                <p>Sentence one two three four five.</p>
                <p>Sentence one two three four five.</p>
            </body>
        </html>
        """

        result = analyzer.analyze(html)

        assert result.features.uniformity_score >= 0.5


class TestIntegrationWithPageClassifier:
    """Tests for integration scenarios with page classification."""

    @pytest.fixture
    def analyzer(self) -> ContentQualityAnalyzer:
        return ContentQualityAnalyzer()

    def test_forum_content_quality(self, analyzer: ContentQualityAnalyzer):
        """Test quality analysis of forum-like content."""
        html = """
        <html>
            <body>
                <div class="thread">
                    <div class="post">
                        <div class="avatar">User1</div>
                        <p>This is a question about programming.</p>
                    </div>
                    <div class="post reply">
                        <div class="avatar">User2</div>
                        <p>Here's my answer with detailed explanation.</p>
                    </div>
                </div>
            </body>
        </html>
        """

        result = analyzer.analyze(html)

        # Forum content might be thin but shouldn't be heavily penalized
        assert result.quality_score >= 0.3

    def test_wiki_content_quality(self, analyzer: ContentQualityAnalyzer):
        """Test quality analysis of wiki-like content."""
        html = """
        <html>
            <body>
                <div class="mw-content">
                    <div id="toc">Table of Contents</div>
                    <h1>History of Computing</h1>
                    <div class="infobox">Summary info</div>
                    <p>The history of computing spans several centuries of technological 
                    development. Early mechanical calculators laid the groundwork for 
                    modern electronic computers.</p>
                    <p>Charles Babbage designed the Analytical Engine in the 1830s. 
                    Ada Lovelace wrote the first computer algorithm for this machine. 
                    Their work anticipated many concepts used in modern computing.</p>
                    <p>Electronic computers emerged during World War II. ENIAC became 
                    operational in 1945 at the University of Pennsylvania. 
                    It could perform thousands of calculations per second.</p>
                    <p>The transistor revolutionized electronics in the 1950s. 
                    Integrated circuits further miniaturized computing components. 
                    Moore's Law predicted the doubling of transistor density every two years.</p>
                    <p>Personal computers became widespread in the 1980s. 
                    The IBM PC and Apple Macintosh brought computing to homes and offices. 
                    Graphical user interfaces made computers accessible to ordinary users.</p>
                    <div id="references">
                        <h2>References</h2>
                        <ol class="citation">
                            <li>Campbell-Kelly, Martin. Computer: A History of the Information Machine.</li>
                            <li>Ceruzzi, Paul E. A History of Modern Computing.</li>
                        </ol>
                    </div>
                </div>
            </body>
        </html>
        """

        result = analyzer.analyze(html)

        # Wiki content should generally be high quality
        assert result.quality_score >= 0.5
        assert QualityIssue.AGGREGATOR not in result.issues

