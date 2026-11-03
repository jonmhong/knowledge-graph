from __future__ import annotations

import os

from anthropic import Anthropic

from atlas.backends.base import Backend

DEFAULT_MODEL = "claude-sonnet-5"


class AnthropicAPIBackend(Backend):
    """Direct Anthropic API call using a standalone ANTHROPIC_API_KEY (no Claude Code)."""

    def __init__(self, model: str | None = None) -> None:
        super().__init__(model)
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set")
        self._client = Anthropic(api_key=api_key)

    def run(self, system_prompt: str, user_prompt: str) -> str:
        model = self.model if self.model and self.model != "default" else DEFAULT_MODEL
        message = self._client.messages.create(
            model=model,
            max_tokens=4096,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        return "".join(block.text for block in message.content if block.type == "text")
