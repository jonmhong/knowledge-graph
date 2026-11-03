from __future__ import annotations

from atlas import config
from atlas.agents.llm import run_role_json

SYSTEM_PROMPT = """You are the Categorizer agent in a personal knowledge-graph pipeline.
Given a summarized source note and the list of concept articles that already exist in the
wiki, decide how this note relates to concepts -- distinguishing:

- primary_concepts: concept(s) this note is CENTRALLY about. Its content will be fully
  integrated into these concept articles. Prefer reusing an existing concept over creating
  a new one; only propose a new concept if nothing existing fits. Most notes have exactly
  one primary concept -- use more than one only if the note is genuinely, substantially
  about multiple topics, not just because it touches on them in passing.
- related_concepts: concept(s) this note genuinely connects to or illustrates, but is NOT
  centrally about. These get a cross-link only, not full integration -- use this for real
  but secondary connections instead of dropping them entirely. related_concepts must only
  reference concepts that ALREADY exist in the wiki (a brand-new concept can only be a
  primary_concept, never introduced as merely related).

Respond with ONLY a JSON object (no markdown fences, no commentary) of this form:
{
  "primary_concepts": ["Concept Name", ...],
  "related_concepts": ["Concept Name", ...]
}
Concept names should be Title Case and short (2-5 words).
"""


def existing_concepts() -> list[str]:
    concepts_dir = config.vault_path("concepts")
    return sorted(p.stem.replace("-", " ").title() for p in concepts_dir.glob("*.md"))



def categorize(summary: dict) -> dict:
    concepts = existing_concepts()
    user_prompt = (
        f"Title: {summary['title']}\n"
        f"Tags: {', '.join(summary.get('tags', []))}\n\n"
        f"Summary:\n{summary['summary']}\n\n"
        f"Existing concepts in the wiki: {concepts if concepts else 'none yet'}"
    )
    result = run_role_json("categorizer", SYSTEM_PROMPT, user_prompt)
    return {
        "primary": result.get("primary_concepts", []),
        "related": result.get("related_concepts", []),
    }
