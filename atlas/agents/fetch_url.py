from __future__ import annotations

import trafilatura


def fetch_url_text(url: str) -> tuple[str, str | None]:
    """Fetch a URL and extract its main readable article text.

    Uses trafilatura, which strips navigation/ads/boilerplate rather than
    returning raw HTML -- deterministic parsing, no LLM call needed.
    Returns (text, title) where title may be None if the page has no usable
    metadata title.
    """
    try:
        downloaded = trafilatura.fetch_url(url)
    except Exception as exc:  # network errors, invalid URL, TLS issues, etc.
        raise ValueError(f"failed to fetch {url}: {exc}") from exc

    if not downloaded:
        raise ValueError(f"failed to fetch {url}: no response")

    text = trafilatura.extract(downloaded, url=url, output_format="txt", include_comments=False)
    if not text or not text.strip():
        raise ValueError(f"no extractable article text at {url}")

    metadata = trafilatura.extract_metadata(downloaded)
    title = metadata.title if metadata and metadata.title else None
    return text.strip(), title
