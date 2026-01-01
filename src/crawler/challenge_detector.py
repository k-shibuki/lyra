"""Challenge page detection for URL fetcher."""


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
        # Medium: Requires simple user interaction
        "turnstile": "medium",  # Usually just a click/checkbox
        # High: Requires significant user effort
        "captcha": "high",
        "recaptcha": "high",
        "hcaptcha": "high",
        "login": "high",
    }

    return effort_map.get(challenge_type, "medium")
