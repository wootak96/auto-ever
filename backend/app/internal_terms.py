"""Site-specific vocabulary, loaded from a file instead of hard-coded.

The router force-includes the Confluence index whenever a question mentions a
term that only exists inside one organisation — a product name, an internal
acronym, an office, an index-namespace prefix. That list is deployment data,
not logic: it differs per company and it is exactly the kind of thing that
should not sit in a public repository.

So it lives in `internal_terms.json`, which is gitignored. What ships is
`internal_terms.example.json` with placeholder terms, and that is also the
fallback when no real file is present — the mechanism keeps working, it just
matches nothing real until the deployment supplies its own list.

Resolution order:

1. `$INTERNAL_TERMS_FILE`, if set
2. `app/internal_terms.json`
3. `app/internal_terms.example.json`

A missing or malformed file is never fatal. Routing degrades to the LLM's own
judgement, which is the same behaviour as a question with no internal term in
it, and a warning names the file that was actually used.
"""

from __future__ import annotations

import json
import logging
import os
import re
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

_HERE = Path(__file__).parent
_REAL = _HERE / "internal_terms.json"
_EXAMPLE = _HERE / "internal_terms.example.json"

# Category -> whether an ASCII word boundary is wrapped around each term.
# Acronyms need it ("DSP" must not fire inside "DSPACE"); product names are
# distinctive enough to match as substrings; CJK has no word boundary for
# `\b` to find, so applying it there would silently never match.
_BOUNDED = {
    "products": False,
    "acronyms": True,
    "locations": False,
    "org": False,
    "namespaces": False,
}

_LABELS = {
    "products": "플랫폼/제품명",
    "acronyms": "사내 약어",
    "locations": "사옥/지역",
    "org": "조직/도메인",
    "namespaces": "사내 ES 네임스페이스 경로",
}


def _resolve_path() -> Path:
    override = os.getenv("INTERNAL_TERMS_FILE", "").strip()
    if override:
        path = Path(override)
        if path.is_file():
            return path
        logger.warning("INTERNAL_TERMS_FILE=%s not found; falling back", override)
    if _REAL.is_file():
        return _REAL
    return _EXAMPLE


@lru_cache
def load_terms() -> dict[str, list[str]]:
    """Category -> terms. Empty categories on any read or parse failure."""
    path = _resolve_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("internal terms unreadable (%s): %s", path, exc)
        return {key: [] for key in _BOUNDED}
    if path == _EXAMPLE:
        logger.warning(
            "using placeholder internal terms from %s — create %s to enable "
            "internal-noun routing for this deployment",
            _EXAMPLE.name,
            _REAL.name,
        )
    terms: dict[str, list[str]] = {}
    for key in _BOUNDED:
        values = raw.get(key) or []
        terms[key] = [str(v).strip() for v in values if str(v).strip()]
    return terms


def regex_alternatives() -> list[str]:
    """Escaped regex alternatives for every configured term."""
    out: list[str] = []
    for key, bounded in _BOUNDED.items():
        for term in load_terms().get(key, []):
            escaped = re.escape(term)
            out.append(rf"\b{escaped}\b" if bounded else escaped)
    return out


def prompt_block(indent: str = "    ") -> str:
    """The `사내 전용 고유명사` lines injected into the INDEX_ROUTE prompt.

    Empty categories are dropped rather than rendered as a dangling label, so
    a deployment that only defines product names does not ship the LLM an
    empty `사내 약어 —` line to interpret.
    """
    lines = []
    for key, label in _LABELS.items():
        values = load_terms().get(key, [])
        if values:
            lines.append(f"{indent}{label} — {', '.join(values)}")
    if not lines:
        return f"{indent}(이 배포에는 등록된 사내 고유명사가 없습니다.)"
    return "\n".join(lines)


def example_term() -> str:
    """One representative term, for use in prompt examples."""
    for key in ("products", "acronyms", "namespaces"):
        values = load_terms().get(key, [])
        if values:
            return values[0]
    return "사내 제품명"
