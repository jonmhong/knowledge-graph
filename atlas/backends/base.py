from __future__ import annotations

from abc import ABC, abstractmethod


class Backend(ABC):
    """Common interface every model backend implements.

    Swapping a backend (Claude Code CLI, Anthropic API, and later Codex/Grok/Kimi/etc.)
    means adding a new class here and pointing at it from config.yaml -- callers never
    change.
    """

    def __init__(self, model: str | None = None) -> None:
        self.model = model

    @abstractmethod
    def run(self, system_prompt: str, user_prompt: str) -> str:
        """Send a prompt to the model and return its raw text response."""
