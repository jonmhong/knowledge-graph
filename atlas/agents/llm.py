from __future__ import annotations

import json
import re

from atlas import config
from atlas.backends import build_backend

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$")


def run_role(role: str, system_prompt: str, user_prompt: str) -> str:
    spec = config.agent_backend_spec(role)
    backend = build_backend(spec["backend"], model=spec.get("model"))
    return backend.run(system_prompt, user_prompt)


def _extract_json_object(text: str) -> str:
    """Return the outermost balanced {...} span, ignoring braces inside strings.

    Models sometimes wrap the JSON in prose ("Here is the answer:") or trail a
    closing note after it. Slicing to the outermost balanced object drops that
    surrounding junk before we try to parse.
    """
    start = text.find("{")
    if start == -1:
        return text
    depth = 0
    in_str = False
    escaped = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_str = False
        else:
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]
    return text[start:]


def run_role_json(role: str, system_prompt: str, user_prompt: str) -> dict:
    text = run_role(role, system_prompt, user_prompt).strip()
    cleaned = _FENCE_RE.sub("", text).strip()

    # Fast path: strict=False allows raw control characters (e.g. literal
    # newlines/tabs from a code block) inside JSON string values -- models
    # frequently emit these even though strict JSON requires them escaped.
    try:
        return json.loads(cleaned, strict=False)
    except json.JSONDecodeError:
        pass

    # Second try: slice to the outermost balanced object, dropping any prose the
    # model wrapped around the JSON.
    candidate = _extract_json_object(cleaned)
    try:
        return json.loads(candidate, strict=False)
    except json.JSONDecodeError:
        pass

    # Last resort: repair genuinely-malformed JSON (unescaped quotes inside
    # string values, trailing commas, missing brackets) rather than letting the
    # exception propagate and kill the whole tool call / MCP subprocess. A
    # best-effort parse of a long markdown answer beats a dead server.
    from json_repair import repair_json

    repaired = repair_json(candidate, return_objects=True)
    if isinstance(repaired, dict):
        return repaired
    # repair_json returns "" for input it can't make sense of at all.
    raise ValueError(
        f"run_role_json[{role}]: could not parse model output as JSON "
        f"(len={len(text)}); head={text[:200]!r}"
    )
