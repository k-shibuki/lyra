"""
Tests for challenge page detection.

Test Classification:
- All tests here are unit tests (no external dependencies)
- Tests cover CAPTCHA, login, and cookie consent detection

Requirements tested:
- CAPTCHA detection accuracy (Cloudflare, reCAPTCHA, hCaptcha, Turnstile)
- Login requirement detection
- Cookie consent banner detection
- False positive prevention
- Detection priority handling

## Test Perspectives Table

| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---------|---------------------|---------------------------------------|-----------------|-------|
| TC-CP-N-01 | Cloudflare challenge | Equivalence – normal | is_challenge=True | - |
| TC-CP-N-02 | hCaptcha widget | Equivalence – normal | is_challenge=True | - |
| TC-CP-N-03 | reCAPTCHA widget | Equivalence – normal | is_challenge=True | - |
| TC-CP-N-04 | Turnstile widget | Equivalence – normal | is_challenge=True | - |
| TC-CP-N-05 | JS challenge | Equivalence – normal | is_challenge=True | - |
| TC-CP-A-01 | Normal content | Equivalence – abnormal | is_challenge=False | - |
| TC-CP-A-02 | CAPTCHA mention only | Equivalence – abnormal | is_challenge=False | false positive test |
| TC-CT-N-01 | Cloudflare type | Equivalence – normal | type="cloudflare" | - |
| TC-CT-N-02 | hCaptcha type | Equivalence – normal | type="hcaptcha" | - |
| TC-CT-N-03 | reCAPTCHA type | Equivalence – normal | type="recaptcha" | - |
| TC-CT-N-04 | Turnstile type | Equivalence – normal | type="turnstile" | - |
| TC-LR-N-01 | Login form | Equivalence – normal | login_required=True | - |
| TC-LR-N-02 | Password + login text | Equivalence – normal | login_required=True | - |
| TC-LR-N-03 | Japanese login page | Equivalence – normal | login_required=True | - |
| TC-LR-A-01 | No password field | Equivalence – abnormal | login_required=False | - |
| TC-LR-A-02 | Sidebar login widget | Equivalence – abnormal | login_required=False | false positive test |
| TC-CC-N-01 | Cookie consent banner | Equivalence – normal | cookie_consent=True | - |
| TC-CC-N-02 | GDPR dialog | Equivalence – normal | cookie_consent=True | - |
| TC-CC-N-03 | Japanese cookie banner | Equivalence – normal | cookie_consent=True | - |
| TC-CC-A-01 | No consent button | Equivalence – abnormal | cookie_consent=False | - |
| TC-AC-N-01 | CAPTCHA + login text | Equivalence – priority | type="captcha" | CAPTCHA takes priority |
| TC-AC-N-02 | Login only | Equivalence – normal | type="login" | - |
| TC-AC-N-03 | Cookie only | Equivalence – normal | type="cookie_consent" | - |
| TC-AC-A-01 | Normal page | Equivalence – abnormal | type=None | - |
| TC-EF-N-01 | Effort low | Equivalence – normal | effort="low" | - |
| TC-EF-N-02 | Effort medium | Equivalence – normal | effort="medium" | - |
| TC-EF-N-03 | Effort high | Equivalence – normal | effort="high" | - |
| TC-EF-B-01 | Unknown type | Boundary – default | effort="medium" | - |
| TC-EF-B-02 | Empty string | Boundary – empty | effort="medium" | - |
"""

import pytest

from src.crawler.challenge_detector import (
    _detect_challenge_type,
    _detect_cookie_consent,
    _detect_login_required,
    _estimate_auth_effort,
    _is_challenge_page,
    detect_auth_challenge,
)

# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def cloudflare_challenge_html() -> str:
    """Cloudflare challenge page HTML."""
    return """
    <!DOCTYPE html>
    <html>
    <head><title>Just a moment...</title></head>
    <body>
        <div id="cf-browser-verification">
            <p>Checking your browser before accessing example.com.</p>
            <p>Please wait while we verify your browser.</p>
        </div>
        <script>var _cf_chl_opt = {};</script>
    </body>
    </html>
    """


@pytest.fixture
def hcaptcha_html() -> str:
    """Page with hCaptcha widget."""
    return """
    <!DOCTYPE html>
    <html>
    <head><title>Verify</title></head>
    <body>
        <form>
            <div class="h-captcha" data-sitekey="abc123"></div>
            <script src="https://hcaptcha.com/1/api.js" async defer></script>
        </form>
    </body>
    </html>
    """


@pytest.fixture
def recaptcha_html() -> str:
    """Page with reCAPTCHA widget."""
    return """
    <!DOCTYPE html>
    <html>
    <head><title>Verify</title></head>
    <body>
        <form>
            <div class="g-recaptcha" data-sitekey="abc123"></div>
            <script>grecaptcha.execute('abc123');</script>
        </form>
    </body>
    </html>
    """


@pytest.fixture
def turnstile_html() -> str:
    """Page with Cloudflare Turnstile widget."""
    return """
    <!DOCTYPE html>
    <html>
    <head><title>Verify</title></head>
    <body>
        <form>
            <div class="cf-turnstile" data-sitekey="abc123"></div>
            <script src="https://challenges.cloudflare.com/turnstile/v0/api.js"></script>
        </form>
    </body>
    </html>
    """


@pytest.fixture
def login_page_html() -> str:
    """Standard login page HTML."""
    return """
    <!DOCTYPE html>
    <html>
    <head><title>Login</title></head>
    <body>
        <h1>Please sign in</h1>
        <form id="login-form" action="/login" method="post">
            <input type="text" name="username" placeholder="Username">
            <input type="password" name="password" placeholder="Password">
            <button type="submit">Sign In</button>
        </form>
    </body>
    </html>
    """


@pytest.fixture
def japanese_login_page_html() -> str:
    """Japanese login page HTML."""
    return """
    <!DOCTYPE html>
    <html>
    <head><title>ログイン</title></head>
    <body>
        <h1>ログインしてください</h1>
        <form class="ログイン-form" action="/login" method="post">
            <input type="text" name="username" placeholder="ユーザー名">
            <input type="password" name="password" placeholder="パスワード">
            <button type="submit">ログイン</button>
        </form>
    </body>
    </html>
    """


@pytest.fixture
def cookie_consent_html() -> str:
    """Page with cookie consent banner."""
    return """
    <!DOCTYPE html>
    <html>
    <head><title>Example Site</title></head>
    <body>
        <div class="cookie-consent">
            <p>We use cookies to improve your experience.</p>
            <p>This site uses cookies for analytics and personalization.</p>
            <button>Accept all cookies</button>
            <button>Manage cookies</button>
        </div>
        <main>Main content here</main>
    </body>
    </html>
    """


@pytest.fixture
def gdpr_consent_html() -> str:
    """Page with GDPR consent dialog."""
    return """
    <!DOCTYPE html>
    <html>
    <head><title>Example Site</title></head>
    <body>
        <div id="onetrust-consent">
            <h2>Your Privacy Choices</h2>
            <p>We use cookies to personalize content.</p>
            <button>I agree</button>
            <button>Cookie preferences</button>
        </div>
        <main>Main content here</main>
    </body>
    </html>
    """


@pytest.fixture
def normal_content_html() -> str:
    """Normal page without any challenges."""
    return """
    <!DOCTYPE html>
    <html>
    <head><title>Example Article</title></head>
    <body>
        <article>
            <h1>Understanding CAPTCHA Technology</h1>
            <p>This article discusses how CAPTCHAs work.</p>
            <p>reCAPTCHA is one popular implementation.</p>
            <p>Cloudflare also offers protection services.</p>
        </article>
    </body>
    </html>
    """


# =============================================================================
# CAPTCHA Detection Tests
# =============================================================================


@pytest.mark.unit
class TestChallengePageDetection:
    """Tests for _is_challenge_page function."""

    def test_detect_cloudflare_challenge(self, cloudflare_challenge_html: str) -> None:
        """Test detection of Cloudflare challenge page."""
        # Given: A Cloudflare challenge page HTML
        # When: _is_challenge_page is called
        # Then: True is returned
        result = _is_challenge_page(cloudflare_challenge_html, {})
        assert result is True

    def test_detect_hcaptcha(self, hcaptcha_html: str) -> None:
        """Test detection of hCaptcha widget."""
        # Given: A page with hCaptcha widget
        # When: _is_challenge_page is called
        # Then: True is returned
        result = _is_challenge_page(hcaptcha_html, {})
        assert result is True

    def test_detect_recaptcha(self, recaptcha_html: str) -> None:
        """Test detection of reCAPTCHA widget."""
        # Given: A page with reCAPTCHA widget
        # When: _is_challenge_page is called
        # Then: True is returned
        result = _is_challenge_page(recaptcha_html, {})
        assert result is True

    def test_detect_turnstile(self, turnstile_html: str) -> None:
        """Test detection of Turnstile widget."""
        # Given: A page with Turnstile widget
        # When: _is_challenge_page is called
        # Then: True is returned
        result = _is_challenge_page(turnstile_html, {})
        assert result is True

    def test_no_challenge_normal_content(self, normal_content_html: str) -> None:
        """Test that normal content is not detected as challenge."""
        # Given: A normal article page mentioning CAPTCHA
        # When: _is_challenge_page is called
        # Then: False is returned (no false positive)
        result = _is_challenge_page(normal_content_html, {})
        assert result is False

    def test_cloudflare_header_small_page(self) -> None:
        """Test Cloudflare detection via headers for small pages."""
        # Given: Small HTML with Cloudflare headers
        # When: _is_challenge_page is called
        # Then: True is returned
        small_html = "<html><body><div>Please wait</div></body></html>"
        headers = {"server": "cloudflare", "cf-ray": "abc123"}
        result = _is_challenge_page(small_html, headers)
        assert result is True

    def test_cloudflare_header_large_page_not_challenge(self) -> None:
        """Test that large pages with Cloudflare headers are not marked as challenge."""
        # Given: Large HTML with Cloudflare headers (normal page)
        # When: _is_challenge_page is called
        # Then: False is returned
        large_html = "<html><body>" + "<div>Content</div>" * 1000 + "</body></html>"
        headers = {"server": "cloudflare", "cf-ray": "abc123"}
        result = _is_challenge_page(large_html, headers)
        assert result is False


@pytest.mark.unit
class TestChallengeTypeDetection:
    """Tests for _detect_challenge_type function."""

    def test_detect_cloudflare_type(self, cloudflare_challenge_html: str) -> None:
        """Test detection of Cloudflare challenge type."""
        # Given: A Cloudflare challenge page
        # When: _detect_challenge_type is called
        # Then: "cloudflare" is returned
        result = _detect_challenge_type(cloudflare_challenge_html)
        assert result == "cloudflare"

    def test_detect_hcaptcha_type(self, hcaptcha_html: str) -> None:
        """Test detection of hCaptcha type."""
        # Given: A page with hCaptcha
        # When: _detect_challenge_type is called
        # Then: "hcaptcha" is returned
        result = _detect_challenge_type(hcaptcha_html)
        assert result == "hcaptcha"

    def test_detect_recaptcha_type(self, recaptcha_html: str) -> None:
        """Test detection of reCAPTCHA type."""
        # Given: A page with reCAPTCHA
        # When: _detect_challenge_type is called
        # Then: "recaptcha" is returned
        result = _detect_challenge_type(recaptcha_html)
        assert result == "recaptcha"

    def test_detect_turnstile_type(self, turnstile_html: str) -> None:
        """Test detection of Turnstile type."""
        # Given: A page with Turnstile
        # When: _detect_challenge_type is called
        # Then: "turnstile" is returned
        result = _detect_challenge_type(turnstile_html)
        assert result == "turnstile"

    def test_detect_js_challenge_type(self) -> None:
        """Test detection of JS challenge type."""
        # Given: A Cloudflare "Just a moment" page
        # When: _detect_challenge_type is called
        # Then: "js_challenge" is returned
        html = "<html><title>Just a moment...</title><body>cloudflare</body></html>"
        result = _detect_challenge_type(html)
        assert result == "js_challenge"

    def test_detect_generic_captcha_type(self) -> None:
        """Test detection of generic CAPTCHA with sitekey."""
        # Given: A page with generic CAPTCHA (data-sitekey but no specific type)
        # When: _detect_challenge_type is called
        # Then: "captcha" is returned
        html = '<html><body><div data-sitekey="abc"></div></body></html>'
        result = _detect_challenge_type(html)
        assert result == "captcha"


# =============================================================================
# Login Detection Tests
# =============================================================================


@pytest.mark.unit
class TestLoginDetection:
    """Tests for _detect_login_required function."""

    def test_detect_login_form(self, login_page_html: str) -> None:
        """Test detection of standard login form."""
        # Given: A standard login page with form
        # When: _detect_login_required is called
        # Then: True is returned
        result = _detect_login_required(login_page_html)
        assert result is True

    def test_detect_japanese_login(self, japanese_login_page_html: str) -> None:
        """Test detection of Japanese login page."""
        # Given: A Japanese login page
        # When: _detect_login_required is called
        # Then: True is returned
        result = _detect_login_required(japanese_login_page_html)
        assert result is True

    def test_detect_login_wall_text(self) -> None:
        """Test detection of login wall with text indicator."""
        # Given: A page with login required text and password field
        # When: _detect_login_required is called
        # Then: True is returned
        html = """
        <html>
        <body>
            <h1>Authentication Required</h1>
            <p>You must be logged in to view this content.</p>
            <form>
                <input type="password" name="pass">
            </form>
        </body>
        </html>
        """
        result = _detect_login_required(html)
        assert result is True

    def test_no_login_without_password_field(self) -> None:
        """Test that pages without password field are not detected as login."""
        # Given: A page mentioning login but without password field
        # When: _detect_login_required is called
        # Then: False is returned
        html = """
        <html>
        <body>
            <p>Please sign in to continue</p>
            <a href="/login">Login here</a>
        </body>
        </html>
        """
        result = _detect_login_required(html)
        assert result is False

    def test_no_login_normal_page(self, normal_content_html: str) -> None:
        """Test that normal content is not detected as login requirement."""
        # Given: A normal article page
        # When: _detect_login_required is called
        # Then: False is returned
        result = _detect_login_required(normal_content_html)
        assert result is False

    def test_login_title_detection(self) -> None:
        """Test detection of login page by title."""
        # Given: A small page with login title and password field
        # When: _detect_login_required is called
        # Then: True is returned
        html = """
        <html>
        <head><title>Sign In</title></head>
        <body>
            <form>
                <input type="password">
            </form>
        </body>
        </html>
        """
        result = _detect_login_required(html)
        assert result is True


# =============================================================================
# Cookie Consent Detection Tests
# =============================================================================


@pytest.mark.unit
class TestCookieConsentDetection:
    """Tests for _detect_cookie_consent function."""

    def test_detect_cookie_consent_banner(self, cookie_consent_html: str) -> None:
        """Test detection of cookie consent banner."""
        # Given: A page with cookie consent banner
        # When: _detect_cookie_consent is called
        # Then: True is returned
        result = _detect_cookie_consent(cookie_consent_html)
        assert result is True

    def test_detect_gdpr_dialog(self, gdpr_consent_html: str) -> None:
        """Test detection of GDPR consent dialog."""
        # Given: A page with GDPR consent dialog
        # When: _detect_cookie_consent is called
        # Then: True is returned
        result = _detect_cookie_consent(gdpr_consent_html)
        assert result is True

    def test_detect_cookiebot_library(self) -> None:
        """Test detection of Cookiebot library."""
        # Given: A page with Cookiebot consent manager
        # When: _detect_cookie_consent is called
        # Then: True is returned
        html = """
        <html>
        <body>
            <div id="cookiebot-banner">Cookie settings</div>
        </body>
        </html>
        """
        result = _detect_cookie_consent(html)
        assert result is True

    def test_detect_japanese_cookie_banner(self) -> None:
        """Test detection of Japanese cookie banner."""
        # Given: A page with Japanese cookie consent
        # When: _detect_cookie_consent is called
        # Then: True is returned
        html = """
        <html>
        <body>
            <div class="cookie-banner">
                <p>このサイトはCookieを使用しています。</p>
                <button>すべて許可</button>
            </div>
        </body>
        </html>
        """
        result = _detect_cookie_consent(html)
        assert result is True

    def test_no_cookie_consent_without_button(self) -> None:
        """Test that text without button is not detected as consent."""
        # Given: A page with cookie text but no consent button
        # When: _detect_cookie_consent is called
        # Then: False is returned
        html = """
        <html>
        <body>
            <footer>
                <p>We use cookies to improve your experience.</p>
                <a href="/privacy">Privacy Policy</a>
            </footer>
        </body>
        </html>
        """
        result = _detect_cookie_consent(html)
        assert result is False

    def test_no_cookie_consent_normal_page(self, normal_content_html: str) -> None:
        """Test that normal content is not detected as cookie consent."""
        # Given: A normal article page
        # When: _detect_cookie_consent is called
        # Then: False is returned
        result = _detect_cookie_consent(normal_content_html)
        assert result is False


# =============================================================================
# Integrated Detection Tests
# =============================================================================


@pytest.mark.unit
class TestDetectAuthChallenge:
    """Tests for detect_auth_challenge integration function."""

    def test_detect_captcha_priority(self, hcaptcha_html: str) -> None:
        """Test that CAPTCHA is detected with correct priority."""
        # Given: A page with hCaptcha
        # When: detect_auth_challenge is called
        # Then: "hcaptcha" type is returned with high effort
        challenge_type, effort = detect_auth_challenge(hcaptcha_html)
        assert challenge_type == "hcaptcha"
        assert effort == "high"

    def test_detect_login_when_no_captcha(self, login_page_html: str) -> None:
        """Test login detection when no CAPTCHA present."""
        # Given: A login page without CAPTCHA
        # When: detect_auth_challenge is called
        # Then: "login" type is returned
        challenge_type, effort = detect_auth_challenge(login_page_html)
        assert challenge_type == "login"
        assert effort == "high"

    def test_detect_cookie_consent_lowest_priority(self, cookie_consent_html: str) -> None:
        """Test cookie consent detection with lowest priority."""
        # Given: A page with only cookie consent
        # When: detect_auth_challenge is called
        # Then: "cookie_consent" type is returned
        challenge_type, effort = detect_auth_challenge(cookie_consent_html)
        assert challenge_type == "cookie_consent"
        assert effort == "low"

    def test_no_challenge_detected(self, normal_content_html: str) -> None:
        """Test that normal content returns no challenge."""
        # Given: A normal article page
        # When: detect_auth_challenge is called
        # Then: None type is returned
        challenge_type, effort = detect_auth_challenge(normal_content_html)
        assert challenge_type is None
        assert effort == "low"

    def test_captcha_priority_over_login_text(self) -> None:
        """Test that CAPTCHA takes priority over login text."""
        # Given: A CAPTCHA page that mentions login
        # When: detect_auth_challenge is called
        # Then: CAPTCHA type is returned (not login)
        html = """
        <html>
        <body>
            <p>Please sign in after verification</p>
            <div class="g-recaptcha" data-sitekey="abc"></div>
        </body>
        </html>
        """
        challenge_type, effort = detect_auth_challenge(html)
        assert challenge_type == "recaptcha"
        assert effort == "high"

    def test_with_headers(self, cloudflare_challenge_html: str) -> None:
        """Test challenge detection with headers."""
        # Given: A Cloudflare challenge page with headers
        # When: detect_auth_challenge is called with headers
        # Then: Cloudflare challenge is detected
        headers = {"server": "cloudflare", "cf-ray": "abc123"}
        challenge_type, effort = detect_auth_challenge(cloudflare_challenge_html, headers)
        assert challenge_type == "cloudflare"
        assert effort == "low"


# =============================================================================
# Effort Estimation Tests
# =============================================================================


@pytest.mark.unit
class TestEffortEstimation:
    """Tests for _estimate_auth_effort function."""

    def test_low_effort_js_challenge(self) -> None:
        """Test low effort for JS challenge."""
        # Given: A JS challenge type
        # When: _estimate_auth_effort is called
        # Then: "low" is returned
        result = _estimate_auth_effort("js_challenge")
        assert result == "low"

    def test_low_effort_cookie_consent(self) -> None:
        """Test low effort for cookie consent."""
        # Given: A cookie consent type
        # When: _estimate_auth_effort is called
        # Then: "low" is returned
        result = _estimate_auth_effort("cookie_consent")
        assert result == "low"

    def test_medium_effort_turnstile(self) -> None:
        """Test medium effort for Turnstile."""
        # Given: A Turnstile type
        # When: _estimate_auth_effort is called
        # Then: "medium" is returned
        result = _estimate_auth_effort("turnstile")
        assert result == "medium"

    def test_high_effort_captcha(self) -> None:
        """Test high effort for CAPTCHA."""
        # Given: A CAPTCHA type
        # When: _estimate_auth_effort is called
        # Then: "high" is returned
        result = _estimate_auth_effort("captcha")
        assert result == "high"

    def test_high_effort_login(self) -> None:
        """Test high effort for login."""
        # Given: A login type
        # When: _estimate_auth_effort is called
        # Then: "high" is returned
        result = _estimate_auth_effort("login")
        assert result == "high"

    def test_default_effort_unknown_type(self) -> None:
        """Test default effort for unknown type."""
        # Given: An unknown challenge type
        # When: _estimate_auth_effort is called
        # Then: "medium" is returned (default)
        result = _estimate_auth_effort("unknown_type")
        assert result == "medium"

    def test_default_effort_empty_string(self) -> None:
        """Test default effort for empty string."""
        # Given: An empty string type
        # When: _estimate_auth_effort is called
        # Then: "medium" is returned (default)
        result = _estimate_auth_effort("")
        assert result == "medium"
