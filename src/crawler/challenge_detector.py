"""Challenge page detection for URL fetcher.

Provides detection functions for various authentication challenges:
- CAPTCHA (reCAPTCHA, hCaptcha, Turnstile)
- Cloudflare challenges (JS challenge, browser verification)
- Login requirements
- Cookie consent banners
"""


def _detect_login_required(content: str) -> bool:
    """Detect if page requires login/authentication.

    This function identifies login forms and authentication walls by looking for:
    - Password input fields (strong indicator)
    - Login form elements and containers
    - Authentication-related text

    Note: This function is conservative to avoid false positives on pages
    that merely mention login or have sidebar login widgets.

    Args:
        content: Page HTML content.

    Returns:
        True if login requirement detected.
    """
    content_lower = content.lower()

    # Strong indicators: password field is the primary signal
    # Password input field is almost always present on login pages
    password_indicators = [
        'type="password"',
        "type='password'",
        'type=password',
    ]

    has_password_field = any(ind in content_lower for ind in password_indicators)

    if not has_password_field:
        # No password field = likely not a login page
        return False

    # With password field present, check for login-specific context
    # to avoid false positives on pages with embedded login widgets
    login_form_indicators = [
        'id="login',
        'class="login',
        'name="login',
        'id="signin',
        'class="signin',
        'action="/login',
        'action="/signin',
        'action="/auth',
        # Japanese
        'id="ログイン',
        'class="ログイン',
    ]

    # Text indicators for login walls (main content, not sidebar)
    login_wall_text = [
        "please sign in",
        "please log in",
        "login required",
        "sign in required",
        "authentication required",
        "you must be logged in",
        "you need to log in",
        "please login to continue",
        "sign in to continue",
        "ログインしてください",
        "ログインが必要です",
        "サインインしてください",
        "会員登録が必要です",
    ]

    # Check for login form context
    if any(ind in content_lower for ind in login_form_indicators):
        return True

    # Check for login wall text
    if any(text in content_lower for text in login_wall_text):
        return True

    # Additional check: small page with password field is likely a login page
    if len(content) < 50000 and has_password_field:
        # Check for common login page title patterns
        title_patterns = [
            "<title>login",
            "<title>log in",
            "<title>sign in",
            "<title>signin",
            "<title>ログイン",
            "<title>サインイン",
        ]
        if any(pattern in content_lower for pattern in title_patterns):
            return True

    return False


def _detect_cookie_consent(content: str) -> bool:
    """Detect if page shows a cookie consent banner/dialog.

    Cookie consent banners (GDPR/CCPA compliance) are different from
    authentication challenges. They typically don't block content access
    but may overlay the page.

    Args:
        content: Page HTML content.

    Returns:
        True if cookie consent banner detected.
    """
    content_lower = content.lower()

    # Cookie consent widget/library indicators
    # These are specific library identifiers that indicate active consent dialogs
    consent_library_indicators = [
        "cookieconsent",  # Cookie Consent library
        "cookie-consent",
        "cookie_consent",
        "onetrust",  # OneTrust consent manager
        "cookiebot",  # Cookiebot
        "cookie-notice",
        "cookie-banner",
        "cookie-policy-banner",
        "gdpr-cookie",
        "ccpa-notice",
        "privacy-consent",
        "consent-banner",
        "consent-dialog",
        "consent-modal",
        # Class/ID patterns for consent overlays
        'class="cc-',  # Cookie Consent library prefix
        'id="cc-',
        'class="cky-',  # CookieYes prefix
        'id="cky-',
    ]

    if any(ind in content_lower for ind in consent_library_indicators):
        return True

    # Cookie consent text patterns (must be combined with button indicators)
    consent_text_patterns = [
        "we use cookies",
        "this site uses cookies",
        "this website uses cookies",
        "accept cookies",
        "accept all cookies",
        "cookie settings",
        "cookie preferences",
        "manage cookies",
        "customize cookies",
        "reject all cookies",
        "decline cookies",
        # GDPR/CCPA specific
        "gdpr compliance",
        "privacy preferences",
        "your privacy choices",
        "do not sell my personal information",
        # Japanese
        "cookieを使用",
        "クッキーを使用",
        "cookie設定",
        "クッキー設定",
        "すべて許可",
        "すべて拒否",
    ]

    # Button indicators that typically accompany consent dialogs
    consent_button_patterns = [
        "accept all",
        "accept cookies",
        "i agree",
        "i accept",
        "got it",
        "ok, i agree",
        "agree and proceed",
        "同意する",
        "許可する",
        "受け入れる",
    ]

    # Need both text AND button pattern to reduce false positives
    has_consent_text = any(text in content_lower for text in consent_text_patterns)
    has_consent_button = any(btn in content_lower for btn in consent_button_patterns)

    return has_consent_text and has_consent_button


def _is_challenge_page(content: str, headers: dict) -> bool:
    """Check if page is a challenge/captcha page.

    This function uses specific patterns to avoid false positives from:
    - Cookie consent banners that reference CAPTCHA services
    - Article content mentioning CAPTCHA/security topics
    - Third-party scripts with CAPTCHA-related URLs

    Args:
        content: Page content.
        headers: Response headers.

    Returns:
        True if challenge detected.
    """
    content_lower = content.lower()

    # Cloudflare challenge page indicators (highly specific)
    # These patterns indicate an ACTIVE challenge, not just a reference
    cloudflare_challenge_indicators = [
        "cf-browser-verification",  # Cloudflare verification element
        "_cf_chl_opt",  # Cloudflare challenge options
        "checking your browser before accessing",  # Challenge text
        "please wait while we verify your browser",  # Challenge text
        "ray id:</strong>",  # Challenge page format (not just "cloudflare ray id")
    ]

    if any(ind in content_lower for ind in cloudflare_challenge_indicators):
        return True

    # Check for "Just a moment" + Cloudflare combination (challenge page title)
    if "just a moment" in content_lower and (
        "cloudflare" in content_lower or "_cf_" in content_lower
    ):
        return True

    # CAPTCHA widget indicators (must be active widgets, not references)
    # Look for iframe sources or specific widget containers
    active_captcha_indicators = [
        'src="https://hcaptcha.com',  # hCaptcha iframe
        'src="https://www.hcaptcha.com',
        "data-sitekey=",  # CAPTCHA widget with sitekey
        'class="h-captcha"',  # hCaptcha container element
        'class="g-recaptcha"',  # reCAPTCHA container element
        'id="captcha-container"',  # Explicit captcha container
        "grecaptcha.execute",  # reCAPTCHA v3 execution
        "hcaptcha.execute",  # hCaptcha execution
    ]

    if any(ind in content_lower for ind in active_captcha_indicators):
        return True

    # Turnstile indicators (Cloudflare's CAPTCHA alternative)
    turnstile_indicators = [
        'class="cf-turnstile"',  # Turnstile widget container
        "challenges.cloudflare.com/turnstile",  # Turnstile script URL
    ]

    if any(ind in content_lower for ind in turnstile_indicators):
        return True

    # Server header check - only for small pages (challenge pages are typically tiny)
    server = headers.get("server", "").lower()
    if "cloudflare" in server:
        cf_ray = headers.get("cf-ray")
        # Challenge pages are very small (< 5KB) and have cf-ray header
        if cf_ray and len(content) < 5000:
            # Additional check: challenge pages have minimal HTML structure
            if "<body" in content_lower and content_lower.count("<div") < 10:
                return True

    return False


def _detect_challenge_type(content: str) -> str:
    """Detect the specific type of challenge from page content.

    This function is called AFTER _is_challenge_page() returns True,
    so we know the page is a challenge page. This determines the type.

    Args:
        content: Page HTML content.

    Returns:
        Challenge type string.
    """
    content_lower = content.lower()

    # Check for specific challenge types in order of specificity
    # Use same specific patterns as _is_challenge_page for consistency
    if (
        'class="cf-turnstile"' in content_lower
        or "challenges.cloudflare.com/turnstile" in content_lower
    ):
        return "turnstile"

    if 'src="https://hcaptcha.com' in content_lower or 'class="h-captcha"' in content_lower:
        return "hcaptcha"

    if 'class="g-recaptcha"' in content_lower or "grecaptcha.execute" in content_lower:
        return "recaptcha"

    if "data-sitekey=" in content_lower:
        # Generic CAPTCHA with sitekey - check for type indicators
        if "hcaptcha" in content_lower:
            return "hcaptcha"
        if "recaptcha" in content_lower:
            return "recaptcha"
        return "captcha"

    # Cloudflare challenge indicators
    cloudflare_indicators = [
        "cf-browser-verification",
        "_cf_chl_opt",
        "checking your browser before accessing",
    ]
    if any(ind in content_lower for ind in cloudflare_indicators):
        return "cloudflare"

    # Generic JS challenge (Cloudflare "Just a moment" page)
    if "just a moment" in content_lower and "cloudflare" in content_lower:
        return "js_challenge"

    return "cloudflare"  # Default for unidentified challenges


def detect_auth_challenge(content: str, headers: dict | None = None) -> tuple[str | None, str]:
    """Detect any authentication challenge in page content.

    This is the main entry point for challenge detection. It checks for all
    types of authentication challenges in priority order:
    1. CAPTCHA/Cloudflare challenges (blocking)
    2. Login requirements (blocking)
    3. Cookie consent (non-blocking, but may overlay content)

    Priority is important: CAPTCHA pages may contain login text (e.g., "sign in
    after verification"), so CAPTCHA takes precedence.

    Args:
        content: Page HTML content.
        headers: Optional HTTP response headers.

    Returns:
        Tuple of (challenge_type, effort_level).
        challenge_type is None if no challenge detected.
        challenge_type values: "turnstile", "hcaptcha", "recaptcha", "captcha",
                              "cloudflare", "js_challenge", "login", "cookie_consent"
        effort_level values: "low", "medium", "high"
    """
    if headers is None:
        headers = {}

    # Priority 1: CAPTCHA/Cloudflare challenges
    if _is_challenge_page(content, headers):
        challenge_type = _detect_challenge_type(content)
        effort = _estimate_auth_effort(challenge_type)
        return challenge_type, effort

    # Priority 2: Login requirements
    if _detect_login_required(content):
        return "login", _estimate_auth_effort("login")

    # Priority 3: Cookie consent (lowest priority as it's often non-blocking)
    if _detect_cookie_consent(content):
        return "cookie_consent", _estimate_auth_effort("cookie_consent")

    return None, "low"


def _estimate_auth_effort(challenge_type: str) -> str:
    """Estimate the effort required to complete authentication.

    Provides estimated_effort for auth challenges.

    Args:
        challenge_type: Type of challenge detected.

    Returns:
        Effort level: "low", "medium", or "high".
    """
    # Effort mapping based on typical time/complexity
    effort_map = {
        # Low: Usually auto-resolves or simple click
        "js_challenge": "low",
        "cloudflare": "low",  # Basic Cloudflare often auto-resolves
        "cookie_consent": "low",  # Just a button click
        # Medium: Requires simple user interaction
        "turnstile": "medium",  # Usually just a click/checkbox
        # High: Requires significant user effort
        "captcha": "high",
        "recaptcha": "high",
        "hcaptcha": "high",
        "login": "high",
    }

    return effort_map.get(challenge_type, "medium")
