from __future__ import annotations

import frontmatter

from atlas import config
from atlas.agents.llm import run_role_json

SYSTEM_PROMPT = """You are the Retriever agent in a personal knowledge-graph query pipeline.
Given a question and a compact index of everything in the wiki (every concept article and,
under each, the library notes filed under it), decide what's worth reading in full to answer
the question.

Guidance:
- Prefer concept articles over individual library notes -- a concept article is already a
  synthesized summary of everything known about that topic, so it's usually enough on its
  own. Only pull specific library notes when the question needs source-level detail a concept
  article wouldn't contain (e.g. "what did source X specifically say about...").
- If nothing in the index looks genuinely relevant to the question, return empty lists and
  mark coverage "insufficient" rather than picking something tangential.

Respond with ONLY a JSON object (no markdown fences, no commentary) of this form:
{
  "concept_slugs": ["slug", ...],
  "library_slugs": ["slug", ...],
  "coverage": "sufficient" | "insufficient"
}
"""


def _build_index() -> str:
    """Cheap, deterministic index: concept articles with their member library notes.

    Same data indexer.rebuild_index() computes for MOC.md, returned as text for a
    prompt instead of written to a file -- this is the "read index/ first, cheap"
    step from SPEC.md, and the reason no embeddings are needed at this scale.
    """
    library_dir = config.vault_path("library")
    concepts_dir = config.vault_path("concepts")

    notes_by_concept: dict[str, list[str]] = {}
    for note_path in sorted(library_dir.glob("*.md")):
        post = frontmatter.load(note_path)
        title = post.get("title", note_path.stem)
        tags = ", ".join(post.get("tags", []))
        label = f"{note_path.stem}: {title}" + (f" (tags: {tags})" if tags else "")
        for concept_slug in post.get("concepts", []) or []:
            notes_by_concept.setdefault(concept_slug, []).append(label)

    lines = []
    for concept_path in sorted(concepts_dir.glob("*.md")):
        slug = concept_path.stem
        title = frontmatter.load(concept_path).get("title", slug.replace("-", " ").title())
        lines.append(f"## {slug}: {title}")
        for label in notes_by_concept.get(slug, []):
            lines.append(f"- {label}")
        lines.append("")
    return "\n".join(lines)


def retrieve(question: str) -> dict:
    index_text = _build_index()
    user_prompt = f"Question: {question}\n\n--- WIKI INDEX ---\n{index_text}"
    result = run_role_json("retriever", SYSTEM_PROMPT, user_prompt)
    return {
        "concept_slugs": result.get("concept_slugs", []),
        "library_slugs": result.get("library_slugs", []),
        "coverage": result.get("coverage", "insufficient"),
    }
