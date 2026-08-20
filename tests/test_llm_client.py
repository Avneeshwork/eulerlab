"""The model client: configuration, and refusing to leak or to guess.

No test here makes a network call. What is worth testing is the surrounding
contract — that keys are never stored in the repository, that a missing key
produces an actionable message, and that a malformed reply is reported rather
than raising a KeyError from inside a helper.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from eulerlab.llm.client import (
    LLMConfig,
    LLMUnavailable,
    Provider,
    _extract,
    health,
    load_config,
)

CONFIG = Path(__file__).resolve().parents[1] / "config" / "llm.yaml"


def test_the_committed_config_parses() -> None:
    assert load_config(CONFIG).providers


def test_the_default_provider_exists() -> None:
    config = load_config(CONFIG)
    assert config.get().name == config.default


def test_the_default_needs_no_key() -> None:
    """The out-of-the-box experience must not require signing up for anything.
    A default that needs a key makes the feature look broken on first contact."""
    assert load_config(CONFIG).get().api_key_var is None


def test_no_api_key_is_committed() -> None:
    """`api_key_var` names an environment variable. A value here would be a
    secret published to the git remote."""
    text = CONFIG.read_text(encoding="utf-8")
    for provider in load_config(CONFIG).providers:
        if provider.api_key_var:
            assert f"{provider.api_key_var}=" not in text
            assert f"{provider.api_key_var}:" not in text


def test_at_least_one_free_provider_needs_nothing() -> None:
    assert any(p.free and not p.api_key_var for p in load_config(CONFIG).providers)


def test_an_unknown_provider_lists_the_real_ones() -> None:
    with pytest.raises(LLMUnavailable, match="Configured:"):
        load_config(CONFIG).get("gpt-9")


def test_an_unknown_config_key_is_rejected() -> None:
    """A typo in the provider config must stop, not be silently ignored."""
    with pytest.raises(ValueError, match="extra"):
        LLMConfig.model_validate(
            {
                "default": "x",
                "providers": [{"name": "x", "base_url": "u", "model": "m", "tempratur": 1}],
            }
        )


def test_a_missing_key_says_what_to_do(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MADE_UP_KEY", "")
    provider = Provider(name="p", base_url="https://x", model="m", api_key_var="MADE_UP_KEY")
    config = LLMConfig(default="p", providers=[provider])
    reported = health(config)[0]
    assert not reported["ready"]
    assert "MADE_UP_KEY" in reported["reason"]


def test_health_does_not_send_a_request(monkeypatch: pytest.MonkeyPatch) -> None:
    """On a metered provider, probing to answer a question nobody asked spends
    the operator's quota."""

    def explode(*args: object, **kwargs: object) -> None:
        raise AssertionError("health() made a network call")

    monkeypatch.setattr("urllib.request.urlopen", explode)
    assert health(load_config(CONFIG))


def test_a_reply_with_no_choices_is_reported_clearly() -> None:
    with pytest.raises(LLMUnavailable, match="no choices"):
        _extract({"error": "model overloaded"})


def test_a_reply_with_empty_content_is_reported_clearly() -> None:
    with pytest.raises(LLMUnavailable, match="no message content"):
        _extract({"choices": [{"message": {"content": "  "}}]})


def test_a_good_reply_is_extracted() -> None:
    assert _extract({"choices": [{"message": {"content": " hello "}}]}) == "hello"
