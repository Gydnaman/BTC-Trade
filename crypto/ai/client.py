"""Optional model-client contract; this project iteration performs no network calls."""


class UnconfiguredClient:
    """Deterministic fallback used until a provider is configured explicitly."""

    provider = "unconfigured"
    model = "none"

    def complete(self, system_prompt: str, user_prompt: str):
        del system_prompt, user_prompt
        raise RuntimeError("no LLM provider is configured")
