from __future__ import annotations

import frontmatter

from atlas import config
from atlas.util import slugify


def add_concept_links(slug: str, primary_names: list[str], related_names: list[str]) -> None:
    """Link a library note out to its concept article(s) -- hub-and-spoke, not pairwise.

    Notes link to their concepts; concept articles are the hub that link back to every
    member note (already true via concept synthesis). This deliberately avoids directly
    cross-linking every note that happens to share a concept with every other one, which
    would be an O(n^2) blowup of "Related" links as a concept's membership grows.
    """
    if not primary_names and not related_names:
        return

    note_path = config.vault_path("library") / f"{slug}.md"
    post = frontmatter.load(note_path)

    lines = [f"- [[concepts/{slugify(name)}|{name}]]" for name in primary_names]
    lines += [f"- [[concepts/{slugify(name)}|{name}]] _(related)_" for name in related_names]

    body = post.content.split("\n## Concepts")[0].rstrip()
    body += "\n\n## Concepts\n" + "\n".join(lines) + "\n"
    post.content = body
    note_path.write_text(frontmatter.dumps(post))
