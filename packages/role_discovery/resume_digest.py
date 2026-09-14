"""Flattens a Reactive Resume document into plain text the agents can reason over.

The master CV is the richest description of the candidate we hold: full work
experience, projects, skills with keywords, education and summaries. Role
discovery is only as good as this digest, so it keeps the structure visible
(section headings, one entry per line) rather than dumping raw JSON.
"""

import re
from typing import Any, Dict, Iterable, List, Optional

from packages.reactive_resume.models import ResumeDetail

# Sections rendered in this order; anything else is appended afterwards.
_SECTION_ORDER = [
    "summary",
    "experience",
    "projects",
    "skills",
    "education",
    "certifications",
    "awards",
    "publications",
    "volunteer",
    "languages",
    "interests",
]

_ITEM_FIELDS = [
    ("position", ""),
    ("name", ""),
    ("company", " at "),
    ("institution", " at "),
    ("organization", " at "),
    ("studyType", ", "),
    ("area", " "),
    ("issuer", " — "),
    ("publisher", " — "),
    ("level", " — level "),
    ("location", " — "),
    ("date", " — "),
]


def _strip_html(value: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", value, flags=re.IGNORECASE)
    text = re.sub(r"</(p|li|div|h[1-6])>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&")
    text = re.sub(r"[ \t]+", " ", text)
    return "\n".join(line.strip() for line in text.split("\n") if line.strip())


def _render_item(item: Dict[str, Any]) -> str:
    if not isinstance(item, dict):
        return str(item)
    if item.get("visible") is False:
        return ""

    head_parts: List[str] = []
    for field, separator in _ITEM_FIELDS:
        value = item.get(field)
        if value in (None, "", []):
            continue
        head_parts.append(f"{separator}{value}" if head_parts else str(value))
    head = "".join(head_parts).strip()

    body_parts: List[str] = []
    for field in ("description", "summary", "content"):
        value = item.get(field)
        if isinstance(value, str) and value.strip():
            body_parts.append(_strip_html(value))

    keywords = item.get("keywords")
    if isinstance(keywords, list) and keywords:
        body_parts.append("Keywords: " + ", ".join(str(k) for k in keywords))

    lines = [part for part in [head] + body_parts if part]
    if not lines:
        return ""
    return "- " + "\n  ".join("\n".join(lines).split("\n"))


def _section_items(section: Any) -> Iterable[Dict[str, Any]]:
    if isinstance(section, dict):
        items = section.get("items")
        if isinstance(items, list):
            return [item for item in items if isinstance(item, dict)]
    if isinstance(section, list):
        return [item for item in section if isinstance(item, dict)]
    return []


def _render_section(key: str, section: Any) -> str:
    if isinstance(section, dict) and section.get("visible") is False:
        return ""

    title = str((section or {}).get("name") or key).strip() if isinstance(section, dict) else key
    lines: List[str] = []

    if isinstance(section, dict):
        content = section.get("content")
        if isinstance(content, str) and content.strip():
            lines.append(_strip_html(content))

    for item in _section_items(section):
        rendered = _render_item(item)
        if rendered:
            lines.append(rendered)

    if not lines:
        return ""
    return f"## {title.upper()}\n" + "\n".join(lines)


def build_resume_digest(resume: Optional[ResumeDetail], max_chars: int = 14000) -> str:
    """Renders the master CV as structured plain text, truncated to max_chars."""
    if resume is None:
        return ""

    data = resume.data
    blocks: List[str] = []

    basics = data.basics
    header = [f"Name: {basics.name}"]
    if basics.headline:
        header.append(f"Headline: {basics.headline}")
    if basics.location:
        header.append(f"Location: {basics.location}")
    if basics.url:
        header.append(f"Website: {basics.url}")
    blocks.append("## BASICS\n" + "\n".join(header))

    sections = data.sections or {}
    seen: set = set()
    for key in _SECTION_ORDER:
        if key in sections:
            seen.add(key)
            rendered = _render_section(key, sections[key])
            if rendered:
                blocks.append(rendered)

    for key, section in sections.items():
        if key in seen or key in ("picture", "references"):
            continue
        rendered = _render_section(key, section)
        if rendered:
            blocks.append(rendered)

    digest = "\n\n".join(blocks)
    if len(digest) > max_chars:
        digest = digest[:max_chars].rsplit("\n", 1)[0] + "\n[digest truncated]"
    return digest
