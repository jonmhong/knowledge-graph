# Atlas: a knowledge graph that writes itself

Give Atlas the articles, notes and PDFs you've been meaning to read. It reads
each one, writes a short summary, sorts it into topics, and keeps an
up-to-date article for every topic that folds in what each new source adds.
Then you can ask it questions in plain English and get answers that cite
your own sources.

Everything is saved as ordinary text files on your computer. You can read them
in Atlas itself, or open the `universe` folder in [Obsidian](https://obsidian.md)
to see it all as a connected graph.

---

## Getting started (no programming needed)

You'll need a Mac (or Linux) and about 10 minutes.

**1. Install Claude Code and sign in once.** Atlas uses Claude to do its
reading and writing. Install it from [claude.com/claude-code](https://claude.com/claude-code),
then open the **Terminal** app, type `claude`, press Return, and follow the
sign-in steps. You can close Terminal afterwards.

**2. Make sure you have Python.** Most Macs need it installed: get the latest
version from [python.org/downloads](https://www.python.org/downloads/) and run
the installer.

**3. Download Atlas.** On this project's GitHub page, click the green **Code**
button, then **Download ZIP**. Unzip it somewhere easy to find, like your
Documents folder.

**4. Double-click `Start Atlas.command`** in the unzipped folder. The first
time, macOS may say it's from an unidentified developer. If so, right-click
the file, choose **Open**, then **Open** again. A Terminal window appears and
does a one-time setup that takes a minute or two. Then Atlas opens in your
web browser.

> Keep that Terminal window open while you use Atlas. Closing it stops Atlas.
> To start it again later, double-click `Start Atlas.command` again.

### The tutorial and the demo

The first time Atlas opens, a short guided tour starts (about 5 minutes). It
highlights one thing at a time and dims the rest, and walks you through:
checking your setup, having Atlas read a few articles, opening a topic it
wrote, asking a question, and opening the graph in Obsidian. You can press
**Skip tutorial** in the bottom-right corner at any time.

The tour runs in the **demo**, a separate practice knowledge graph about how
people learn and remember (10 short articles, 7 already read and 3 waiting
for you). You have **two knowledge graphs**, and the switch in the top-right
corner of Atlas chooses which one you're working in:

| | **Demo** | **My knowledge graph** |
| --- | --- | --- |
| What it's for | Practicing and experimenting | Your own reading |
| Folder | `demo` | `universe` |
| Starts with | 10 sample articles | Nothing |

Everything you do in Atlas (adding, updating, asking, browsing) applies only
to the graph that's selected. When the demo is selected, an orange banner
says so. Nothing you do in the demo ever touches your own graph.

The **Guide** tab has two buttons for the demo:
- **Reset the demo** puts it back exactly as it started.
- **Restart the tutorial** resets the demo and runs the tour again.

### Viewing your graphs in Obsidian

[Obsidian](https://obsidian.md) is a free notes app that can show a knowledge
graph as a web of connected notes. Each graph is its own Obsidian "vault":

1. In Obsidian, choose **Open folder as vault** and pick the `demo` folder
   inside the Atlas folder.
2. To see your own graph, open the vault switcher (click the vault name in
   the bottom-left corner of Obsidian, then **Manage vaults**), choose
   **Open folder as vault**, and pick the `universe` folder.
3. From then on, switch between the two with that same vault switcher.

Click the graph icon in Obsidian's left sidebar to see the connections.

### Using Atlas

The tabs along the top of the page are everything Atlas can do:

| Tab | What it's for |
| --- | --- |
| **Home** | See how big the selected knowledge graph is, and what's waiting to be read. |
| **Add sources** | Pick one of three ways: **Upload files** (PDF, `.md`, `.txt`), **Web link** (an article's address), or **Paste text** (copy an article from anywhere, including pages behind a login). Then press **Update my knowledge graph**. Each source takes about half a minute. |
| **Ask** | Ask a question. Answers only come from your sources. If they don't cover it, Atlas tells you instead of making something up. |
| **Browse** | Read the topic articles and source summaries Atlas has written. |
| **Health check** | Confirm Atlas is set up correctly, and check your knowledge graph for broken links. |
| **Guide** | This page, plus **Reset the demo** and **Restart the tutorial**. |

**Tip:** with a big pile of sources, set "Only the next ___ sources" to 5 or
so. That way you can check the results as you go.

### Common questions

**Does it cost anything?** Atlas is free. It runs on your Claude Code
account, and the usage counts toward your Claude plan.

**Where is my stuff?** Your own graph is in the `universe` folder (the demo is in `demo`). `raw` holds what you added,
`library` holds one summary per source, and `concepts` holds the topic
articles. Atlas only *reads* your originals and never changes them.

**Can I edit what Atlas wrote?** You can, but your edits may be overwritten
the next time Atlas updates that topic. It's better to add a source that
says what you want.

**Is my data shared?** No. Atlas runs on your computer, and only *you* can
open the page. Your sources are sent to Claude to be read, the same as
pasting them into a Claude chat.

---

## For developers

Atlas is an orchestrator-subagent pipeline over an Obsidian vault of plain
markdown. It's inspired by Karpathy's note on LLM-maintained knowledge bases:
at ~100 articles you don't need embeddings or a vector DB, because a
well-maintained index file is enough for a model to find what it needs.

```
universe/raw/  --ingest-->  library/ + concepts/ + index/  --ask-->  output/
   your sources              the wiki                        your Q&A log
```

### Install and run from the command line

Requires Python 3.10+ and, for the default config, the
[Claude Code CLI](https://claude.com/claude-code) logged in. Uses `fcntl`, so
macOS/Linux (or WSL) only.

```bash
git clone <this-repo> knowledge-graph && cd knowledge-graph
python3 -m venv .venv && source .venv/bin/activate
pip install -e .

cp ~/Downloads/some-article.pdf universe/raw/   # 1. add a source (.md, .pdf, .txt, or a .md containing just a URL)
atlas ingest                                    # 2. compile it into the wiki
atlas ask "what are the tradeoffs of X?"        # 3. ask the wiki something
atlas lint                                      # 4. structural health check (read-only)
atlas ui                                        # or do all of the above in the browser
```

| Command | What it does |
| --- | --- |
| `atlas ingest` | Process every new/changed file in `raw/` |
| `atlas ingest --limit 5` | Process only the next 5, so you can work a backlog in reviewable batches |
| `atlas ask "..."` | Ask a question. Genuinely new findings get folded back into the relevant concept article |
| `atlas ask "..." --no-file-back` | Ask without writing anything back into the wiki |
| `atlas lint` | Read-only check for broken links, dangling refs, and orphaned or overgrown concepts |
| `atlas ui [--port N] [--no-browser]` | Start the local web app (default http://127.0.0.1:8765) |
| `atlas --vault demo <command>` | Run `ingest` / `ask` / `lint` against the demo graph (or `--vault <folder>` for any vault inside the repo) instead of `universe/` |

If the folder is a git repository, every run auto-commits only the files it
touched, so a bad summary or miscategorization is one `git revert` away. Run
`git init` in a downloaded copy to turn this on. Without git, runs work the
same and simply skip the commit.

### What's committed vs. local

A fresh clone ships an **empty vault** in `universe/` plus the demo
**template** in `atlas/demo_template/` (built once by the real pipeline, with
its manifest committed so the 7 pre-built articles count as already read).
These paths are git-ignored and stay on your machine:

- **`universe/raw/`**: your source material, which is often someone else's copyrighted text.
- **`universe/output/`**: your Q&A history.
- **`universe/.atlas/`**: content hashes of your `raw/` files, so ingest knows what it has already seen. Every vault keeps its own copy, so two graphs never confuse each other.
- **`demo/`**: the working demo graph, created from the template on first launch and restored by **Reset the demo**.
- **`atlas/state/`**: machine-local UI state, e.g. whether the tutorial has been completed.

`library/`, `concepts/` and `index/` are not ignored, so you can version your
own wiki in your own fork. If you plan to contribute back upstream, keep
them out of your PRs.

### How it works

`atlas ingest` runs each new file through a chain of small, single-purpose
agents. [SPEC.md](SPEC.md) has the full design and the reasoning behind each
choice.

1. **Extractor**: normalizes PDF/article/URL/markdown into text + metadata. Pure code, no model call.
2. **Summarizer**: writes `library/<slug>.md`, with frontmatter plus a summary.
3. **Categorizer**: assigns *primary* concepts (the note is centrally about them) vs. *related* ones (it merely touches on them). This split stops tangential mentions from diluting a concept article.
4. **Linker**: hub-and-spoke links out to concepts. Deliberately not pairwise, so the number of links doesn't grow O(n²) with the vault.
5. **Concept synthesizer**: revises each primary concept article using *only* the new note, never regenerating from every member. Cost per ingest stays flat as a concept grows.
6. **Indexer**: rebuilds `index/MOC.md`.

`atlas ask` retrieves relevant slugs from frontmatter, reads those notes in
full, and writes a cited answer. If the wiki doesn't cover the question, it
says so plainly instead of inventing an answer.

### Swapping models

`atlas/config.yaml` maps each agent role to a backend and model. Changing a
role's model is a one-line edit, never a code change:

```yaml
agents:
  summarizer: {backend: claude_cli, model: default}
  categorizer: {backend: anthropic_api, model: claude-sonnet-5}
```

`claude_cli` shells out to your logged-in Claude Code CLI. `anthropic_api`
calls the API directly and needs `ANTHROPIC_API_KEY` set in the environment
(see `.env.example`).

### Letting your agents use it (MCP)

The repo ships a `.mcp.json`, so an MCP-aware client opened in this directory
picks up an `atlas` server with two tools:

- **`ask_knowledge_graph(question, caller)`**: query the wiki and get a cited answer.
- **`add_source(url, caller)`**: permanently ingest a URL through the same pipeline as everything else.

For a client that needs manual registration, point it at the launcher script
rather than the pip entry point:

```json
{ "mcpServers": { "atlas": { "command": "/absolute/path/to/knowledge-graph/atlas/bin/atlas-mcp" } } }
```

That wrapper handles two real macOS failure modes: a Rosetta architecture
mismatch, and GUI apps not inheriting your shell `PATH`. Its comments explain
both.

Agents working *in* this repo should read [CLAUDE.md](CLAUDE.md). It covers
the conventions that keep the vault consistent, the most important being:
never hand-write generated notes, always go through the pipeline.

### Layout

```
Start Atlas.command  double-click launcher (sets up .venv, runs `atlas ui`)
atlas/               the orchestrator
  cli.py             ingest / ask / lint / ui
  mcp_server.py      the two MCP tools
  config.yaml        role -> backend/model mapping
  backends/          claude_cli, anthropic_api
  agents/            one module per pipeline role
  orchestrator/      ingest.py, query.py, lint.py
  ui/                local web app (stdlib server + static/ page, tour.js tutorial)
  demo.py            create / reset the demo graph from the template
  demo_template/     the demo graph as shipped: 10 CC0 articles, 7 pre-built
universe/            YOUR knowledge graph (an Obsidian vault)
  raw/               INPUT ONLY (local)
  library/           one note per source
  concepts/          synthesized topic articles
  index/MOC.md       auto-generated index
  output/            Q&A log (local)
demo/                the working demo graph (local, created on first launch)
SPEC.md              architecture, decisions, and what's deferred
```
