"""Server-side sanitisation of whatever the extension sends.

The extension already strips scripts, styles, navigation and hidden elements
before uploading. This module repeats the work on arrival: the payload comes from
a browser page and must never be trusted to have been cleaned properly.
"""

import re
from typing import Optional

from bs4 import BeautifulSoup

_DROP_TAGS = (
    "script",
    "style",
    "noscript",
    "iframe",
    "svg",
    "canvas",
    "nav",
    "footer",
    "form",
    "template",
    "link",
    "meta",
)

_DROP_ROLES = ("navigation", "banner", "complementary", "contentinfo", "search")

_NOISE_PATTERN = re.compile(
    r"(cookie|advert|promo|newsletter|recommend|similar-jobs|related-jobs|breadcrumb|"
    r"social-share|tracking|footer|header|sidebar)",
    re.IGNORECASE,
)


def clean_html(html: str, max_chars: int = 120_000) -> str:
    """Removes non-content markup and returns compact HTML."""
    if not html:
        return ""

    soup = BeautifulSoup(html[:max_chars], "html.parser")

    for tag in soup.find_all(_DROP_TAGS):
        tag.decompose()

    for tag in soup.find_all(attrs={"role": True}):
        if str(tag.get("role", "")).lower() in _DROP_ROLES:
            tag.decompose()

    for tag in soup.find_all(attrs={"aria-hidden": "true"}):
        tag.decompose()

    for tag in soup.find_all(attrs={"class": True}):
        classes = " ".join(tag.get("class") or [])
        if _NOISE_PATTERN.search(classes):
            tag.decompose()

    # Attributes carry tracking ids and inline styles that are pure noise here.
    for tag in soup.find_all(True):
        keep = {}
        for attribute in ("href", "datetime", "itemprop", "content"):
            if tag.has_attr(attribute):
                keep[attribute] = tag[attribute]
        tag.attrs = keep

    return str(soup)


def html_to_text(html: str) -> str:
    """Flattens HTML into readable text, keeping paragraph and list breaks."""
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(_DROP_TAGS):
        tag.decompose()
    for tag in soup.find_all(["br"]):
        tag.replace_with("\n")
    for tag in soup.find_all(["p", "li", "div", "h1", "h2", "h3", "h4", "tr"]):
        tag.append("\n")
    text = soup.get_text(" ")
    return normalise_text(text)


def normalise_text(text: Optional[str]) -> str:
    if not text:
        return ""
    text = text.replace("\r", "\n").replace(" ", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return "\n".join(line.strip() for line in text.split("\n")).strip()


def strip_tracking_params(url: str) -> str:
    """Drops the tracking query parameters job boards attach to share links."""
    if not url or "?" not in url:
        return url

    from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

    noisy_prefixes = ("utm_", "trk", "ref", "src", "source", "lipi", "li_")
    noisy_exact = {
        "refid",
        "trackingid",
        "position",
        "pagenum",
        "originalsubdomain",
        "eBP",
        "gh_src",
        "ashby_jid_source",
    }

    parts = urlsplit(url)
    kept = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not (
            key.lower() in noisy_exact
            or any(key.lower().startswith(prefix) for prefix in noisy_prefixes)
        )
    ]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(kept), ""))
