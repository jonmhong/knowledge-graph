from __future__ import annotations

from datetime import date, datetime

import frontmatter

from atlas import config
from atlas.agents import concept_synth, retriever, writer
from atlas.util import slugify

MAX_NOTE_CHARS = 50_000
SLUG_MAX_LEN = 60


def run_ask(
    question: str,
    file_back: bool = True,
    caller: str = "cli",
    conversation_id: str | None = None,
) -> dict:
    """Answer a question against the wiki, append it to an output artifact, and
    (optionally) fold any new finding back into the relevant concept article.

    Mirrors orchestrator/ingest.py::run_ingest's shape: deterministic file I/O in
    Python, judgment calls delegated to LLM agent roles.

    `caller` identifies which entrypoint/agent is asking (e.g. "cli", or an MCP
    client name) -- MCP has no protocol-level caller identity, so this is recorded
    directly in the output artifact.

    `conversation_id`, when a caller passes one, groups every question asked within
    the same conversation into one output file instead of one file per question --
    this exists because frequent agent-driven querying (multiple calls per build
    task) was producing a new file per call, which is noise, not the compounding
    Karpathy's original design intends. Falls back to one file per calendar day
    when no conversation_id is given (e.g. plain `atlas ask` from the CLI), since a
    caller can't be relied on to pass one consistently (see: `caller` itself
    defaulting to "unknown" from MCP clients in practice) -- the daily grouping needs no
    caller cooperation to still bound file count.
    """
    picks = retriever.retrieve(question)

    concept_bodies = _read_bodies("concepts", picks["concept_slugs"])
    library_bodies = _read_bodies("library", picks["library_slugs"])

    answer = writer.write(question, concept_bodies, library_bodies, picks["coverage"])

    output_filename = _output_filename(conversation_id)
    output_path = _write_output(output_filename, question, answer, picks, caller)

    filed_back_path = None
    if file_back and answer["key_finding"] and answer["target_concept"]:
        if answer["target_concept"] in picks["concept_slugs"]:
            filed_back_path = _file_back(
                answer["target_concept"], output_filename, question, answer["key_finding"]
            )

    return {
        "output_path": output_path,
        "filed_back": filed_back_path is not None,
        "filed_back_path": filed_back_path,
        "question_slug": slugify(question)[:SLUG_MAX_LEN],
        "answer_markdown": answer["answer_markdown"],
        "summary": answer["summary"],
        "coverage": picks["coverage"],
        "sources": picks["concept_slugs"] + picks["library_slugs"],
    }


def _output_filename(conversation_id: str | None) -> str:
    if conversation_id:
        return f"conv-{slugify(conversation_id)[:SLUG_MAX_LEN]}.md"
    return f"{date.today().isoformat()}.md"


def _read_bodies(subdir: str, slugs: list[str]) -> dict[str, str]:
    bodies = {}
    for slug in slugs:
        path = config.vault_path(subdir) / f"{slug}.md"
        if path.exists():
            bodies[slug] = frontmatter.load(path).content[:MAX_NOTE_CHARS]
    return bodies


def _write_output(filename: str, question: str, answer: dict, picks: dict, caller: str) -> str:
    """Append one Q&A entry to the grouped output file (creating it if new).

    One file accumulates every question in the same conversation (or the same
    calendar day, with no conversation_id) rather than one file per question --
    see run_ask's docstring for why. Each entry is ONE line: a human skimming this
    file to see what's been asked should never need to read a full answer here --
    the full `answer_markdown` only goes back in the tool response (for the calling
    agent to use in its own context) and, when there's a real finding, into the
    concept article itself via file_back. This file is a scannable log, not a
    second copy of the answer.
    """
    output_dir = config.vault_path("output")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / filename

    if output_path.exists():
        post = frontmatter.load(output_path)
    else:
        post = frontmatter.Post("")
        post["created"] = date.today().isoformat()
        post["question_count"] = 0

    source_links = [f"[[concepts/{s}]]" for s in picks["concept_slugs"]]
    source_links += [f"[[library/{s}]]" for s in picks["library_slugs"]]
    summary = answer["summary"].strip() or answer["answer_markdown"].split("\n", 1)[0][:200]

    time_tag = datetime.now().strftime("%H:%M")
    caller_tag = f", {caller}" if caller not in ("cli", "unknown") else ""
    entry = (
        f"- **{time_tag}** ({picks['coverage']}{caller_tag}) {question} "
        f"→ {summary}"
        + (f" {' '.join(source_links)}" if source_links else "")
        + "\n"
    )
    post.content = f"{post.content.rstrip()}\n{entry}" if post.content.strip() else entry
    post["question_count"] = post.get("question_count", 0) + 1
    post["last_updated"] = date.today().isoformat()

    output_path.write_text(frontmatter.dumps(post))
    return str(output_path.relative_to(config.REPO_ROOT))


def _file_back(concept_slug: str, output_filename: str, question: str, key_finding: str) -> str | None:
    """Integrate a Q&A finding into a concept article -- the same incremental
    integration concept_synth already does for ingest, given a synthetic 'note'
    standing in for the (now shared, grouped) output artifact instead of a library
    source note. Links to the grouped output file itself, not a per-question one --
    there's no longer a per-question file to point at.

    Returns the touched file's repo-relative path (for a git-add scoped to exactly
    what this run changed), or None if there was nothing to file back into.
    """
    concept_path = config.vault_path("concepts") / f"{concept_slug}.md"
    if not concept_path.exists():
        return None

    current_body = frontmatter.load(concept_path).content
    output_link = f"output/{output_filename[:-3]}"  # strip .md -- wikilinks omit it
    new_note = {"title": question, "link": output_link, "summary": key_finding}
    body = concept_synth.synthesize(concept_path.stem.replace("-", " ").title(), current_body, new_note)

    post = frontmatter.load(concept_path)
    post.content = body
    concept_path.write_text(frontmatter.dumps(post))
    return str(concept_path.relative_to(config.REPO_ROOT))
