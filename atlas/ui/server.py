"""`atlas ui` -- a small local web app for running Atlas without a terminal.

Design notes:

- Stdlib `http.server` only, bound to 127.0.0.1. No framework, no build step,
  no node_modules: the people this is for should never see an install error
  from the UI itself.
- Every action calls the same functions the CLI does (cmd_ingest, run_ask +
  git_commit, run_lint). The UI is a front end, never a second pipeline -- if
  it computed anything the CLI doesn't, the two would drift.
- One long-running job at a time. Ingest and ask are each several sequential
  model calls; a non-technical user double-clicking "Build" shouldn't be able
  to start three overlapping runs. Output the job prints (the same progress
  lines the CLI shows) is captured per-thread and streamed to the page.
"""
from __future__ import annotations

import io
import json
import mimetypes
import os
import re
import shutil
import sys
import threading
import time
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import frontmatter
import markdown
from markdown.extensions import Extension
from markdown.treeprocessors import Treeprocessor

from atlas import config, demo
from atlas.util import slugify

STATIC_DIR = Path(__file__).parent / "static"
UI_STATE_PATH = config.REPO_ROOT / "atlas" / "state" / "ui.json"
# The two knowledge graphs the UI can switch between. "mine" is the user's own
# (config.yaml vault.root, i.e. universe/); "demo" is the sandbox in demo/.
GRAPHS = ("mine", "demo")
ALLOWED_UPLOAD_SUFFIXES = {".md", ".txt", ".pdf"}
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
# Folders the note viewer may open. raw/ is deliberately absent: inputs can be
# PDFs or arbitrary text and aren't meant to be read back through the wiki.
VIEWABLE_FOLDERS = {"library", "concepts", "index", "output"}
# Top-level docs the Guide page may render.
DOCS = {"README.md", "SPEC.md", "CLAUDE.md"}


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------


class Job:
    def __init__(self, kind: str, label: str, graph: str) -> None:
        self.kind = kind
        self.label = label
        self.graph = graph
        self.status = "running"  # running | done | error
        self.lines: list[str] = []
        self.result: dict | None = None
        self.error: str | None = None
        self.started = time.time()
        self.finished: float | None = None
        self._partial = ""
        self._lock = threading.Lock()

    def write(self, text: str) -> None:
        with self._lock:
            self._partial += text
            *complete, self._partial = self._partial.split("\n")
            self.lines.extend(line for line in complete if line.strip())

    def flush_partial(self) -> None:
        with self._lock:
            if self._partial.strip():
                self.lines.append(self._partial)
            self._partial = ""

    def to_dict(self, since: int = 0) -> dict:
        with self._lock:
            return {
                "kind": self.kind,
                "label": self.label,
                "graph": self.graph,
                "status": self.status,
                "lines": self.lines[since:],
                "line_count": len(self.lines),
                "result": self.result,
                "error": self.error,
                "elapsed": round((self.finished or time.time()) - self.started),
            }


class _ThreadRoutedStdout(io.TextIOBase):
    """sys.stdout replacement: text printed by a job's thread also goes into that
    job's log, so the page sees exactly the progress lines the CLI prints. Every
    write still reaches the real terminal too."""

    def __init__(self, real) -> None:
        self.real = real
        self.routes: dict[int, Job] = {}

    def write(self, text: str) -> int:
        job = self.routes.get(threading.get_ident())
        if job is not None:
            job.write(text)
        self.real.write(text)
        return len(text)

    def flush(self) -> None:
        self.real.flush()


_stdout = _ThreadRoutedStdout(sys.stdout)
_job_lock = threading.Lock()
_current_job: Job | None = None


def _start_job(kind: str, label: str, graph: str, fn) -> Job | None:
    """Run fn() in a background thread, against `graph`. Returns None if a job is
    already running -- one at a time across BOTH graphs, so two model runs never
    overlap."""
    global _current_job
    with _job_lock:
        if _current_job is not None and _current_job.status == "running":
            return None
        job = Job(kind, label, graph)
        _current_job = job
    vault = _graph_root(graph)

    def runner() -> None:
        _stdout.routes[threading.get_ident()] = job
        try:
            with config.use_vault(vault):  # a new thread starts with no active vault
                job.result = fn() or {}
            job.status = "done"
        except Exception as exc:  # surfaced to the page, never swallowed
            traceback.print_exc()
            job.error = _friendly_error(exc)
            job.status = "error"
        finally:
            job.flush_partial()
            job.finished = time.time()
            _stdout.routes.pop(threading.get_ident(), None)

    threading.Thread(target=runner, daemon=True).start()
    return job


def _friendly_error(exc: Exception) -> str:
    text = str(exc)
    if isinstance(exc, FileNotFoundError) and "claude" in text:
        return (
            "Atlas couldn't find Claude Code on this computer. Install it from "
            "https://claude.com/claude-code, sign in once, then try again."
        )
    if "ANTHROPIC_API_KEY" in text:
        return "Your settings use the Anthropic API, but no ANTHROPIC_API_KEY is set."
    if "claude CLI failed" in text:
        return (
            "Claude Code returned an error. If you haven't yet, open Terminal, run "
            "`claude`, and sign in -- then try again.\n\nDetails: " + text
        )
    return f"{type(exc).__name__}: {text}"


# ---------------------------------------------------------------------------
# Actions (each mirrors a CLI command)
# ---------------------------------------------------------------------------


def _do_ingest(limit: int | None) -> dict:
    from atlas.cli import ingest_and_commit

    result = ingest_and_commit(limit=limit)
    return {
        "created_topics": [{"slug": c, "title": _title_of("concepts", c)} for c in result["created_topics"]],
        "updated_topics": [{"slug": c, "title": _title_of("concepts", c)} for c in result["updated_topics"]],
    }


def _do_ask(question: str, file_back: bool) -> dict:
    from atlas.orchestrator.query import run_ask
    from atlas.util import git_commit

    print("Looking through your knowledge graph ...", flush=True)
    result = run_ask(question, file_back=file_back, caller="ui")
    paths = [result["output_path"]]
    if result["filed_back_path"]:
        paths.append(result["filed_back_path"])
        print(f"Saved a new insight into {result['filed_back_path']}", flush=True)
    git_commit(f"ask: {result['question_slug']} (via ui)", paths=paths)
    return {
        "question": question,
        "coverage": result["coverage"],
        "html": render_markdown(result["answer_markdown"]),
        "filed_back_path": result["filed_back_path"],
    }


def _check_setup() -> dict:
    """Send one tiny prompt through the summarizer's configured backend -- the
    only reliable way to know Claude Code is installed AND signed in."""
    from atlas.agents.llm import run_role

    reply = run_role("summarizer", "You are a connectivity check.", "Reply with exactly: OK")
    return {"reply": reply.strip()[:200]}


def _raw_dir() -> Path:
    return config.vault_path(config.load()["vault"].get("input_dirs", ["raw"])[0])


def _waiting_files() -> list[dict]:
    from atlas.orchestrator.ingest import _hash_file, _input_files, _load_manifest

    manifest = _load_manifest()["items"]
    vault = config.vault_path()
    waiting = []
    for path in _input_files():
        rel = str(path.relative_to(vault))
        if manifest.get(rel, {}).get("hash") != _hash_file(path):
            label = path.name
            if path.suffix == ".md" and path.stat().st_size < 2048:
                text = path.read_text(errors="replace").strip()
                if re.match(r"^https?://\S+$", text):
                    label = text
            waiting.append({"path": rel, "label": label, "size": path.stat().st_size})
    return waiting


def _setup_problems() -> list[str]:
    problems = []
    backends = {spec["backend"] for spec in config.load()["agents"].values()}
    if "claude_cli" in backends and not shutil.which("claude"):
        problems.append(
            "Claude Code isn't installed (or isn't on your PATH). Atlas uses it to read and "
            "write. Install it from https://claude.com/claude-code and sign in once."
        )
    if "anthropic_api" in backends and not os.environ.get("ANTHROPIC_API_KEY"):
        problems.append("Your settings use the Anthropic API, but ANTHROPIC_API_KEY isn't set.")
    return problems


def _status() -> dict:
    lib = list(config.vault_path("library").glob("*.md"))
    con = list(config.vault_path("concepts").glob("*.md"))
    from atlas.util import _in_git_repo

    return {
        "sources": len(lib),
        "topics": len(con),
        "waiting": _waiting_files(),
        "problems": _setup_problems(),
        "git": _in_git_repo(),
        "busy": _current_job is not None and _current_job.status == "running",
        "vault": str(config.vault_path()),
        "demo_available": demo.available(),
        "first_time_user": _ui_state()["first_time_user"],
    }


def _graph_root(graph: str) -> Path:
    if graph == "demo":
        if not demo.available():
            raise ValueError("The demo isn't included in this copy of Atlas.")
        return demo.ensure_demo()
    return config.REPO_ROOT / config.load()["vault"]["root"]


def _ui_state() -> dict:
    """Machine-local UI state (git-ignored). A missing file means a brand-new user."""
    try:
        state = json.loads(UI_STATE_PATH.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        state = {}
    return {"first_time_user": bool(state.get("first_time_user", True))}


def _set_first_time_user(value: bool) -> dict:
    state = _ui_state()
    state["first_time_user"] = bool(value)
    UI_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    UI_STATE_PATH.write_text(json.dumps(state, indent=2))
    return state


def _reset_demo() -> dict:
    if _current_job is not None and _current_job.status == "running":
        raise ValueError("Atlas is busy. Wait for it to finish first.")
    demo.reset_demo()
    return {"ok": True}


def _save_upload(name: str, data: bytes) -> str:
    name = Path(name).name  # strip any directory parts
    suffix = Path(name).suffix.lower()
    if suffix not in ALLOWED_UPLOAD_SUFFIXES:
        raise ValueError(f"Atlas can read .md, .txt and .pdf files -- not {suffix or 'this file type'}.")
    target = _unique_raw_path(slugify(Path(name).stem) or "source", suffix)
    target.write_bytes(data)
    return target.name


def _unique_raw_path(stem: str, suffix: str) -> Path:
    # Never overwrite: a raw file's name is its library note's identity, so
    # reusing one would silently replace an earlier source's note.
    raw = _raw_dir()
    target = raw / f"{stem}{suffix}"
    n = 2
    while target.exists():
        target = raw / f"{stem}-{n}{suffix}"
        n += 1
    return target


def _save_text(title: str, text: str) -> str:
    """Pasted article text -> a .md file in raw/, ingested like any other source.
    The title becomes the H1, which the extractor already uses as the title guess."""
    title, text = title.strip(), text.strip()
    if not text:
        raise ValueError("Paste the article's text first.")
    if re.match(r"^https?://\S+$", text):
        return _save_url(text)  # they pasted a link; treat it as one
    if len(text) < 200:
        raise ValueError("That's very short. Paste the full article text so Atlas has enough to work with.")
    if len(text.encode()) > MAX_UPLOAD_BYTES:
        raise ValueError("That's too long to paste (limit 50 MB).")
    given_title = bool(title)
    if not title:
        first = next((line.strip() for line in text.splitlines() if line.strip()), "")
        title = first.lstrip("#").strip()[:80] if len(first) <= 120 else ""
    stem = slugify(title)[:80].strip("-") or f"pasted-{time.strftime('%Y%m%d-%H%M%S')}"
    body = f"# {title}\n\n{text}" if given_title and not text.startswith("# ") else text
    target = _unique_raw_path(stem, ".md")
    target.write_text(body + "\n", encoding="utf-8")
    return target.name


def _save_url(url: str) -> str:
    url = url.strip()
    if not re.match(r"^https?://\S+$", url):
        raise ValueError("That doesn't look like a web address. It should start with http:// or https://")
    # Same filename convention as ingest.run_ingest_url, so a link added here and
    # the same link added over MCP map to the same raw file (and library note).
    target = _raw_dir() / f"{slugify(url)[:100] or 'source'}.md"
    if not target.exists():
        target.write_text(url)
    return target.name


def _remove_waiting(rel: str) -> None:
    waiting = {w["path"] for w in _waiting_files()}
    if rel not in waiting:
        raise ValueError("Only sources that haven't been added to the graph yet can be removed here.")
    (config.vault_path() / rel).unlink()


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

_WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|([^\]]+))?\]\]")


class _LinkPolicy(Treeprocessor):
    def run(self, root):
        for a in root.iter("a"):
            href = (a.get("href") or "").strip()
            low = href.lower()
            if low.startswith(("javascript:", "data:", "vbscript:")):
                a.set("href", "#")
            elif low.startswith(("http://", "https://")):
                a.set("target", "_blank")
                a.set("rel", "noopener noreferrer")
            elif href in DOCS:
                a.set("href", f"#/guide/{href}")
        for img in root.iter("img"):
            if not (img.get("src") or "").lower().startswith(("http://", "https://")):
                img.set("src", "")


class _AtlasExtension(Extension):
    def extendMarkdown(self, md):
        # Escape raw HTML instead of passing it through: notes are LLM-written from
        # arbitrary web pages, and this page can start model runs.
        md.preprocessors.deregister("html_block")
        md.inlinePatterns.deregister("html")
        md.treeprocessors.register(_LinkPolicy(md), "atlas_links", 0)


def _wikilinks_to_markdown(text: str) -> str:
    def repl(m: re.Match) -> str:
        target = m.group(1).strip().removesuffix(".md")
        label = (m.group(2) or target.rsplit("/", 1)[-1].replace("-", " ")).strip()
        label = label.replace("[", "(").replace("]", ")")
        return f"[{label}](#/note/{target})"

    return _WIKILINK_RE.sub(repl, text)


def render_markdown(text: str) -> str:
    md = markdown.Markdown(extensions=["tables", "fenced_code", "sane_lists", _AtlasExtension()])
    return md.convert(_wikilinks_to_markdown(text))


def _resolve_note(note_path: str) -> Path:
    folder, _, slug = note_path.partition("/")
    if folder not in VIEWABLE_FOLDERS or not re.fullmatch(r"[A-Za-z0-9_.-]+", slug or ""):
        raise ValueError("Unknown note.")
    path = config.vault_path(folder) / f"{slug}.md"
    if not path.is_file():
        raise FileNotFoundError(note_path)
    return path


def _note(note_path: str) -> dict:
    post = frontmatter.load(_resolve_note(note_path))
    folder = note_path.split("/", 1)[0]
    meta = {}
    if folder == "library":
        meta = {
            "source": post.get("source"),
            "date_ingested": str(post.get("date_ingested") or ""),
            "topics": [
                {"slug": c, "title": _title_of("concepts", c)} for c in post.get("concepts", []) or []
            ],
            "related": [
                {"slug": c, "title": _title_of("concepts", c)} for c in post.get("related_concepts", []) or []
            ],
        }
    title = post.get("title") or note_path.rsplit("/", 1)[-1].replace("-", " ").title()
    return {"path": note_path, "folder": folder, "title": title, "meta": meta, "html": render_markdown(post.content)}


def _title_of(folder: str, slug: str) -> str:
    path = config.vault_path(folder) / f"{slug}.md"
    if path.exists():
        return frontmatter.load(path).get("title") or slug
    return slug.replace("-", " ").title()


def _notes_listing() -> dict:
    lib = config.vault_path("library")
    members: dict[str, int] = {}
    sources = []
    for p in sorted(lib.glob("*.md")):
        post = frontmatter.load(p)
        for c in post.get("concepts", []) or []:
            members[c] = members.get(c, 0) + 1
        sources.append(
            {
                "slug": p.stem,
                "title": post.get("title") or p.stem,
                "date": str(post.get("date_ingested") or ""),
            }
        )
    topics = [
        {"slug": p.stem, "title": frontmatter.load(p).get("title") or p.stem, "count": members.get(p.stem, 0)}
        for p in sorted(config.vault_path("concepts").glob("*.md"))
    ]
    history = [
        {"slug": p.stem, "title": p.stem}
        for p in sorted(config.vault_path("output").glob("*.md"), reverse=True)
    ]
    sources.sort(key=lambda s: s["date"], reverse=True)
    return {"topics": topics, "sources": sources, "history": history}


def _lint() -> dict:
    from atlas.orchestrator.lint import run_lint

    report = run_lint()
    return {"total": report.issue_count(), "checks": {k: v for k, v in vars(report).items()}}


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------


class Handler(BaseHTTPRequestHandler):
    server_version = "AtlasUI"

    def log_message(self, fmt, *args):  # keep the terminal readable
        pass

    # -- plumbing --------------------------------------------------------------

    def _host_ok(self) -> bool:
        # Blocks DNS-rebinding: a web page on some other origin resolving its own
        # hostname to 127.0.0.1 would otherwise be able to drive model runs.
        port = self.server.server_address[1]
        host = self.headers.get("Host", "")
        if host not in (f"127.0.0.1:{port}", f"localhost:{port}"):
            return False
        origin = self.headers.get("Origin")
        if self.command == "POST" and origin and origin not in (
            f"http://127.0.0.1:{port}",
            f"http://localhost:{port}",
        ):
            return False
        return True

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data, code: int = 200) -> None:
        self._send(code, json.dumps(data).encode(), "application/json")

    def _error(self, message: str, code: int = 400) -> None:
        self._json({"error": message}, code)

    def _body(self) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_UPLOAD_BYTES:
            raise ValueError("That file is too large (limit 50 MB).")
        return self.rfile.read(length) if length else b""

    def _json_body(self) -> dict:
        raw = self._body()
        return json.loads(raw) if raw else {}

    # -- routes ----------------------------------------------------------------

    def _graph(self, qs: dict) -> str:
        graph = qs.get("graph", "mine")
        if graph not in GRAPHS:
            raise ValueError("Unknown knowledge graph.")
        return graph

    def do_GET(self) -> None:
        if not self._host_ok():
            return self._error("Forbidden", 403)
        url = urlparse(self.path)
        qs = {k: v[0] for k, v in parse_qs(url.query).items()}
        if not url.path.startswith("/api/"):
            return self._get(url, qs)
        try:
            graph = self._graph(qs)
            with config.use_vault(_graph_root(graph)):
                return self._get(url, qs)
        except ValueError as exc:
            return self._error(str(exc))

    def _get(self, url, qs) -> None:
        try:
            if url.path in ("/", "/index.html"):
                return self._static("index.html")
            if url.path.startswith("/static/"):
                return self._static(url.path.removeprefix("/static/"))
            if url.path == "/api/status":
                return self._json(_status())
            if url.path == "/api/job":
                job = _current_job
                return self._json(job.to_dict(int(qs.get("since", 0))) if job else None)
            if url.path == "/api/notes":
                return self._json(_notes_listing())
            if url.path == "/api/note":
                return self._json(_note(qs.get("path", "")))
            if url.path == "/api/doc":
                name = qs.get("name", "README.md")
                if name not in DOCS:
                    return self._error("Unknown document.", 404)
                text = (config.REPO_ROOT / name).read_text()
                return self._json({"name": name, "html": render_markdown(text)})
            return self._error("Not found", 404)
        except FileNotFoundError:
            return self._error("That note doesn't exist (yet).", 404)
        except ValueError as exc:
            return self._error(str(exc))

    def do_POST(self) -> None:
        if not self._host_ok():
            return self._error("Forbidden", 403)
        url = urlparse(self.path)
        qs = {k: v[0] for k, v in parse_qs(url.query).items()}
        try:
            graph = self._graph(qs)
            with config.use_vault(_graph_root(graph)):
                return self._post(url, qs, graph)
        except ValueError as exc:
            return self._error(str(exc))

    def _post(self, url, qs, graph: str) -> None:
        try:
            if url.path == "/api/upload":
                return self._json({"saved": _save_upload(qs.get("name", ""), self._body())})
            body = self._json_body()
            if url.path == "/api/add-text":
                return self._json({"saved": _save_text(body.get("title", ""), body.get("text", ""))})
            if url.path == "/api/add-url":
                return self._json({"saved": _save_url(body.get("url", ""))})
            if url.path == "/api/reset-demo":
                return self._json(_reset_demo())
            if url.path == "/api/tutorial":
                return self._json(_set_first_time_user(bool(body.get("first_time_user"))))
            if url.path == "/api/restart-tutorial":
                _reset_demo()
                return self._json(_set_first_time_user(True))
            if url.path == "/api/remove-waiting":
                _remove_waiting(body.get("path", ""))
                return self._json({"ok": True})
            if url.path == "/api/lint":
                return self._json(_lint())
            if url.path == "/api/ingest":
                limit = body.get("limit")
                limit = int(limit) if limit not in (None, "", 0) else None
                label = "Updating your knowledge graph" + (f" (next {limit})" if limit else "")
                return self._job(_start_job("ingest", label, graph, lambda: _do_ingest(limit)))
            if url.path == "/api/ask":
                question = (body.get("question") or "").strip()
                if not question:
                    raise ValueError("Type a question first.")
                file_back = bool(body.get("file_back", True))
                return self._job(_start_job("ask", "Answering your question", graph, lambda: _do_ask(question, file_back)))
            if url.path == "/api/check-setup":
                return self._job(_start_job("check", "Checking your setup", graph, _check_setup))
            return self._error("Not found", 404)
        except ValueError as exc:
            return self._error(str(exc))
        except json.JSONDecodeError:
            return self._error("Bad request.")

    def _job(self, job: Job | None) -> None:
        if job is None:
            return self._error("Atlas is already working on something. Wait for it to finish.", 409)
        return self._json(job.to_dict())

    def _static(self, name: str) -> None:
        path = (STATIC_DIR / name).resolve()
        if STATIC_DIR.resolve() not in path.parents or not path.is_file():
            return self._error("Not found", 404)
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype == "application/javascript":
            ctype += "; charset=utf-8"
        self._send(200, path.read_bytes(), ctype)


def serve(port: int = 8765, open_browser: bool = True) -> None:
    # Same reason as atlas/bin/atlas-mcp: when launched from a GUI context the
    # shell PATH may be missing, and the claude_cli backend shells out to `claude`.
    extra = [str(Path.home() / ".local/bin"), "/opt/homebrew/bin", "/usr/local/bin"]
    os.environ["PATH"] = os.pathsep.join(extra + [os.environ.get("PATH", "")])
    sys.stdout = _stdout

    for folder in ("raw", "library", "concepts", "index", "output"):
        config.vault_path(folder).mkdir(parents=True, exist_ok=True)
    demo.ensure_demo()

    try:
        httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    except OSError:
        print(f"Port {port} is busy -- Atlas may already be running. Opening it in your browser.")
        if open_browser:
            webbrowser.open(f"http://127.0.0.1:{port}/")
        return

    address = f"http://127.0.0.1:{port}/"
    print(f"\n  Atlas is running at {address}\n  Your knowledge graph: {config.vault_path()}\n  Demo knowledge graph: {demo.DEMO_DIR}\n  Keep this window open while you use it. Press Ctrl+C to stop.\n")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(address)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nAtlas stopped.")
    finally:
        httpd.server_close()
