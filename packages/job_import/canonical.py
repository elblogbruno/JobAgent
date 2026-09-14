"""Resolving the original application URL behind an aggregator listing.

A LinkedIn posting is a copy. The company's own ATS page is the record, and it is
the URL the application pipeline should use. When the real one can be identified
reliably, both are stored.
"""

import re
from typing import List, Optional, Tuple
from urllib.parse import urlsplit

from packages.domain.enums import JobSourceType
from packages.job_import.cleaning import strip_tracking_params

# hostname fragment -> (source type, confidence). Order matters: the first match wins.
ATS_HOSTS: List[Tuple[str, JobSourceType]] = [
    ("jobs.ashbyhq.com", JobSourceType.ASHBY),
    ("ashbyhq.com", JobSourceType.ASHBY),
    ("boards.greenhouse.io", JobSourceType.GREENHOUSE),
    ("job-boards.greenhouse.io", JobSourceType.GREENHOUSE),
    ("greenhouse.io", JobSourceType.GREENHOUSE),
    ("jobs.lever.co", JobSourceType.LEVER),
    ("lever.co", JobSourceType.LEVER),
    ("apply.workable.com", JobSourceType.WORKABLE),
    ("workable.com", JobSourceType.WORKABLE),
    ("jobs.smartrecruiters.com", JobSourceType.SMARTRECRUITERS),
    ("smartrecruiters.com", JobSourceType.SMARTRECRUITERS),
    ("myworkdayjobs.com", JobSourceType.WORKDAY),
    ("workday.com", JobSourceType.WORKDAY),
]

AGGREGATOR_HOSTS = {
    "linkedin.com": JobSourceType.LINKEDIN,
    "infojobs.net": JobSourceType.INFOJOBS,
    "indeed.com": JobSourceType.INDEED,
    "glassdoor.com": JobSourceType.GENERIC_WEB,
    "google.com": JobSourceType.GENERIC_WEB,
}

_URL_PATTERN = re.compile(r"https?://[^\s\"'<>)]+", re.IGNORECASE)


def hostname_of(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


def source_for_url(url: str) -> JobSourceType:
    """Classifies a URL into a known source type."""
    host = hostname_of(url)
    if not host:
        return JobSourceType.GENERIC_WEB
    for fragment, source in ATS_HOSTS:
        if host.endswith(fragment) or fragment in host:
            return source
    for fragment, source in AGGREGATOR_HOSTS.items():
        if host.endswith(fragment):
            return source
    return JobSourceType.COMPANY_CAREERS


def is_ats_url(url: str) -> bool:
    host = hostname_of(url)
    return any(host.endswith(fragment) or fragment in host for fragment, _ in ATS_HOSTS)


def find_ats_urls(*texts: Optional[str]) -> List[str]:
    """Collects every ATS application URL that appears in the supplied text."""
    found: List[str] = []
    for text in texts:
        if not text:
            continue
        for match in _URL_PATTERN.findall(text):
            candidate = match.rstrip(".,);\"'")
            if is_ats_url(candidate) and candidate not in found:
                found.append(candidate)
    return found


def resolve_canonical(
    page_url: str,
    canonical_hint: Optional[str] = None,
    apply_url_hint: Optional[str] = None,
    cleaned_html: Optional[str] = None,
    visible_text: Optional[str] = None,
) -> Tuple[str, str, JobSourceType]:
    """Returns (canonical_url, apply_url, source).

    The canonical URL is the company or ATS page whenever one can be identified
    with confidence; otherwise the page the user was looking at stands, because a
    wrong canonical URL is worse than an aggregator one.
    """
    page_url = strip_tracking_params(page_url)

    candidates: List[str] = []
    for hint in (apply_url_hint, canonical_hint):
        if hint and is_ats_url(hint):
            candidates.append(strip_tracking_params(hint))
    candidates.extend(
        strip_tracking_params(url) for url in find_ats_urls(cleaned_html, visible_text)
    )

    if is_ats_url(page_url):
        canonical = page_url
    elif candidates:
        canonical = candidates[0]
    elif canonical_hint:
        canonical = strip_tracking_params(canonical_hint)
    else:
        canonical = page_url

    apply_url = candidates[0] if candidates else canonical
    return canonical, apply_url, source_for_url(canonical)


def extract_source_job_id(url: str, source: JobSourceType) -> str:
    """Pulls the board's own identifier out of a job URL, for deduplication."""
    path = urlsplit(url).path.strip("/")
    query = urlsplit(url).query
    segments = [segment for segment in path.split("/") if segment]

    if source == JobSourceType.LINKEDIN:
        match = re.search(r"(?:view/)?(?:[\w-]*-)?(\d{8,})", path) or re.search(
            r"currentJobId=(\d+)", query
        )
        if match:
            return match.group(1)
    elif source == JobSourceType.GREENHOUSE:
        match = re.search(r"/jobs/(\d+)", path) or re.search(r"gh_jid=(\d+)", query)
        if match:
            return match.group(1)
    elif source == JobSourceType.LEVER and segments:
        return segments[-1]
    elif source == JobSourceType.ASHBY and segments:
        return segments[-1]
    elif source == JobSourceType.INFOJOBS:
        match = re.search(r"([0-9a-f]{20,})", path)
        if match:
            return match.group(1)
    elif source == JobSourceType.INDEED:
        match = re.search(r"jk=([0-9a-f]+)", query)
        if match:
            return match.group(1)
    elif source == JobSourceType.WORKDAY and segments:
        return segments[-1]

    if segments:
        return segments[-1][:255]
    return hostname_of(url) or url[:255]
