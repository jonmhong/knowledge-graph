# Working in this repo

Atlas is a self-compiling knowledge graph. `universe/` is an Obsidian vault of
plain markdown; `atlas/` is the Python orchestrator that writes it. Read
[README.md](README.md) for the user-facing picture and [SPEC.md](SPEC.md) for
the architecture and the reasoning behind each design choice — SPEC.md is the
living technical spec and stays current.

## The one rule that matters

**Never hand-write or hand-edit notes in `universe/library/`, `universe/concepts/`,
or `universe/index/`.** They are generated artifacts. If a note is wrong or
missing, fix the agent prompt or the pipeline and re-run it — don't patch the
output. Hand-edits silently diverge from what the next ingest would produce, and
`index/MOC.md` gets overwritten wholesale on every run regardless.

When a task genuinely needs a one-off note change (a concept split, say), do it
by calling the same production functions ingest uses — `concept_synth.synthesize`,
`linker.add_concept_links`, `indexer.rebuild_index` — rather than writing
markdown directly. SPEC.md's "Maintenance" section walks through the one
procedure where this has come up.

## Doing things through the CLI

```bash
atlas ingest [--limit N]          # compile new/changed raw/ files into the wiki
atlas ask "question" [--no-file-back]
atlas lint                        # read-only structural health check
atlas ui [--port N]               # local web app over the same commands (atlas/ui/)
```

`ingest` and `ask` auto-commit (also when triggered from `atlas ui`; skipped if the folder isn't a git repo) (`lint` is read-only), scoped to the files that run touched. Don't add your own
`git add -A` around them: ingest and ask can run concurrently, and an unscoped
add misattributes one run's output to the other's commit message.

Prefer `--limit` when working a backlog, so each batch stays reviewable.

## Answering questions about the vault's contents

If you need to know what the vault *says* about something, query it rather than
grepping every note:

- Via MCP (registered in `.mcp.json`): `ask_knowledge_graph(question, caller="<your name>")`.
- Via CLI: `atlas ask "..."`.

Both run the same retrieval pipeline and write a cited answer to
`universe/output/`. Pass a real `caller` — it's recorded as `asked_by` and is
the only provenance trail MCP gives us.

Two caveats worth knowing before you use the result:

- If the wiki doesn't cover the question, the writer reports
  `coverage: insufficient` instead of guessing. Take that at face value; don't
  paper over it with your own knowledge without saying so.
- By default a genuinely new finding gets filed back into an existing concept
  article. Use `--no-file-back` / `file_back=False` for throwaway lookups, so
  casual questions don't accrete into the graph.

For structural questions ("which concepts are orphaned?", "what links are
broken?"), use `atlas lint` — it's deterministic and free.

## Vault conventions

- `library/<slug>.md` — one note per source. Slug is keyed to the **raw
  filename**, never the LLM-generated title: titles aren't deterministic
  run-to-run, and keying on one would silently create a duplicate note on
  reprocess instead of updating the existing one.
- `concepts/<slug>.md` — synthesized topic articles. Every one must open with a
  plain-language, jargon-free definition *before* any named sub-patterns or
  vocabulary. This is an explicit synthesizer rule, added after a real article
  shipped without one.
- Frontmatter `concepts:` is primary membership (full synthesis); `related_concepts:`
  is a cross-link only. Keeping these distinct is what stops tangential mentions
  from diluting a concept's focus.
- Links are `[[library/slug|Title]]` / `[[concepts/slug|Title]]`. Concept
  articles are the hub that links back to members — avoid adding pairwise
  note-to-note links, which grow O(n²) as membership does.

## Local-only paths

`universe/raw/`, `universe/output/`, `universe/.atlas/` (each vault's ingest
manifest), `atlas/state/` (UI state), and the working demo vault `demo/` are
git-ignored — inputs, personal Q&A history, and machine-local bookkeeping. Images are ignored repo-wide. Don't `git add -f` anything under
these, and don't assume a file there exists for anyone else. `.gitkeep` files
hold the directories; ingest already skips them by name.

## Two vaults: yours and the demo

`universe/` is the user's knowledge graph and the default for every command.
`demo/` is a separate sandbox vault created from the committed
`atlas/demo_template/`. Use `atlas --vault demo <command>` to work on the demo;
never point MCP or a plain `atlas` command at it. The template's generated
notes follow the same no-hand-edit rule as `universe/` — rebuild with
`atlas --vault atlas/demo_template ingest`.

## Changing the pipeline

- Swapping which model runs a role is a `atlas/config.yaml` edit, never a code
  change. Only `summarizer`, `categorizer`, `concept_synthesizer`, `retriever`,
  and `writer` hit a model; extractor, linker, and indexer are deterministic code.
- Backends implement one method: `run(system_prompt, user_prompt) -> str`.
  There's no tool-use wired into either backend, so anything needing live web
  access is a larger change than it looks.
- `atlas/bin/atlas-mcp` is the launcher MCP clients must use. It resolves the
  repo root from its own location — keep it path-portable, and keep the two
  workarounds in it (Rosetta arch forcing via `sysctl`, explicit `PATH` for GUI
  clients). Both fix real failures that surface as silent "Connection closed".
- The web UI (`atlas/ui/server.py`) must call the same functions the CLI does —
  never reimplement pipeline logic there. Keep it stdlib + `markdown`, no JS build step.
- After touching anything that writes the vault, run `atlas lint` and check the
  git diff is exactly the intended change before committing.
