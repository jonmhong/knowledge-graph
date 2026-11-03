from __future__ import annotations

import os
from contextlib import contextmanager
from contextvars import ContextVar
from functools import lru_cache
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = REPO_ROOT / "atlas" / "config.yaml"

# Which knowledge graph (vault) the pipeline reads and writes. Resolution order:
#   1. use_vault(...) in the current thread/context -- how the web UI serves the
#      demo and the user's own graph side by side, one request at a time;
#   2. the ATLAS_VAULT environment variable -- how `atlas --vault demo ...` works;
#   3. vault.root in config.yaml (universe/) -- the default, and the only graph the
#      MCP server ever touches.
# A vault must live inside the repo: every path the pipeline reports (and hands to
# git_commit) is REPO_ROOT-relative.
_active_vault: ContextVar[Path | None] = ContextVar("atlas_active_vault", default=None)


@lru_cache
def load() -> dict:
    return yaml.safe_load(CONFIG_PATH.read_text())


def resolve_vault(name_or_path: str | Path) -> Path:
    path = Path(name_or_path)
    path = (path if path.is_absolute() else REPO_ROOT / path).resolve()
    if REPO_ROOT != path and REPO_ROOT not in path.parents:
        raise ValueError(f"vault must be inside the repo ({REPO_ROOT}): {path}")
    return path


def vault_root() -> Path:
    override = _active_vault.get() or os.environ.get("ATLAS_VAULT")
    if override:
        return resolve_vault(override)
    return REPO_ROOT / load()["vault"]["root"]


@contextmanager
def use_vault(name_or_path: str | Path):
    token = _active_vault.set(resolve_vault(name_or_path))
    try:
        yield
    finally:
        _active_vault.reset(token)


def vault_path(*parts: str) -> Path:
    return vault_root().joinpath(*parts)


def state_dir() -> Path:
    """Per-vault ingest bookkeeping (manifest + lock). Lives inside the vault, in a
    dot-folder Obsidian ignores, so each knowledge graph carries its own record of
    what it has already read and two graphs can never confuse each other's."""
    return vault_path(".atlas")


def agent_backend_spec(role: str) -> dict:
    return load()["agents"][role]
