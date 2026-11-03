# Universe

This vault is a living knowledge graph. Almost none of what you see here was typed by hand — source material goes in, and an agentic pipeline reads, categorizes, cross-links, and writes almost everything else. You are mostly a reader and a director of what gets researched next, not the author.

## Purpose: knowledge that compounds

The point of this system isn't just to store notes — it's that each new piece of source material makes the *existing* knowledge base better, not just bigger. When a new article lands, it doesn't just get filed away next to what's already here: it revises the specific concept articles it touches, folding its content into the accumulated understanding built from every prior source on that topic. The wiki you're looking at at any given moment is the running synthesis of everything ingested so far, always up to date, never a pile of disconnected summaries you'd have to cross-reference yourself.

This is deliberately inspired by Andrej Karpathy's description of using an LLM to compile a personal wiki: collect raw material, let the model compile it into an interlinked `.md` wiki, and query that wiki instead of re-researching from scratch every time. The wager is that at the scale of one person's research interests (dozens to low hundreds of articles), an LLM that's kept the wiki well-organized can answer hard questions directly against it — no separate retrieval infrastructure required.

## Components

- **`raw/`** — the only folder you touch directly. Drop in anything: articles, PDFs, papers, repo links, datasets, images, or a bare URL. This is pure input; nothing here is ever modified by the system.
- **`library/`** — one generated note per item in `raw/`, holding a faithful summary plus metadata (source, tags, date). This is the atomic unit of "what does this one source say."
- **`concepts/`** — synthesized articles, one per topic, each woven together from every `library/` note that's centrally about it. This is where compounding actually happens: a concept article is a living document, incrementally revised every time a new relevant source is ingested, not a static file rewritten from scratch each time.
- **`index/`** *(MOC.md)* — a map of content: every concept, its core member notes, and anything that merely *touches on* it without being centrally about it. This is the front door for figuring out what the wiki already knows before diving into individual notes — read [[index/MOC]] first.
- **`output/`** — a log of the questions you've asked, one line each with links to the notes the answer drew on. Genuinely new insights from an answer get folded back into the matching concept article.

## The agentic system behind it

An orchestrator-subagent pipeline (code name **Atlas**) does the actual reading and writing. For each new item in `raw/`, it runs through a fixed sequence of specialized roles:

1. **Extractor** — pulls plain text out of whatever format landed in `raw/` (including fetching a page's real content if you just dropped in a URL).
2. **Summarizer** — reads the source and writes its `library/` note.
3. **Categorizer** — decides which concept(s) this note is *centrally* about (full integration) versus merely *related to* (a cross-link only) — this distinction is what keeps concept articles focused instead of diluted by every tangential mention.
4. **Concept synthesizer** — revises the relevant concept article(s) to fold in the new note.
5. **Index updater** — refreshes the map of content.

Notably, several of these steps are plain deterministic code, not model calls — extraction, cross-linking, and index rebuilding don't require judgment, only summarizing, categorizing, and synthesizing do. Every step that *is* a model call is routed through a swappable backend (Claude Code or a direct Anthropic API call) purely by config — no code changes needed to point a given role at a different model. When the folder is a git repository, every run is committed, so anything the system gets wrong is a one-line revert away.

The easiest way to run it is the Atlas app: double-click `Start Atlas.command` in the project folder (see the README).
