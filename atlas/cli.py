from __future__ import annotations

import sys

USAGE = (
    'Usage: atlas ingest [--limit N] | atlas ask "question" [--no-file-back] | atlas lint\n'
    "       atlas ui [--port N] [--no-browser]\n"
    "       add --vault demo (or --vault <folder>) to ingest/ask/lint to work on another knowledge graph"
)


def ingest_and_commit(limit: int | None = None) -> dict:
    """`atlas ingest` minus the exit code: shared by the CLI and the web UI so both
    run identical code. Also reports which topics this run created vs. updated
    (the UI's tour points at whichever topic actually changed -- the categorizer
    isn't deterministic, so that can't be known in advance)."""
    from atlas import config
    from atlas.orchestrator.ingest import run_ingest
    from atlas.util import git_commit

    before = {p.stem for p in config.vault_path("concepts").glob("*.md")}
    result = run_ingest(limit=limit)
    processed = result["processed"]
    if not processed:
        print("Nothing new to ingest.")
        return {"processed": [], "created_topics": [], "updated_topics": []}

    print(f"Ingested {len(processed)} item(s):")
    for item in processed:
        print(f"  - {item}")

    git_commit("ingest: " + ", ".join(processed), paths=result["touched_paths"])
    concepts_prefix = str(config.vault_path("concepts").relative_to(config.REPO_ROOT)) + "/"
    touched = list(dict.fromkeys(
        p.removeprefix(concepts_prefix).removesuffix(".md")
        for p in result["touched_paths"] if p.startswith(concepts_prefix)
    ))
    return {
        "processed": processed,
        "created_topics": [c for c in touched if c not in before],
        "updated_topics": [c for c in touched if c in before],
    }


def cmd_ingest(limit: int | None = None) -> int:
    ingest_and_commit(limit)
    return 0


def cmd_ask(question: str, file_back: bool = True) -> int:
    from atlas.orchestrator.query import run_ask
    from atlas.util import git_commit

    result = run_ask(question, file_back=file_back, caller="cli")
    print(f"Answer written to {result['output_path']}")
    print("Filed back into wiki." if result["filed_back"] else "No new finding filed back.")

    paths = [result["output_path"]]
    if result["filed_back_path"]:
        paths.append(result["filed_back_path"])
    git_commit(f"ask: {result['question_slug']}", paths=paths)
    return 0


def cmd_lint() -> int:
    from atlas.orchestrator.lint import run_lint

    report = run_lint()
    total = report.issue_count()
    if total == 0:
        print("No issues found.")
        return 0

    for check_name, issues in vars(report).items():
        if not issues:
            continue
        print(f"\n{check_name.replace('_', ' ')} ({len(issues)}):")
        for issue in issues:
            print(f"  - {issue}")
    print(f"\n{total} issue(s) found.")
    return 0


def cmd_ui(args: list[str]) -> int:
    from atlas.ui.server import serve

    port = 8765
    if "--port" in args:
        idx = args.index("--port")
        try:
            port = int(args[idx + 1])
        except (IndexError, ValueError):
            print("Usage: atlas ui [--port N] [--no-browser]")
            return 1
    serve(port=port, open_browser="--no-browser" not in args)
    return 0


def _apply_vault_flag() -> bool:
    """`--vault demo|<folder>` anywhere on the command line selects the knowledge
    graph to work on (default: universe/). Removed from argv so the per-command
    parsing below never sees it."""
    if "--vault" not in sys.argv:
        return True
    idx = sys.argv.index("--vault")
    if idx + 1 >= len(sys.argv):
        print("Usage: --vault demo  (or --vault <folder inside this repo>)")
        return False
    name = sys.argv[idx + 1]
    del sys.argv[idx : idx + 2]

    import os

    from atlas import config, demo

    if name == "demo":
        demo.ensure_demo()
    try:
        path = config.resolve_vault(name)
    except ValueError as exc:
        print(exc)
        return False
    if not path.is_dir():
        print(f"No knowledge graph folder at {path}")
        return False
    os.environ["ATLAS_VAULT"] = str(path)
    return True


def main() -> int:
    if not _apply_vault_flag():
        return 1
    if len(sys.argv) < 2 or sys.argv[1] not in ("ingest", "ask", "lint", "ui"):
        print(USAGE)
        return 1

    if sys.argv[1] == "lint":
        return cmd_lint()

    if sys.argv[1] == "ui":
        return cmd_ui(sys.argv[2:])

    if sys.argv[1] == "ingest":
        limit = None
        if "--limit" in sys.argv:
            idx = sys.argv.index("--limit")
            try:
                limit = int(sys.argv[idx + 1])
            except (IndexError, ValueError):
                print("Usage: atlas ingest [--limit N]")
                return 1
        return cmd_ingest(limit=limit)

    # ask
    args = sys.argv[2:]
    file_back = "--no-file-back" not in args
    args = [a for a in args if a != "--no-file-back"]
    if not args:
        print('Usage: atlas ask "question" [--no-file-back]')
        return 1
    question = " ".join(args)
    return cmd_ask(question, file_back=file_back)


if __name__ == "__main__":
    raise SystemExit(main())
