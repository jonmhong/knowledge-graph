from __future__ import annotations

import json
import subprocess

from atlas.backends.base import Backend


class ClaudeCLIBackend(Backend):
    """Shells out to headless `claude -p` for a single prompt/response round trip."""

    def run(self, system_prompt: str, user_prompt: str) -> str:
        cmd = [
            "claude",
            "-p",
            user_prompt,
            "--output-format",
            "json",
            "--system-prompt",
            system_prompt,
            "--permission-mode",
            "dontAsk",
        ]
        if self.model and self.model != "default":
            cmd += ["--model", self.model]

        # stdin=DEVNULL: without this, the child inherits whatever this process's
        # own stdin is. When atlas is running as an MCP stdio server, that's the
        # MCP protocol pipe itself, not a terminal or empty input -- `claude -p`'s
        # stdin auto-detection stalls and fails against it. Explicitly closing
        # stdin here matches running `claude -p ... </dev/null` by hand.
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=300, stdin=subprocess.DEVNULL
        )
        if result.returncode != 0:
            raise RuntimeError(f"claude CLI failed: {result.stderr.strip()}")

        payload = json.loads(result.stdout)
        return payload["result"]
