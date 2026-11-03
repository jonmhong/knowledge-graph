from __future__ import annotations

from atlas.backends.anthropic_api import AnthropicAPIBackend
from atlas.backends.base import Backend
from atlas.backends.claude_cli import ClaudeCLIBackend

_REGISTRY: dict[str, type[Backend]] = {
    "claude_cli": ClaudeCLIBackend,
    "anthropic_api": AnthropicAPIBackend,
}


def build_backend(name: str, model: str | None = None) -> Backend:
    try:
        cls = _REGISTRY[name]
    except KeyError:
        raise ValueError(f"Unknown backend '{name}'. Available: {sorted(_REGISTRY)}") from None
    return cls(model=model)
