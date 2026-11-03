from __future__ import annotations

from atlas.agents.llm import run_role_json

SYSTEM_PROMPT = """You are the Summarizer agent in a personal knowledge-graph pipeline.
Given the raw text of a single source document, produce a concise, faithful summary
note for a personal Obsidian wiki.

Respond with ONLY a JSON object (no markdown fences, no commentary) of this form:
{
  "title": "short descriptive title",
  "tags": ["lowercase-kebab-tag", ...],
  "summary": "a well-organized markdown summary of the source, several paragraphs, using ## subheadings if useful"
}
"""

MAX_CHARS = 100_000


def summarize(extracted: dict) -> dict:
    user_prompt = (
        f"Source filename: {extracted['source']}\n"
        f"Guessed title: {extracted['title']}\n\n"
        f"--- RAW TEXT ---\n{extracted['text'][:MAX_CHARS]}"
    )
    if extracted.get("reference"):
        user_prompt += (
            "\n\n--- NOTE ---\nThis source is itself a list of concrete, discrete examples "
            "(e.g. real hooks/quotes/data points) meant to be read directly by other agents, "
            "not distilled into general lessons. Preserve the actual examples close to "
            "verbatim in your summary -- exact wording and any stats given -- rather than "
            "paraphrasing or abstracting patterns away from them."
        )
    return run_role_json("summarizer", SYSTEM_PROMPT, user_prompt)
