from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import frontmatter

from atlas import config

_WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)")
_SECTION_RE = re.compile(r"^## ", re.MULTILINE)

# See SPEC.md, "Maintenance: Concept Granularity & Splitting" -- these thresholds
# only flag a candidate for a human to review against that section's diagnosis
# criteria (redundancy vs. genuinely separable sub-disciplines). Lint detects,
# it never decides to split anything itself.
OVERGROWN_LINE_THRESHOLD = 100
OVERGROWN_SECTION_THRESHOLD = 4


@dataclass
class LintReport:
    missing_frontmatter: list[str] = field(default_factory=list)
    broken_wikilinks: list[str] = field(default_factory=list)
    dangling_concept_refs: list[str] = field(default_factory=list)
    orphaned_concepts: list[str] = field(default_factory=list)
    overgrown_concepts: list[str] = field(default_factory=list)

    def issue_count(self) -> int:
        return sum(len(v) for v in vars(self).values())


def run_lint() -> LintReport:
    """Deterministic health checks over universe/ -- no LLM calls, same file-scan
    approach as indexer.rebuild_index(). Read-only: lint reports issues for a human
    (or a future auto-fix pass) to act on, it never edits the vault itself.
    """
    library_dir = config.vault_path("library")
    concepts_dir = config.vault_path("concepts")

    library_notes = {p.stem: frontmatter.load(p) for p in sorted(library_dir.glob("*.md"))}
    concept_notes = {p.stem: frontmatter.load(p) for p in sorted(concepts_dir.glob("*.md"))}

    report = LintReport()
    _check_library_frontmatter(library_notes, report)
    _check_concept_frontmatter(concept_notes, report)
    _check_dangling_concept_refs(library_notes, concept_notes, report)
    _check_broken_wikilinks(library_dir, concepts_dir, library_notes, concept_notes, report)
    _check_orphaned_concepts(library_notes, concept_notes, report)
    _check_overgrown_concepts(concept_notes, report)
    return report


def _check_library_frontmatter(library_notes: dict, report: LintReport) -> None:
    for slug, post in library_notes.items():
        missing = [f for f in ("title", "source", "type") if not post.get(f)]
        if missing:
            report.missing_frontmatter.append(f"library/{slug}.md missing {missing}")


def _check_concept_frontmatter(concept_notes: dict, report: LintReport) -> None:
    for slug, post in concept_notes.items():
        if not post.get("title"):
            report.missing_frontmatter.append(f"concepts/{slug}.md missing ['title']")


def _check_dangling_concept_refs(library_notes: dict, concept_notes: dict, report: LintReport) -> None:
    for slug, post in library_notes.items():
        for field_name in ("concepts", "related_concepts"):
            for ref in post.get(field_name, []):
                if ref not in concept_notes:
                    report.dangling_concept_refs.append(
                        f"library/{slug}.md references missing concept '{ref}' via {field_name}"
                    )


def _check_broken_wikilinks(
    library_dir: Path, concepts_dir: Path, library_notes: dict, concept_notes: dict, report: LintReport
) -> None:
    for prefix, notes in (("library", library_notes), ("concepts", concept_notes)):
        for slug, post in notes.items():
            for target in _WIKILINK_RE.findall(post.content):
                target = target.strip()
                if not _wikilink_target_exists(target, library_dir, concepts_dir):
                    report.broken_wikilinks.append(f"{prefix}/{slug}.md links to missing [[{target}]]")


def _wikilink_target_exists(target: str, library_dir: Path, concepts_dir: Path) -> bool:
    if "/" not in target:
        # Bare slug with no folder prefix -- not a convention this vault's linker/
        # indexer uses (always `library/slug` or `concepts/slug`), but check both
        # dirs rather than assuming malformed.
        return (library_dir / f"{target}.md").exists() or (concepts_dir / f"{target}.md").exists()
    folder, slug = target.split("/", 1)
    base = library_dir if folder == "library" else concepts_dir if folder == "concepts" else None
    if base is None:
        return True  # link into e.g. index/ or raw/ -- not this lint's concern
    return (base / f"{slug}.md").exists()


def _check_orphaned_concepts(library_notes: dict, concept_notes: dict, report: LintReport) -> None:
    referenced: set[str] = set()
    for post in library_notes.values():
        referenced.update(post.get("concepts", []))
        referenced.update(post.get("related_concepts", []))
    for slug in concept_notes:
        if slug not in referenced:
            report.orphaned_concepts.append(f"concepts/{slug}.md has no library notes referencing it")


def _check_overgrown_concepts(concept_notes: dict, report: LintReport) -> None:
    for slug, post in concept_notes.items():
        lines = post.content.count("\n") + 1
        sections = len(_SECTION_RE.findall(post.content))
        if lines >= OVERGROWN_LINE_THRESHOLD and sections >= OVERGROWN_SECTION_THRESHOLD:
            report.overgrown_concepts.append(
                f"concepts/{slug}.md is {lines} lines across {sections} sections -- "
                "review against SPEC.md's concept-splitting criteria"
            )
