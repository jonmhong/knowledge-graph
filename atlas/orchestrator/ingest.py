from __future__ import annotations

import fcntl
import hashlib
import json
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path

import frontmatter

from atlas import config
from atlas.agents import categorizer, concept_synth, extractor, indexer, linker, summarizer
from atlas.util import slugify



def manifest_path() -> Path:
    """The active vault's manifest (see config.state_dir). A function, not a
    constant, because which vault is active can change per run/thread."""
    return config.state_dir() / "manifest.json"
SKIP_NAMES = {".DS_Store", ".gitkeep"}


def run_ingest(limit: int | None = None) -> dict:
    """Scan the vault input dirs (raw/ by default), ingest new/changed files.

    With `limit` set, stops after that many files -- lets a large backlog be worked
    through in small batches (e.g. to spot-check synthesizer quality as it goes)
    instead of one long run touching everything at once.

    Returns {"processed": [...raw rel names...], "touched_paths": [...every file
    this run wrote, REPO_ROOT-relative...]} -- touched_paths exists so callers can
    scope `git add` to exactly what this run changed instead of `-A`, which would
    sweep in whatever a concurrent process has written but not yet committed (this
    happened in practice once with `ask`, before it got the same scoped-commit fix
    `cmd_ingest` was still missing).
    """
    processed: list[str] = []
    touched_paths: list[str] = []

    with manifest_lock():
        manifest = _load_manifest()
        for raw_path in _input_files():
            if limit is not None and len(processed) >= limit:
                break

            rel, outcome, touched = _process_if_new(raw_path, manifest)
            if outcome == "processed":
                processed.append(rel)
                touched_paths.extend(touched)

        if processed:
            indexer.rebuild_index()
            touched_paths.append(str((config.vault_path("index") / "MOC.md").relative_to(config.REPO_ROOT)))
            touched_paths.append(str(manifest_path().relative_to(config.REPO_ROOT)))
        _save_manifest(manifest)
    return {"processed": processed, "touched_paths": list(dict.fromkeys(touched_paths))}


def _input_files() -> list[Path]:
    """Every ingestable file across the configured input dirs (raw/ by default)."""
    files: list[Path] = []
    for name in config.load()["vault"].get("input_dirs", ["raw"]):
        files += sorted(
            p for p in config.vault_path(name).rglob("*") if p.is_file() and p.name not in SKIP_NAMES
        )
    return files


@contextmanager
def manifest_lock():
    """Serialize every read-modify-write of manifest.json across processes.

    `atlas ingest`, MCP add_source, and the web UI can all run at once; without this,
    the last one to save the manifest silently drops the others' entries, and those
    files get re-ingested on the next run.
    """
    lock_path = config.state_dir() / "manifest.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "w") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def run_ingest_url(url: str) -> dict:
    """Ingest a single URL directly, bypassing the raw/ scan queue.

    For when an agent's own research (e.g. after asking a question the wiki
    doesn't cover yet) finds a source worth keeping permanently -- it goes through
    the exact same pipeline as everything else, not a bolted-on note. Reuses the
    bare-URL raw file convention extractor.py already parses.
    """
    raw_dir = config.vault_path("raw")
    raw_path = raw_dir / f"{slugify(url)[:100] or 'source'}.md"
    if not raw_path.exists():
        raw_path.write_text(url)
    return ingest_single(raw_path)


def ingest_single(raw_path: Path) -> dict:
    """Ingest one input file directly, bypassing the directory scan. Used by
    add_source (URLs)."""
    with manifest_lock():
        manifest = _load_manifest()
        rel, outcome, touched = _process_if_new(raw_path, manifest)
        if outcome == "processed":
            indexer.rebuild_index()
            _save_manifest(manifest)
    # `rel` (used for manifest keys, above) is relative to universe/, matching every
    # existing manifest.json entry. Paths returned here get handed straight to
    # util.git_commit, which runs from the repo root -- so these need to be
    # REPO_ROOT-relative instead, same convention orchestrator/query.py already uses.
    repo_rel_raw = str(raw_path.relative_to(config.REPO_ROOT))

    if outcome == "unchanged":
        return {"status": "already_up_to_date", "raw_path": repo_rel_raw}
    if outcome == "failed":
        return {"status": "failed", "raw_path": repo_rel_raw}

    # touched == [raw_path, library_path, *concept_paths] -- see _process_if_new.
    moc_path = str((config.vault_path("index") / "MOC.md").relative_to(config.REPO_ROOT))
    manifest_rel = str(manifest_path().relative_to(config.REPO_ROOT))
    return {
        "status": "ingested",
        "raw_path": repo_rel_raw,
        "library_path": touched[1],
        "concept_paths": touched[2:],
        "touched_paths": touched + [moc_path, manifest_rel],
        "primary_concepts": manifest["items"][rel]["primary_concepts"],
        "related_concepts": manifest["items"][rel]["related_concepts"],
    }


def _process_if_new(raw_path: Path, manifest: dict) -> tuple[str, str, list[str]]:
    """Returns (rel_path, outcome, touched_paths). outcome is one of "processed" /
    "unchanged" / "failed"; touched_paths (REPO_ROOT-relative: [raw, library,
    *concepts]) is only populated when outcome == "processed". Shared by
    run_ingest's directory scan and run_ingest_url's single-target path -- same
    hash-check -> _ingest_one -> manifest-update logic either way; the distinct
    "failed" outcome (vs. "unchanged") matters for run_ingest_url's caller, which
    needs to know extraction actually broke rather than the URL simply already
    being ingested.
    """
    rel = str(raw_path.relative_to(config.vault_path()))
    digest = _hash_file(raw_path)
    if manifest["items"].get(rel, {}).get("hash") == digest:
        return rel, "unchanged", []

    print(f"Reading {rel} ...", flush=True)
    try:
        categorization = _ingest_one(raw_path)
    except ValueError as exc:
        print(f"skip {rel}: {exc}")
        return rel, "failed", []

    manifest["items"][rel] = {
        "hash": digest,
        "ingested_at": datetime.now(timezone.utc).isoformat(),
        "primary_concepts": categorization["primary"],
        "related_concepts": categorization["related"],
    }

    library_path = config.vault_path("library") / f"{slugify(raw_path.stem)}.md"
    touched = [str(raw_path.relative_to(config.REPO_ROOT)), str(library_path.relative_to(config.REPO_ROOT))]
    touched += [
        str((config.vault_path("concepts") / f"{c}.md").relative_to(config.REPO_ROOT))
        for c in categorization["primary"]
    ]
    return rel, "processed", touched


def _ingest_one(raw_path: Path) -> dict:
    extracted = extractor.extract(raw_path)
    summary = summarizer.summarize(extracted)
    # Slug is keyed on the stable raw filename, not the LLM's title -- title generation
    # isn't perfectly deterministic run-to-run, so keying on it would create a new
    # duplicate library note (rather than updating the same one) every time a raw file
    # gets reprocessed and the model happens to phrase the title slightly differently.
    slug = slugify(raw_path.stem)

    categorization = categorizer.categorize(summary)
    primary_names, related_names = categorization["primary"], categorization["related"]
    primary_slugs = [slugify(c) for c in primary_names]
    related_slugs = [slugify(c) for c in related_names]

    _write_library_note(slug, extracted, summary, primary_slugs, related_slugs)
    linker.add_concept_links(slug, primary_names, related_names)

    new_note = {"title": summary["title"], "slug": slug, "summary": summary["summary"]}
    if extracted.get("source_date"):
        new_note["source_date"] = extracted["source_date"]

    is_reference = bool(extracted.get("reference"))
    for concept_name, concept_slug in zip(primary_names, primary_slugs):
        concept_path = config.vault_path("concepts") / f"{concept_slug}.md"
        # Reference notes (e.g. a running example bank the user edits over time) are
        # still categorized/indexed normally -- the retriever only lists a library note
        # under a concept if it's a primary member (see retriever.py::_build_index), so
        # this is what keeps them queryable via ask_knowledge_graph. But their content
        # is deliberately kept OUT of the synthesized prose (concept_synth would distill
        # concrete examples into general lessons, which defeats the point of a verbatim
        # example bank) -- a deterministic pointer is added instead. Exception: a
        # brand-new concept still needs one real synthesis pass to get its
        # definition-first structure bootstrapped; only later re-edits of this same
        # reference note skip straight to the pointer.
        if is_reference and concept_path.exists():
            _add_pointer(concept_path, slug, summary["title"], REFERENCE_SECTION)
        else:
            _synthesize_concept(concept_name, concept_slug, new_note)

    return {"primary": primary_slugs, "related": related_slugs}


def _write_library_note(
    slug: str, extracted: dict, summary: dict, primary_slugs: list[str], related_slugs: list[str]
) -> None:
    post = frontmatter.Post(summary["summary"])
    post["title"] = summary["title"]
    post["source"] = extracted["source"]
    post["type"] = extracted["type"]
    post["tags"] = summary.get("tags", [])
    post["concepts"] = primary_slugs
    post["related_concepts"] = related_slugs
    post["date_ingested"] = date.today().isoformat()
    if extracted.get("source_date"):
        post["source_date"] = extracted["source_date"]
    if extracted.get("reference"):
        post["reference"] = True
    note_path = config.vault_path("library") / f"{slug}.md"
    note_path.write_text(frontmatter.dumps(post))


def _synthesize_concept(concept_name: str, concept_slug: str, new_note: dict) -> None:
    """Incrementally integrate one new note into a concept article.

    The current article body is already the accumulated synthesis of every prior
    member note -- it's revised with just the new note, never regenerated from
    every member's full text. Cost per ingest is therefore O(1) in concept size,
    not O(n), which matters once a concept has many members.
    """
    concepts_dir = config.vault_path("concepts")
    concept_path = concepts_dir / f"{concept_slug}.md"

    current_body = frontmatter.load(concept_path).content if concept_path.exists() else None
    print(f"  {'updating' if current_body is not None else 'creating'} topic: {concept_name}", flush=True)
    body = concept_synth.synthesize(concept_name, current_body, new_note)

    post = frontmatter.Post(body)
    post["title"] = concept_name
    concept_path.write_text(frontmatter.dumps(post))


REFERENCE_SECTION = (
    "## Reference Material",
    "Verbatim source material for direct use by agents/readers -- "
    "kept out of the synthesis above so concrete examples aren't distilled away:",
)


def _add_pointer(concept_path: Path, library_slug: str, title: str, section: tuple[str, str]) -> None:
    """Deterministic (no LLM) alternative to _synthesize_concept, for reference notes:
    add a link from the concept article to the library note instead
    of folding its content into the synthesized prose. The section must stay the
    article's last one, since new links are appended at the end. Matches on the link
    TARGET only, not the full display text -- title can change across re-edits of
    the same source file, and this must stay idempotent (not accumulate a duplicate
    pointer) either way.
    """
    post = frontmatter.load(concept_path)
    target_prefix = f"[[library/{library_slug}"
    if target_prefix in post.content:
        return

    marker, intro = section
    link_line = f"- [[library/{library_slug}|{title}]]"
    if marker in post.content:
        post.content = post.content.rstrip() + f"\n{link_line}\n"
    else:
        post.content = post.content.rstrip() + f"\n\n{marker}\n\n{intro}\n\n" + link_line + "\n"
    concept_path.write_text(frontmatter.dumps(post))


def _load_manifest() -> dict:
    path = manifest_path()
    if path.exists():
        return json.loads(path.read_text())
    return {"items": {}}


def _save_manifest(manifest: dict) -> None:
    path = manifest_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True))


def _hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
