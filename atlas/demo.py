"""The demo knowledge graph: a separate, fully usable vault people can learn on.

`atlas/demo_template/` is the pristine demo as shipped (committed): 7 articles
already compiled by the real pipeline, plus 3 raw articles left waiting so the
first-run tour can show a live build. `demo/` is the working copy people actually
use -- created from the template on first launch, git-ignored so experiments
never show up as repo changes, and restorable with reset_demo().

Kept apart from the user's own graph (universe/) on purpose: if both lived in one
vault, the categorizer would happily file the user's real sources under demo
topics, and the demo could never be cleanly separated out again.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from atlas import config

TEMPLATE_DIR = config.REPO_ROOT / "atlas" / "demo_template"
DEMO_DIR = config.REPO_ROOT / "demo"


def available() -> bool:
    return TEMPLATE_DIR.is_dir()


def ensure_demo() -> Path:
    """Create demo/ from the template if it doesn't exist yet. Never touches an
    existing demo/ (that's reset_demo's job)."""
    if not DEMO_DIR.exists() and available():
        shutil.copytree(TEMPLATE_DIR, DEMO_DIR)
    return DEMO_DIR


def reset_demo() -> Path:
    """Restore demo/ to exactly the shipped template. Only ever deletes DEMO_DIR --
    asserted, because this is the one place the UI removes a whole folder."""
    if not available():
        raise RuntimeError("The demo template is missing from this copy of Atlas.")
    target = DEMO_DIR.resolve()
    user_vault = (config.REPO_ROOT / config.load()["vault"]["root"]).resolve()
    if target.name != "demo" or target.parent != config.REPO_ROOT.resolve() or target == user_vault:
        raise RuntimeError(f"refusing to reset unexpected path: {target}")
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(TEMPLATE_DIR, target)
    return target
