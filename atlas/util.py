import re
import subprocess

from atlas import config


def slugify(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def git_commit(message: str, paths: list[str] | None = None) -> None:
    """Commit to git, scoped to `paths` when given.

    Scoping matters once multiple entrypoints (CLI, MCP server, concurrent ingest
    runs) can write to the vault around the same time: `git add -A` would sweep up
    whatever another in-flight process has written but not yet committed,
    misattributing its output to this run's commit message. Passing explicit paths
    keeps each command's commit to exactly what that run itself touched.

    The scoping has to be on the `git commit` too, not just the `git add`:
    `git commit -m` with no pathspec commits the whole index, so anything a
    human (or another process) had staged for unrelated reasons would be
    swallowed into this run's commit -- the exact misattribution the scoped
    `git add` exists to prevent.
    """
    if not _in_git_repo():
        # Auto-commit is a safety net (every run one `git revert` away), not a
        # requirement: someone who downloaded a ZIP has no repo, and the run's
        # output is already on disk either way.
        print("git commit skipped: this folder isn't a git repository (run `git init` to enable history).")
        return

    if paths:
        paths = _drop_ignored(paths)
        if not paths:
            print("git commit skipped: every path this run touched is git-ignored.")
            return

    add_cmd = ["git", "add"] + (paths if paths else ["-A"])
    subprocess.run(add_cmd, cwd=config.REPO_ROOT, check=True)
    commit_cmd = ["git", "commit", "-m", message] + (["--"] + paths if paths else [])
    result = subprocess.run(
        commit_cmd, cwd=config.REPO_ROOT, capture_output=True, text=True
    )
    if result.returncode == 0:
        print("Committed to git.")
    else:
        print(f"git commit skipped: {(result.stdout + result.stderr).strip()}")


def _drop_ignored(paths: list[str]) -> list[str]:
    """Drop paths git is configured to ignore.

    Callers hand us every file a run touched, and some of those legitimately
    live in ignored trees -- universe/raw/ (inputs), universe/output/ (personal
    Q&A history), atlas/state/manifest.json (machine-local ingest hashes). They
    are written on purpose and simply aren't shared. `git add` exits non-zero on
    an ignored path, though, which with check=True aborted the whole commit --
    taking the library/concept/index files that DO belong in the repo down with
    it.
    """
    result = subprocess.run(
        ["git", "check-ignore", "--stdin"],
        cwd=config.REPO_ROOT,
        input="\n".join(paths),
        capture_output=True,
        text=True,
    )
    # Exit 1 just means "nothing matched"; only >1 is a real failure.
    if result.returncode > 1:
        raise RuntimeError(f"git check-ignore failed: {result.stderr.strip()}")
    ignored = {line.strip() for line in result.stdout.splitlines() if line.strip()}
    return [p for p in paths if p not in ignored]


def _in_git_repo() -> bool:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=config.REPO_ROOT,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:  # git itself isn't installed
        return False
    return result.returncode == 0 and result.stdout.strip() == "true"
