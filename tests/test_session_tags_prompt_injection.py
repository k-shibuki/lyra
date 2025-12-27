from __future__ import annotations

import re

from src.utils.prompt_manager import render_prompt


def _extract_lyra_tag_pair(rendered: str) -> tuple[str, str]:
    # Find <LYRA-...> ... </LYRA-...>
    open_match = re.search(r"<(LYRA-[0-9a-f]{32})>", rendered)
    assert open_match is not None, "Expected an opening <LYRA-...> tag"
    tag_name = open_match.group(1)
    close_tag = f"</{tag_name}>"
    assert close_tag in rendered, "Expected a matching closing </LYRA-...> tag"
    return (f"<{tag_name}>", close_tag)


def test_render_prompt_injects_session_tags_by_default(monkeypatch) -> None:
    # Given: default ON (explicitly set to avoid test env surprises)
    monkeypatch.setenv("LYRA_LLM__SESSION_TAGS_ENABLED", "true")
    from src.utils.config import get_settings

    get_settings.cache_clear()

    # When: rendering a real template via render_prompt()
    rendered = render_prompt("extract_facts", text="UNTRUSTED_TEXT_ABC")

    # Then: tags are present and the input text is enclosed by the tag pair
    open_tag, close_tag = _extract_lyra_tag_pair(rendered)
    assert open_tag in rendered
    assert close_tag in rendered
    assert (
        rendered.index(open_tag) < rendered.index("UNTRUSTED_TEXT_ABC") < rendered.index(close_tag)
    )


def test_render_prompt_can_disable_session_tags(monkeypatch) -> None:
    # Given: session tags disabled via env
    monkeypatch.setenv("LYRA_LLM__SESSION_TAGS_ENABLED", "false")
    from src.utils.config import get_settings

    get_settings.cache_clear()

    # When
    rendered = render_prompt("extract_facts", text="UNTRUSTED_TEXT_ABC")

    # Then
    assert "<LYRA-" not in rendered
    assert "UNTRUSTED_TEXT_ABC" in rendered


def test_render_prompt_does_not_override_explicit_tag_vars(monkeypatch) -> None:
    # Given: even if enabled, explicit vars should win (caller-controlled)
    monkeypatch.setenv("LYRA_LLM__SESSION_TAGS_ENABLED", "true")
    from src.utils.config import get_settings

    get_settings.cache_clear()

    # When
    rendered = render_prompt(
        "extract_facts",
        text="UNTRUSTED_TEXT_ABC",
        session_tag_open="<LYRA-00000000000000000000000000000000>",
        session_tag_close="</LYRA-00000000000000000000000000000000>",
    )

    # Then
    assert "<LYRA-00000000000000000000000000000000>" in rendered
    assert "</LYRA-00000000000000000000000000000000>" in rendered
