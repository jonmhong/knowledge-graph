from __future__ import annotations

import re
from pathlib import Path

from atlas.agents.fetch_url import fetch_url_text

try:
    from pypdf import PdfReader
except ImportError:  # pragma: no cover
    PdfReader = None

TEXT_EXTENSIONS = {".md", ".txt"}
URL_RE = re.compile(r"^https?://\S+$")
MARKER_RE = re.compile(r"^([a-zA-Z_]+):\s*(.+)$")
KNOWN_MARKERS = {"source_date", "reference"}


def extract(raw_path: Path) -> dict:
    """Pull plain text + basic metadata out of a raw/ item.

    Deterministic file-format parsing, not judgment -- no LLM call needed here
    (the one exception is fetching a URL's page, which needs the network, but
    still no LLM). Images/repos/datasets aren't handled yet (see SPEC.md V3+);
    this raises a clear error so an unsupported drop in raw/ is skipped, not
    silently mishandled.
    """
    suffix = raw_path.suffix.lower()

    markers: dict[str, str] = {}
    if suffix in TEXT_EXTENSIONS:
        raw_content = raw_path.read_text(encoding="utf-8", errors="replace")
        stripped = raw_content.strip()
        if URL_RE.match(stripped):
            return _extract_url(stripped, raw_path)
        text, markers = _strip_markers(raw_content)
        source = raw_path.name
        file_type = suffix.lstrip(".")
    elif suffix == ".pdf":
        if PdfReader is None:
            raise RuntimeError("pypdf is required to ingest PDFs (pip install pypdf)")
        reader = PdfReader(str(raw_path))
        text = "\n\n".join(page.extract_text() or "" for page in reader.pages)
        source = raw_path.name
        file_type = "pdf"
    else:
        raise ValueError(f"unsupported raw file type: {raw_path.suffix or '(no extension)'}")

    if not text.strip():
        raise ValueError("no extractable text found")

    result = {
        "title": _guess_title(text, raw_path),
        "source": source,
        "type": file_type,
        "text": text.strip(),
    }
    if markers.get("source_date"):
        result["source_date"] = markers["source_date"]
    if markers.get("reference", "").lower() in ("true", "yes", "1"):
        result["reference"] = True
    return result


def _strip_markers(raw_content: str) -> tuple[str, dict[str, str]]:
    """A raw file can open with one or more `key: value` marker lines (e.g.
    `source_date: Sept 2025`, `reference: true`) before the actual content --
    manual annotations for things the pipeline can't infer from the text itself.
    Only known keys are recognized, so ordinary body text that happens to look
    like `Word: text` (common in markdown, e.g. "Platform: TikTok") is left alone
    and ends the marker block. Consumed markers (and surrounding blank lines) are
    stripped before the text reaches the summarizer.
    """
    lines = raw_content.splitlines()
    markers: dict[str, str] = {}
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        if not stripped:
            i += 1
            continue
        m = MARKER_RE.match(stripped)
        if not m or m.group(1).lower() not in KNOWN_MARKERS:
            break
        markers[m.group(1).lower()] = m.group(2).strip()
        i += 1
    return "\n".join(lines[i:]).lstrip("\n"), markers


def _extract_url(url: str, raw_path: Path) -> dict:
    text, fetched_title = fetch_url_text(url)
    return {
        "title": fetched_title or _guess_title(text, raw_path),
        "source": url,
        "type": "url",
        "text": text,
    }


def _guess_title(text: str, raw_path: Path) -> str:
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("# "):
            return line[2:].strip()
    return raw_path.stem.replace("-", " ").replace("_", " ").title()
