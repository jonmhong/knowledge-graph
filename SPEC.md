# Atlas — Architecture & Design Notes

## Context

Inspired by Karpathy's X post on LLM-maintained personal knowledge bases: raw sources go into a `raw/` folder, an LLM incrementally "compiles" them into a wiki of markdown files (summaries, backlinks, concept articles, auto-maintained index files), Obsidian is the viewing frontend, and Q&A against the wiki is answered by rendering markdown (or slides/images) rather than chat text — with outputs filed back into the wiki so every query compounds the knowledge base. Karpathy's key insight: at ~100 articles / 400K words, you don't need fancy RAG — good auto-maintained index/summary files are enough for an LLM to find what it needs.

Atlas is also meant to be a shared memory that other agents can read and grow. Because those agents may run on any model provider, the agent-facing access layer is **MCP** (`atlas-mcp`, see below) rather than anything Claude-specific. The CLI (`atlas ask`), the MCP server, and the local web UI (`atlas ui`) all call the same underlying pipeline: one implementation, several entrypoints.

**Decisions made:**
- Multi-agent style: **orchestrator-subagent** (hierarchical), not graph-based orchestration or swarm — chosen because ingest/query/lint are linear pipelines, not cyclic/negotiated workflows.
- Orchestration mechanism: **CLI-shell orchestrator** — a script that dispatches each agent role to a configurable backend (Claude Code CLI, Anthropic API directly, and later Codex/Grok/Kimi/etc.), so swapping models is a config change, not a rewrite.
- Available today: Claude Code subscription + a standalone Anthropic API key. Other providers (Codex, Grok, Kimi) are future swaps — the backend interface supports them now, implementations come later.
- Build order: **ingest pipeline first**, query pipeline second, linting/extra tools/fine-tuning later ("start simple, add incrementally").
- Git: initialized at repo root; ingest runs auto-commit, so any bad auto-summary/link/categorization is a one-line `git revert` away.
- Output philosophy: answers render as markdown files in `universe/output/` (or later: Marp slides, matplotlib images), viewed in Obsidian — never plain chat text.

## Repository Layout

```
knowledge-graph/                   # repo root
├── SPEC.md                        # this document — persistent cross-session reference
├── universe/                      # Obsidian vault ("the wiki")
│   ├── raw/                       # INPUT ONLY: articles, PDFs, repos, datasets, images,
│   │                               #   links, Web-Clipper .md exports + their clipped images
│   ├── library/                   # one generated note per raw/ item: summary + frontmatter + backlinks
│   ├── concepts/                  # synthesized topic articles linking multiple library notes together
│   ├── index/                     # auto-maintained MOC / index files (per Karpathy — the reason
│   │                               #   fancy RAG isn't needed at this scale)
│   ├── output/                    # Q&A log: one file per conversation (or per day), one line per question
│   └── Welcome.md
├── atlas/                         # the orchestrator + agents (Python)
│   ├── cli.py                     # entrypoint: `atlas ingest`, `atlas ask "..."`, `atlas lint`, `atlas ui`
│   ├── mcp_server.py              # ask_knowledge_graph + add_source MCP tools, for other agents
│   ├── bin/atlas-mcp               # arch -arm64 wrapper -- run THIS, not .venv/bin/atlas-mcp directly
│   ├── config.yaml                # per-agent-role → backend + model mapping (swap models here)
│   ├── backends/                  # model backend abstraction
│   │   ├── base.py                #   run(system, user) -> str
│   │   ├── claude_cli.py          #   shells out to `claude -p ... --output-format json`
│   │   └── anthropic_api.py       #   direct Anthropic SDK call using ANTHROPIC_API_KEY
│   ├── agents/                    # prompt templates + parsing per role
│   ├── orchestrator/
│   │   ├── ingest.py              # sequences the per-file ingest pipeline
│   │   ├── query.py               # sequences the ask pipeline; shared by cli.py and mcp_server.py
│   │   └── lint.py                # read-only structural health checks
│   ├── ui/                        # `atlas ui`: local web app (server.py + static/, tour.js), see "Web UI"
│   ├── demo.py                    # create/reset demo/ from demo_template/, see "Demo graph & tutorial"
│   ├── demo_template/             # the demo vault as shipped (committed, built by the real pipeline)
│   ├── util.py                    # slugify, git_commit(message, paths) — shared by both entrypoints
│   └── state/ui.json              # machine-local UI state (first_time_user); git-ignored
├── demo/                          # working demo vault (git-ignored; Reset demo restores it)
└── .git/

Every vault keeps its own ingest bookkeeping in `<vault>/.atlas/`:
manifest.json (hash/timestamp of processed input files — avoids reprocessing) and
manifest.lock (flock serializing manifest writes across concurrent runs).
```

## Backend Abstraction

Common interface every backend implements:
```python
def run(system_prompt: str, user_prompt: str) -> str
```
No tool-use parameter: neither backend wires tools, which is why the Researcher step (V2) is deferred.
Note `claude_cli` passes the user prompt as an argv value, so a prompt must not start with `-`
(`claude` parses e.g. a leading `---` as an unknown option).
- `ClaudeCodeCLIBackend`: shells out to headless `claude -p` (print mode), parses JSON output.
- `AnthropicAPIBackend`: direct SDK call with the user's `ANTHROPIC_API_KEY`.
- Future (interface stubs only, not implemented in v1): Codex CLI, Grok API, Kimi API, etc.

`config.yaml` maps each agent role to a backend + model, e.g.:
```yaml
agents:
  summarizer: {backend: claude_cli, model: default}
  categorizer: {backend: anthropic_api, model: claude-sonnet-5}
```
Swapping a role to a different model/provider is a one-line config edit, never a code change.

## V1: Ingest Pipeline (built first)

`atlas ingest` scans the vault's input dirs (`vault.input_dirs` in `config.yaml`, `raw/` by default), diffs against the vault's `.atlas/manifest.json` (content hash) to find new/changed items, then runs each through a sequential subagent chain:

1. **Extractor** — normalizes raw input (PDF/article/link/repo/dataset/image/pre-clipped .md, or a bare URL — fetched via `trafilatura`) into plain text + metadata (title, source, type, date). Deterministic code, no LLM call. A text file may open with `key: value` marker lines the pipeline can't infer itself: `source_date:` (the material is time-sensitive — concept synthesis notes "as of <date>" next to it) and `reference: true` (a verbatim example bank — summarized close to verbatim and, for an existing concept, linked under `## Reference Material` instead of being folded into the synthesis). Only these known keys are consumed; YAML frontmatter is not parsed.
2. **Summarizer** — writes `universe/library/<slug>.md`: frontmatter (source, tags, type, date-ingested) + summary body. Note slugs are keyed on the stable raw filename, never on the LLM's title (title generation isn't perfectly deterministic run-to-run, so keying on it risks silently creating a duplicate note on reprocess instead of updating the existing one).
3. **Categorizer** — splits assignment into `primary_concepts` (this note is centrally about it — gets full synthesis membership) vs `related_concepts` (genuinely touches on it, but gets a cross-link only, not full integration). This distinction exists specifically to stop tangential mentions from diluting a concept article's focus. Prefers reusing existing concepts over creating new ones.
4. **Linker** — hub-and-spoke, not pairwise: writes the new library note's own links out to its concept(s) (primary + related). Concept articles remain the hub that link back to members — this deliberately avoids O(n²) note-to-note cross-linking as a concept's membership grows.
5. **Concept synthesizer** — for each *primary* concept, incrementally revises the existing concept article using just the new note (never regenerates from every member's full text — cost per ingest is O(1) in concept size, not O(n)). Every concept article must open with a plain-language, jargon-free definition before any named sub-patterns/vocabulary — enforced as an explicit synthesizer rule after a real article shipped without one.
6. **Index updater** — refreshes `universe/index/MOC.md`, listing each concept's primary members plus an "Also touches on" list of related-only notes, so retrieval later never needs embeddings, just this index.

After each run: a git commit scoped to exactly the files that run touched (`util.git_commit(message, paths)`), message `ingest: <files>`. Every read-modify-write of the manifest holds an `fcntl` lock (`ingest.manifest_lock`), since `atlas ingest`, MCP `add_source`, and the web UI can run concurrently. When the repo isn't a git repository (e.g. downloaded as a ZIP), the commit step is skipped with a message rather than failing the run. `atlas ingest --limit N` processes only the first N unprocessed files, for working through a large backlog in inspectable batches.

## V2: Query Pipeline (built)

`atlas ask "question"` (`atlas/orchestrator/query.py::run_ask`):
1. **Retriever** — builds a cheap index in Python from concept/library frontmatter (no `MOC.md` parsing needed), asks an LLM which concept/library slugs are relevant and whether the wiki covers the question at all (`coverage: sufficient|insufficient`).
2. **Writer** — reads the full text of the retrieved notes, writes a cited markdown answer. If coverage is insufficient, it says so plainly instead of fabricating an answer — this stands in for the **Researcher** step (optional live web research), which is explicitly deferred: the `Backend` interface is pure text-in/text-out with no tool-use wired for either backend, so real web research is a separable follow-up.
3. **Output** — a scannable log, not a copy of the answer: one file per conversation (`universe/output/conv-<conversation_id>.md` when a caller passes `conversation_id`) or per day (`<YYYY-MM-DD>.md`), frontmatter `created` / `question_count` / `last_updated`, and one line per question — time, coverage, the caller (omitted for `cli`; this is the only provenance trail, since MCP has no protocol-level caller identity), the question, a one-sentence summary, and links to the sources used. The full answer goes back only in the return value (and, for a real finding, into the concept via file-back).
4. **File-back** — if the writer identifies a genuine new `key_finding` tied to one of the concepts already in context (never a new concept — avoids ad hoc concept sprawl from casual questions), it's folded into that concept article via the same `concept_synth.synthesize` agent ingest uses. The CLI files back by default (`--no-file-back` skips it); MCP `ask_knowledge_graph` defaults to `file_back=False`, so agents' casual lookups don't accrete into the graph unless they opt in.

Git commit is scoped to exactly the files each `ask` run touched (`util.git_commit`, not `git add -A`) — this matters because ingest and ask can run concurrently and an unscoped add would misattribute one run's output to another's commit message (this happened once in practice during development).

## MCP Server (built)

`atlas-mcp` (`atlas/mcp_server.py`, built on `fastmcp`) exposes **two consolidated tools**, not a set of low-level primitives a calling agent would have to chain itself:
- `ask_knowledge_graph` — wraps `run_ask` directly, same code `atlas ask` uses.
- `add_source(url)` — wraps `run_ingest_url` (see V1 above), for when a caller's own research (e.g. an agent doing a web search after `ask_knowledge_graph` returns `coverage: insufficient`) finds something worth permanently absorbing into the wiki, ingested through the exact same pipeline as everything else.

This exists so other agents (and models — MCP is provider-agnostic, unlike a Claude-specific integration) can query and grow the wiki directly from its own UI instead of shelling out to the CLI. A calling agent identifies itself via the `caller` parameter, recorded as `asked_by` in `ask`'s output artifact / the git commit message for `add_source`.

**Run via the wrapper script, not the pip entry point directly:** `atlas/bin/atlas-mcp`, which forces `arch -arm64` before exec'ing the venv's Python. This exists because `pydantic_core` (a transitive `fastmcp` dependency) only has an arm64-compiled component in this venv, and a client that spawns child processes under Rosetta/x86_64 (observed with at least one desktop MCP client on Apple Silicon) crashes it on import before any MCP handshake happens — surfacing to the client as an immediate, silent "Connection closed," not an error naming the real cause. A client registers it as a local command-based MCP server: `{"mcpServers": {"atlas": {"command": "<repo>/atlas/bin/atlas-mcp"}}}`.

## Web UI (built)

`atlas ui` (`atlas/ui/server.py`) is a small local web app for people who'd rather not use a terminal; `Start Atlas.command` in the repo root is a double-clickable launcher that creates `.venv/` on first run, reinstalls when `pyproject.toml` changes, and then runs `atlas ui`.

- **Stdlib only** (`http.server`), bound to `127.0.0.1`, plus `markdown` for rendering. No framework, no JS build step, so nothing in the UI itself can fail to install.
- **No second pipeline.** Each button calls exactly what the CLI calls: `cli.cmd_ingest`, `query.run_ask` + `util.git_commit`, `lint.run_lint`. Uploads and pasted links just write files into `raw/` (links use the same filename convention as `run_ingest_url`), and "Update my knowledge graph" is a plain ingest.
- **One job at a time.** Ingest and ask are several sequential model calls each; the server refuses a second job while one runs. Whatever the job's thread prints (the same progress lines the CLI shows) is routed into that job's log and polled by the page.
- **Safety.** Raw HTML in notes is escaped rather than rendered (notes are LLM-written from arbitrary web pages), `javascript:`/`data:` links are neutralized, and requests whose `Host`/`Origin` isn't the local address are refused (DNS rebinding), since the page can start model runs.
- **Setup check** sends one tiny prompt through the summarizer's configured backend: the only reliable way to confirm Claude Code is both installed and signed in.
- **Graph switcher.** Every API request carries `graph=mine|demo`; the server runs that request (and any job it starts, in its own thread) inside `config.use_vault(...)`. Jobs remember their graph, and the one-job limit spans both graphs.

## Demo graph & tutorial (built)

**Two vaults, not one.** The demo is its own knowledge graph (`demo/`), separate from the user's (`universe/`). An earlier version loaded demo articles into the user's own vault with a "Remove the demo" button; that breaks as soon as someone adds a real source before removing the demo, because the categorizer happily files real sources under demo topics and the two can no longer be separated. Separate vaults make that impossible and keep the demo around as a reference.

**Active vault.** `config.vault_root()` resolves, in order: a `ContextVar` set by `config.use_vault()` (the web UI, per request/job thread), the `ATLAS_VAULT` env var (`atlas --vault demo …`), then `vault.root` from `config.yaml`. Vaults must live inside the repo, since every reported path is REPO_ROOT-relative. The manifest moved from `atlas/state/` into each vault's `.atlas/` so two graphs never share "already read" bookkeeping. The MCP server never sets a vault, so agents only ever see the user's own graph.

**Template.** `atlas/demo_template/` is committed: 10 original CC0 articles in `raw/`, 7 of them compiled by the real pipeline (library/, concepts/, index/, plus the `.atlas/manifest.json` that marks them read) and 3 left waiting for the tour to build. `demo.ensure_demo()` copies it to `demo/` on first launch; `demo.reset_demo()` deletes and re-copies, and refuses any path other than `<repo>/demo`. Never hand-edit the template's generated notes — rebuild it with `atlas --vault atlas/demo_template ingest` from its raw/ files instead.

**Tutorial.** `first_time_user` lives in `atlas/state/ui.json` (missing file = true), on the server rather than in browser storage so it survives a different browser. While true, `static/tour.js` runs a spotlight tour in the demo: the target element gets a 100vmax box-shadow that dims the rest of the page, a card explains the step, and steps that need an action advance on the real event (a job starting/finishing, a hash change, the graph switch) rather than on a click. Skip (fixed bottom-right) or finishing sets the flag false; Guide → Restart the tutorial resets the demo and sets it true. The step index persists in localStorage, so a reload resumes the tour.

**Known variability.** Which topics the 3 tour articles create vs. update is the categorizer's call and differs run to run, so `cli.ingest_and_commit` reports `created_topics` / `updated_topics` and the tour points at whichever topic actually changed.

## Maintenance: Concept Granularity & Splitting

**The problem.** The categorizer prefers reusing existing concepts over creating new ones (deliberately, to avoid fragmenting near-duplicate concepts — see the tags/concepts asymmetry discussion in project history). But a concept that was scoped too broadly when first created can keep absorbing genuinely separable sub-disciplines, one *individually correct* categorization at a time — each addition is a real fit, but the concept itself grows unfocused. For example, a broad "design patterns" concept can grow past 100 lines covering four distinct sub-disciplines, each with its own internal vocabulary dense enough to stand alone.

**Diagnosing real bloat vs. healthy breadth.** A long concept article is not automatically a problem — check for *redundancy* (does a later section restate a point an earlier section already made?) before assuming it needs splitting. If every section adds genuinely new information from a specific source with no repetition, the issue isn't verbosity — it's that the *concept boundary* is scoped too broadly, bundling what are really N separate topics under one name. That's a categorization-granularity problem, not a synthesis-quality problem, and the fix is narrowing the taxonomy, not compressing the prose.

**Signals it's time to split:**
- The article has multiple sections that each introduce their own named vocabulary/framework, largely independent of each other.
- A section could be read on its own, out of context, and still make complete sense as a standalone topic.
- New sources keep landing in this concept via the categorizer's reuse-preference, but each one feels like it's only "sort of" about the same thing as the others.

**Splitting procedure** (done manually so far, once per identified case — not yet automated):
1. **Identify natural section boundaries** in the overgrown concept article — each split target should be a coherent, self-contained sub-topic, not an arbitrary cut.
2. **Check every existing concept for overlap with each split target before creating a new one** — a candidate split may substantially overlap an already-existing concept that covers the same underlying question from a different source/vocabulary. If a real overlap is found, decide explicitly: merge into the existing concept, or keep separate with reciprocal `## Related Concepts` links between them (this project has chosen "keep separate, cross-link" in the one case hit so far, to avoid just relocating the bloat under a different name).
3. **Extract exact section text programmatically** (e.g. split on `## ` headers in Python) rather than retyping it, to avoid transcription drift.
4. **Generate each new concept through the real production path**: call `concept_synth.synthesize(name, current_article=None, new_note={title, slug, summary: <extracted text>})` for each underlying library note's relevant content, in the same order it was originally ingested — this is exactly the empty-concept path a real ingest takes, so the split article gets the same definition-first treatment and structure a fresh ingest would produce, rather than being hand-assembled.
5. **Update the affected library notes' frontmatter** (`concepts:` / `related_concepts:`) to point at the new concept(s) instead of (or in addition to — a single source can be primary to more than one concept if it genuinely covers more than one) the original, then regenerate each note's `## Concepts` section via `linker.add_concept_links()` — don't hand-write this, reuse the same function ingest uses so the format stays consistent.
6. **Trim the original concept article** to remove the moved sections, fix any sentences that referenced the moved content, and add a `## Related Concepts` footer pointing at the new split-off concepts.
7. **Rebuild the index** via `indexer.rebuild_index()` and verify the result (`MOC.md` structure, no orphaned links, git diff looks like exactly the intended change) before committing.

**Detection is now automated** — `atlas lint` (below) flags overgrown-concept candidates by line/section-count threshold. The split itself (steps 1-7 above) is still a manual, human-judgment operation; lint only surfaces candidates for a human to review against the diagnosis criteria in this section.

## V3: Lint / Health-Check (built)

`atlas lint` (`atlas/orchestrator/lint.py::run_lint`) runs deterministic, read-only checks over `universe/` — no LLM calls, same file-scan approach as `indexer.rebuild_index()`. It never edits the vault; it only reports. Built deliberately scoped away from the query pipeline (`query.py`, `retriever.py`, `writer.py`, `mcp_server.py`) — no shared files, no LLM backend/config dependency, so it could be developed alongside concurrent `ask`-side work with zero merge risk.

**Done:**
- **Missing frontmatter** — library notes missing `title`/`source`/`type`; concept notes missing `title`.
- **Dangling concept refs** — a library note's `concepts`/`related_concepts` slug that doesn't correspond to an actual file in `concepts/`.
- **Broken wikilinks** — `[[library/slug|...]]` / `[[concepts/slug|...]]` links whose target file doesn't exist.
- **Orphaned concepts** — a concept file with zero library notes referencing it.
- **Overgrown concepts** — line/section-count over threshold (`OVERGROWN_LINE_THRESHOLD` / `OVERGROWN_SECTION_THRESHOLD` in `lint.py`), the automated version of the detection step described in "Maintenance" above.
- **CLI wiring** — `atlas lint`, prints a grouped report by check name, exits 0 either way (informational, not a gate).

**Remaining / not yet built** (deferred to V4+, see below):
- **MCP exposure** — `run_lint()` isn't wired into `atlas-mcp` yet, so agents can't trigger it. (The web UI's Health check page does expose it.)
- **Auto-fix** — lint only detects and reports; nothing acts on a finding automatically (e.g. no auto-splitting an overgrown concept, no auto-repair of a broken wikilink).
- **Inconsistency detection / missing-data imputation / new-article suggestions** — the broader health-check scope originally sketched for "linting" in V1's build order; only the five structural/detection checks above exist so far.
- **CI/pre-commit hook** — currently run manually (`atlas lint`); not wired into `ingest`/`ask`'s auto-commit flow or any git hook.

## V4+: Deferred (explicitly out of scope for now)

- **Lint auto-fix / suggestions** — inconsistency detection, missing-data imputation via web search, new-article/connection suggestions. `atlas lint`'s detection-only checks (V3 above) are a first step toward this, not the full scope.
- **Extra tools** — e.g. a small standalone search engine over the wiki (web UI + CLI-callable by an agent).
- Output formats beyond markdown — Marp slides, matplotlib images.
- Synthetic data generation / fine-tuning to internalize the wiki into model weights.

## Verification

- Ingest: run `atlas ingest` against a handful of real raw files spanning types (article, PDF, repo link, Web Clipper export); open `universe/` in Obsidian and check the graph view shows sensible link structure, frontmatter is valid, and no orphaned/duplicate concept articles were created on a second run (idempotency via the manifest).
- Query: run `atlas ask` with a question you know the answer to from the seeded content; confirm the output file cites the right library/concept notes and reads correctly rendered in Obsidian.
- Git safety net: intentionally let one ingest stage produce a bad note, confirm `git revert`/`git log` makes recovery trivial.
