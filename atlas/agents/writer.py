from __future__ import annotations

from atlas.agents.llm import run_role_json

SYSTEM_PROMPT = """You are the Writer agent in a personal knowledge-graph query pipeline.
Given a question and the full text of the wiki notes retrieved for it, write the answer.

Rules:
- Write the answer as well-organized markdown (use ## subheadings, tables, lists where they
  help). Cite the notes you drew from using Obsidian wikilink syntax, e.g. [[concepts/<slug>]]
  or [[library/<slug>]].
- If coverage is "insufficient", say plainly what the wiki doesn't cover instead of
  fabricating an answer from general knowledge. Note what topic would need to be added to
  the wiki to answer this properly.
- Also write a one-sentence summary of the answer: plain text, ONE sentence, no line breaks,
  no markdown formatting. This is for a scannable log a human skims, not the full answer --
  compress to the actual bottom line (e.g. "Use git worktrees for isolation; escalate to
  explicit locking only once sessions actually collide," not a restatement of the question).
- Separately, decide if this Q&A produced a genuinely new key_finding worth folding back into
  the wiki as permanent knowledge -- a real insight, comparison, or connection, not just a
  restatement of something a note already says. If so, also name a target_concept: the slug
  of ONE concept (from the concept_slugs you were given as context, never a new one) that
  this finding belongs in. If there's no new finding, or no single existing concept it
  cleanly belongs to, set both to null.

Respond with ONLY a JSON object (no markdown fences, no commentary) of this form:
{
  "answer_markdown": "the full answer",
  "summary": "one plain sentence, no line breaks",
  "key_finding": "a short paragraph capturing the new insight, or null",
  "target_concept": "concept-slug" | null
}
"""

MAX_CHARS = 150_000


def write(question: str, concept_bodies: dict[str, str], library_bodies: dict[str, str], coverage: str) -> dict:
    parts = [f"Question: {question}", f"Coverage: {coverage}", ""]
    for slug, body in concept_bodies.items():
        parts.append(f"--- CONCEPT: {slug} ---\n{body}")
    for slug, body in library_bodies.items():
        parts.append(f"--- LIBRARY NOTE: {slug} ---\n{body}")

    user_prompt = "\n\n".join(parts)[:MAX_CHARS]
    result = run_role_json("writer", SYSTEM_PROMPT, user_prompt)
    return {
        "answer_markdown": result.get("answer_markdown", ""),
        "summary": result.get("summary", ""),
        "key_finding": result.get("key_finding"),
        "target_concept": result.get("target_concept"),
    }
