"""Shared AI-provider configuration helpers.

Extracted from ``AIChatController.get_default_model`` /
``_get_provider_preferences`` so that Chess Log Charts and AI Summary
share a single definition of "is an LLM available."

All functions accept a plain ``user_settings`` dict (the value returned by
``UserSettingsService.get_settings()``) and have no side effects.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from app.services.ai_service import AIProvider


def is_ai_configured(user_settings: Dict[str, Any]) -> bool:
    """Return True if at least one AI provider is fully configured and active."""
    return resolve_default_provider(user_settings) is not None


def resolve_default_provider(
    user_settings: Dict[str, Any],
) -> Optional[Tuple[AIProvider, str, str, Optional[str]]]:
    """Return ``(provider, model, api_key, base_url_override)`` for the active provider.

    Returns ``None`` if no provider is configured and active.
    ``base_url_override`` is non-None only for the ``custom`` provider.

    Mirrors the provider-preference logic from ``AIChatController``:
    - The active provider is read from ``ai_summary.use_*_models`` toggles.
    - If zero or multiple are True the fallback is OpenAI (same as the controller).
    - Custom additionally requires ``enabled=True`` and a non-empty ``base_url``.
    """
    ai_settings = user_settings.get("ai_models", {})
    ai_summary = user_settings.get("ai_summary", {})

    use_openai = bool(ai_summary.get("use_openai_models", True))
    use_anthropic = bool(ai_summary.get("use_anthropic_models", False))
    use_custom = bool(ai_summary.get("use_custom_models", False))

    # Enforce exactly one active provider; fall back to OpenAI
    if sum([use_openai, use_anthropic, use_custom]) != 1:
        use_openai, use_anthropic, use_custom = True, False, False

    if use_openai:
        s = ai_settings.get("openai", {})
        api_key = s.get("api_key") or ""
        model = s.get("model") or ""
        if api_key and model:
            return (AIProvider.OPENAI, model, api_key, None)

    if use_anthropic:
        s = ai_settings.get("anthropic", {})
        api_key = s.get("api_key") or ""
        model = s.get("model") or ""
        if api_key and model:
            return (AIProvider.ANTHROPIC, model, api_key, None)

    if use_custom:
        s = ai_settings.get("custom", {})
        base_url = (s.get("base_url") or "").strip()
        model = s.get("model") or ""
        api_key = s.get("api_key") or ""
        if s.get("enabled", False) and base_url and model:
            return (AIProvider.CUSTOM, model, api_key, base_url)

    return None
