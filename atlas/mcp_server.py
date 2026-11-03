from __future__ import annotations

from fastmcp import FastMCP

from atlas.orchestrator.ingest import run_ingest_url
from atlas.orchestrator.query import run_ask
from atlas.util import git_commit

mcp = FastMCP(name="atlas")


@mcp.tool
def ask_knowledge_graph(
    question: str,
    caller: str = "unknown",
    file_back: bool = False,
    conversation_id: str = "",
) -> dict:
    """Ask the user's personal knowledge graph (Atlas) a question and get a cited answer.

    This wiki covers only the sources the user has ingested into it -- NOT general
    trivia or facts outside that scope. If the response's `coverage` field is "insufficient", the wiki
    doesn't have material on this question; `answer_markdown` will say so plainly rather
    than fabricating an answer, and nothing gets filed back into the wiki in that case.

    Args:
        question: The question to ask, in plain English.
        caller: Who's asking (e.g. your agent/session name). Recorded in the output
            artifact -- the knowledge graph has no other way to know which agent is
            querying it.
        file_back: If the answer surfaces a genuinely new insight tied to one existing
            concept in the wiki, fold it back in permanently. Default False -- this adds
            a third sequential LLM call (see latency note below), so only set True when
            you actually want to persist a finding, not for routine lookups.
        conversation_id: PASS THIS, and the same value, on every call within one
            conversation/session -- every question asked with the same conversation_id
            is appended into ONE output file instead of creating a new file per
            question. If you're calling this repeatedly while building/debugging
            something, a stable id here (e.g. your session id) is what keeps the
            wiki's output/ directory from filling up with one file per lookup.

    Returns:
        answer_markdown: the full cited answer.
        coverage: "sufficient" or "insufficient".
        sources: concept/library note slugs the answer drew from.
        output_path: repo-relative path of the saved answer artifact (shared across
            every question in this conversation_id, or this calendar day if omitted).
        filed_back / filed_back_path: whether and where a new finding was folded back.

    Note: this can be slow. Answering chains 2 sequential LLM calls (retrieval, writing) by
    default, or 3 with file_back=True (adds concept synthesis), each with its own timeout
    of up to 300s -- worst case ~900s with file_back=True. The MCP host's per-call timeout
    for this server must comfortably exceed that; a past incident here was exactly this
    mismatch (host gave up mid-call, server got parked after exhausting its retry budget).
    """
    result = run_ask(
        question, file_back=file_back, caller=caller, conversation_id=conversation_id or None
    )

    paths = [result["output_path"]]
    if result["filed_back_path"]:
        paths.append(result["filed_back_path"])
    git_commit(f"ask: {result['question_slug']} (via {caller})", paths=paths)

    return result


@mcp.tool
def add_source(url: str, caller: str = "unknown") -> dict:
    """Ingest a URL into the knowledge graph permanently, through the same pipeline
    every other source goes through (summarize, categorize, link, synthesize into
    concept articles) -- not a one-off note.

    Use this after ask_knowledge_graph returns coverage: "insufficient" and your own
    research (e.g. a web search) found a good source for the question: hand the URL
    back here so the finding compounds the wiki instead of staying a one-off answer.

    Args:
        url: A URL to a page worth permanently absorbing into the wiki.
        caller: Who's adding this (e.g. your agent/session name). Used in the git
            commit message for provenance.

    Returns:
        status: "ingested" (new content processed), "already_up_to_date" (this URL
            was already ingested, nothing changed), or "failed" (couldn't extract
            usable text from the page).
        raw_path / library_path / concept_paths: repo-relative paths written, when
            status is "ingested".
        primary_concepts / related_concepts: which concept(s) this source was filed
            under.

    Note: this is slower than ask_knowledge_graph -- it's the full ingest chain
    (extract, summarize, categorize, link, concept-synthesize), several sequential
    LLM calls via claude_cli, each with up to a 300s timeout.
    """
    result = run_ingest_url(url)
    if result["status"] == "ingested":
        git_commit(f"ingest (via {caller}): {result['raw_path']}", paths=result["touched_paths"])
    return result


if __name__ == "__main__":
    mcp.run()  # stdio transport by default
