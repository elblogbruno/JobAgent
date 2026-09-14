"""Turns a browser capture into a RawJob.

Extraction follows a strict priority ladder, cheapest and most reliable first:

1. JSON-LD ``JobPosting`` — the publisher's own structured data.
2. The extension's site-specific extractor output (known ATS DOM).
3. Semantic HTML in the cleaned markup (itemprop, headings, time elements).
4. The visible job text the user was reading.
5. A model call, only when the page is unknown and the fields above are missing.

Each layer fills only the fields still empty, so a partial JSON-LD block plus a
DOM extraction combine into one complete record.
"""

import json
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from bs4 import BeautifulSoup

from packages.domain.models import RawJob
from packages.domain.role_discovery import BrowserJobCapture
from packages.job_import.canonical import extract_source_job_id, resolve_canonical
from packages.job_import.cleaning import clean_html, html_to_text, normalise_text
from packages.llm.base import LLMMessage
from packages.llm.gateway import LLMGateway

EXTRACTION_SYSTEM_PROMPT = """You extract structured job data from the text of a job posting page.

RULES:
1. Copy values from the text. Never infer a company name from the domain, never invent a salary,
   never translate the description.
2. Leave a field as null when the text does not state it.
3. requirements are the must-haves; preferred_requirements are the nice-to-haves. Split them only
   when the posting itself distinguishes them.
4. Output MUST be valid JSON matching the schema exactly.

JSON OUTPUT SCHEMA:
{
  "role": "<job title>",
  "company": "<hiring company>",
  "location": "<location or null>",
  "remote_policy": "<remote|hybrid|onsite|null>",
  "salary": "<salary text or null>",
  "employment_type": "<full-time|part-time|contract|internship|null>",
  "description": "<the job description as plain text>",
  "requirements": ["<requirement>", ...],
  "preferred_requirements": ["<nice to have>", ...],
  "technologies": ["<technology named in the posting>", ...]
}
"""

_TITLE_SUFFIX = re.compile(
    r"\s*[|\-–—·]\s*(linkedin|infojobs|indeed|glassdoor|greenhouse|lever|ashby|workable|"
    r"smartrecruiters|workday|jobs?|careers?|hiring)\b.*$",
    re.IGNORECASE,
)

_REQUIREMENT_HEADINGS = (
    "requirements",
    "qualifications",
    "what you'll need",
    "what you will need",
    "who you are",
    "requisitos",
    "must have",
)
_PREFERRED_HEADINGS = (
    "nice to have",
    "preferred",
    "bonus",
    "plus",
    "desirable",
    "se valorará",
    "valorable",
)


class BrowserJobExtractor:
    """Extracts a RawJob from a captured page, using an LLM only as a last resort."""

    def __init__(self, llm_gateway: Optional[LLMGateway] = None):
        self.gateway = llm_gateway or LLMGateway.get()

    async def extract(
        self,
        capture: BrowserJobCapture,
        allow_llm: bool = True,
    ) -> RawJob:
        cleaned = clean_html(capture.cleaned_html)
        visible_text = normalise_text(capture.visible_text) or html_to_text(cleaned)

        fields: Dict[str, Any] = {}
        strategies: List[str] = []

        for name, extracted in (
            ("json-ld", self._from_json_ld(capture.structured_data)),
            ("extension-dom", self._from_extension(capture.extracted)),
            ("semantic-html", self._from_semantic_html(cleaned)),
            ("visible-text", self._from_visible_text(capture, visible_text)),
        ):
            if _merge(fields, extracted):
                strategies.append(name)

        if allow_llm and self._needs_model(fields):
            llm_fields = await self._from_model(capture, visible_text)
            if _merge(fields, llm_fields):
                strategies.append("model")

        canonical_url, apply_url, source = resolve_canonical(
            page_url=capture.url,
            canonical_hint=capture.canonical_url_hint,
            apply_url_hint=fields.get("apply_url"),
            cleaned_html=cleaned,
            visible_text=visible_text,
        )

        description = fields.get("description") or visible_text
        role = _clean_title(fields.get("role") or capture.title or "Unknown role")
        company = fields.get("company") or _company_from_url(canonical_url)

        return RawJob(
            source=source,
            source_job_id=extract_source_job_id(capture.url, source),
            canonical_url=canonical_url,
            apply_url=apply_url or canonical_url,
            company=company,
            role=role,
            location=fields.get("location"),
            remote_policy=fields.get("remote_policy"),
            salary=fields.get("salary"),
            currency=fields.get("currency"),
            description=description or "",
            requirements=fields.get("requirements") or [],
            preferred_requirements=fields.get("preferred_requirements") or [],
            technologies=fields.get("technologies") or [],
            employment_type=fields.get("employment_type"),
            published_at=fields.get("published_at"),
            discovered_at=capture.captured_at or datetime.utcnow(),
            raw_payload={
                "page_url": capture.url,
                "page_title": capture.title,
                "hostname": capture.hostname,
                "extraction_strategies": strategies,
                "extension_strategy": capture.extraction_strategy,
                "search_query_id": capture.search_query_id,
                "search_provider": capture.search_provider,
            },
        )

    def _needs_model(self, fields: Dict[str, Any]) -> bool:
        description = fields.get("description") or ""
        return not fields.get("company") or not fields.get("role") or len(description) < 200

    # -- layer 1: JSON-LD --------------------------------------------------

    def _from_json_ld(self, structured_data: Any) -> Dict[str, Any]:
        posting = _find_job_posting(structured_data)
        if not posting:
            return {}

        fields: Dict[str, Any] = {}
        fields["role"] = _first_string(posting.get("title"))
        fields["description"] = html_to_text(str(posting.get("description") or ""))

        org = posting.get("hiringOrganization")
        if isinstance(org, dict):
            fields["company"] = _first_string(org.get("name"))
        elif isinstance(org, str):
            fields["company"] = org

        fields["location"] = _json_ld_location(posting)
        if str(posting.get("jobLocationType", "")).upper() == "TELECOMMUTE":
            fields["remote_policy"] = "remote"

        employment = posting.get("employmentType")
        if isinstance(employment, list):
            employment = ", ".join(str(e) for e in employment)
        fields["employment_type"] = _first_string(employment)

        salary, currency = _json_ld_salary(posting.get("baseSalary"))
        fields["salary"] = salary
        fields["currency"] = currency

        posted = posting.get("datePosted")
        if posted:
            fields["published_at"] = _parse_date(str(posted))

        apply_url = posting.get("url") or posting.get("sameAs")
        fields["apply_url"] = _first_string(apply_url)

        skills = posting.get("skills") or posting.get("occupationalCategory")
        if isinstance(skills, str):
            fields["technologies"] = [s.strip() for s in re.split(r"[,;]", skills) if s.strip()][
                :20
            ]
        elif isinstance(skills, list):
            fields["technologies"] = [str(s).strip() for s in skills][:20]

        requirements = posting.get("qualifications") or posting.get("experienceRequirements")
        if isinstance(requirements, str) and requirements.strip():
            fields["requirements"] = _split_bullets(html_to_text(requirements))

        return {key: value for key, value in fields.items() if value}

    # -- layer 2: the extension's site-specific extractor ------------------

    def _from_extension(self, extracted: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(extracted, dict) or not extracted:
            return {}
        mapping = {
            "role": ("role", "title", "jobTitle"),
            "company": ("company", "companyName", "employer"),
            "location": ("location", "jobLocation"),
            "salary": ("salary", "compensation", "pay"),
            "employment_type": ("employmentType", "employment_type", "contractType"),
            "remote_policy": ("remotePolicy", "workplaceType", "remote_policy"),
            "description": ("description", "descriptionText", "jobDescription"),
            "apply_url": ("applyUrl", "apply_url", "applicationUrl"),
        }
        fields: Dict[str, Any] = {}
        for target, keys in mapping.items():
            for key in keys:
                value = extracted.get(key)
                if isinstance(value, str) and value.strip():
                    fields[target] = normalise_text(value)
                    break

        for target, key in (
            ("requirements", "requirements"),
            ("preferred_requirements", "preferredRequirements"),
            ("technologies", "technologies"),
        ):
            value = extracted.get(key)
            if isinstance(value, list) and value:
                fields[target] = [str(item).strip() for item in value if str(item).strip()][:30]

        posted = extracted.get("datePosted") or extracted.get("publishedAt")
        if isinstance(posted, str) and posted.strip():
            parsed = _parse_date(posted)
            if parsed:
                fields["published_at"] = parsed
        return fields

    # -- layer 3: semantic HTML -------------------------------------------

    def _from_semantic_html(self, cleaned_html: str) -> Dict[str, Any]:
        if not cleaned_html:
            return {}
        soup = BeautifulSoup(cleaned_html, "html.parser")
        fields: Dict[str, Any] = {}

        for prop, target in (
            ("title", "role"),
            ("hiringOrganization", "company"),
            ("jobLocation", "location"),
            ("baseSalary", "salary"),
            ("employmentType", "employment_type"),
        ):
            node = soup.find(attrs={"itemprop": prop})
            if node is not None:
                text = normalise_text(node.get("content") or node.get_text(" "))
                if text:
                    fields[target] = text

        if "role" not in fields:
            heading = soup.find("h1")
            if heading is not None:
                text = normalise_text(heading.get_text(" "))
                if text:
                    fields["role"] = text

        description_node = soup.find(attrs={"itemprop": "description"}) or soup.find("article")
        if description_node is not None:
            description = html_to_text(str(description_node))
            if len(description) > 200:
                fields["description"] = description

        time_node = soup.find("time")
        if time_node is not None:
            parsed = _parse_date(str(time_node.get("datetime") or time_node.get_text(" ")))
            if parsed:
                fields["published_at"] = parsed

        return fields

    # -- layer 4: visible text --------------------------------------------

    def _from_visible_text(self, capture: BrowserJobCapture, visible_text: str) -> Dict[str, Any]:
        if not visible_text:
            return {}
        fields: Dict[str, Any] = {"description": visible_text}

        title = _clean_title(capture.title)
        if title:
            fields["role"] = title

        requirements, preferred = _split_requirement_sections(visible_text)
        if requirements:
            fields["requirements"] = requirements
        if preferred:
            fields["preferred_requirements"] = preferred

        salary = _find_salary(visible_text)
        if salary:
            fields["salary"] = salary

        return fields

    # -- layer 5: the model ------------------------------------------------

    async def _from_model(self, capture: BrowserJobCapture, visible_text: str) -> Dict[str, Any]:
        if not visible_text:
            return {}
        prompt = f"""PAGE URL: {capture.url}
PAGE TITLE: {capture.title}

PAGE TEXT:
{visible_text[:9000]}
"""
        try:
            response = await self.gateway.generate(
                [
                    LLMMessage(role="system", content=EXTRACTION_SYSTEM_PROMPT),
                    LLMMessage(role="user", content=prompt),
                ],
                temperature=0.0,
                response_format="json",
            )
            parsed = json.loads(response.content)
        except Exception:
            return {}
        if not isinstance(parsed, dict):
            return {}

        fields: Dict[str, Any] = {}
        for key in (
            "role",
            "company",
            "location",
            "salary",
            "employment_type",
            "remote_policy",
            "description",
        ):
            value = parsed.get(key)
            if isinstance(value, str) and value.strip() and value.strip().lower() != "null":
                fields[key] = normalise_text(value)
        for key in ("requirements", "preferred_requirements", "technologies"):
            value = parsed.get(key)
            if isinstance(value, list) and value:
                fields[key] = [str(item).strip() for item in value if str(item).strip()][:30]
        return fields


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _merge(target: Dict[str, Any], incoming: Dict[str, Any]) -> bool:
    """Fills only the keys that are still empty. Returns True if anything landed."""
    changed = False
    for key, value in (incoming or {}).items():
        if value in (None, "", []):
            continue
        current = target.get(key)
        if current in (None, "", []):
            target[key] = value
            changed = True
        elif key == "description" and isinstance(value, str) and len(value) > len(str(current)) * 2:
            # A much fuller description from a later layer is worth taking.
            target[key] = value
            changed = True
    return changed


def _find_job_posting(data: Any, depth: int = 0) -> Optional[Dict[str, Any]]:
    """Finds a JobPosting node anywhere in the structured data, including @graph."""
    if depth > 6 or data is None:
        return None
    if isinstance(data, str):
        try:
            return _find_job_posting(json.loads(data), depth + 1)
        except (ValueError, TypeError):
            return None
    if isinstance(data, list):
        for item in data:
            found = _find_job_posting(item, depth + 1)
            if found:
                return found
        return None
    if isinstance(data, dict):
        node_type = data.get("@type") or data.get("type")
        types = node_type if isinstance(node_type, list) else [node_type]
        if any(str(t).lower() == "jobposting" for t in types if t):
            return data
        for key in ("@graph", "mainEntity", "itemListElement"):
            found = _find_job_posting(data.get(key), depth + 1)
            if found:
                return found
    return None


def _first_string(value: Any) -> Optional[str]:
    if isinstance(value, str) and value.strip():
        return normalise_text(value)
    if isinstance(value, list):
        for item in value:
            result = _first_string(item)
            if result:
                return result
    return None


def _json_ld_location(posting: Dict[str, Any]) -> Optional[str]:
    location = posting.get("jobLocation")
    if isinstance(location, list):
        location = location[0] if location else None
    if isinstance(location, str):
        return normalise_text(location)
    if isinstance(location, dict):
        address = location.get("address")
        if isinstance(address, dict):
            parts = [
                address.get("addressLocality"),
                address.get("addressRegion"),
                address.get("addressCountry"),
            ]
            flattened = []
            for part in parts:
                if isinstance(part, dict):
                    part = part.get("name")
                if isinstance(part, str) and part.strip():
                    flattened.append(part.strip())
            if flattened:
                return ", ".join(flattened)
        name = location.get("name")
        if isinstance(name, str):
            return normalise_text(name)
    applicant = posting.get("applicantLocationRequirements")
    if isinstance(applicant, dict):
        return _first_string(applicant.get("name"))
    return None


def _json_ld_salary(base_salary: Any) -> tuple:
    if not isinstance(base_salary, dict):
        return None, None
    currency = base_salary.get("currency") or base_salary.get("salaryCurrency")
    value = base_salary.get("value")
    if isinstance(value, dict):
        minimum = value.get("minValue")
        maximum = value.get("maxValue")
        single = value.get("value")
        unit = value.get("unitText") or ""
        if minimum or maximum:
            return f"{minimum or ''} - {maximum or ''} {currency or ''} {unit}".strip(), currency
        if single:
            return f"{single} {currency or ''} {unit}".strip(), currency
    elif isinstance(value, (int, float, str)):
        return f"{value} {currency or ''}".strip(), currency
    return None, currency


def _parse_date(value: str) -> Optional[datetime]:
    text = value.strip()
    if not text:
        return None
    for pattern in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"):
        try:
            parsed = datetime.strptime(
                text[:26] if "%z" in pattern else text[: len("2024-01-01T00:00:00")], pattern
            )
            return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=None)
    except ValueError:
        return None


def _clean_title(title: Optional[str]) -> str:
    if not title:
        return ""
    cleaned = _TITLE_SUFFIX.sub("", normalise_text(title)).strip(" -|·—–")
    # "Senior XR Engineer hiring at Company X" style titles from aggregators.
    cleaned = re.sub(r"\s+hiring\s+.*$", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip()


def _company_from_url(url: str) -> str:
    from packages.job_import.canonical import hostname_of

    host = hostname_of(url)
    if not host:
        return "Unknown company"
    parts = [
        part
        for part in host.split(".")
        if part not in ("www", "jobs", "careers", "apply", "boards", "job-boards")
    ]
    if not parts:
        return "Unknown company"
    if parts[0] in ("greenhouse", "lever", "ashbyhq", "workable", "smartrecruiters"):
        segments = [segment for segment in url.split("/") if segment and "." not in segment]
        if segments:
            return segments[0].replace("-", " ").title()
    return parts[0].replace("-", " ").title()


def _split_bullets(text: str) -> List[str]:
    bullets = []
    for line in text.split("\n"):
        cleaned = line.strip(" •-*•\t")
        if 8 <= len(cleaned) <= 300:
            bullets.append(cleaned)
    return bullets[:20]


def _split_requirement_sections(text: str) -> tuple:
    """Pulls requirement bullets out of the visible text by their headings."""
    lines = text.split("\n")
    requirements: List[str] = []
    preferred: List[str] = []
    bucket: Optional[List[str]] = None

    for line in lines:
        stripped = line.strip()
        lowered = stripped.lower().rstrip(":")
        if not stripped:
            continue
        if len(stripped) < 60 and any(heading in lowered for heading in _PREFERRED_HEADINGS):
            bucket = preferred
            continue
        if len(stripped) < 60 and any(heading in lowered for heading in _REQUIREMENT_HEADINGS):
            bucket = requirements
            continue
        if len(stripped) < 60 and stripped.endswith(":") and bucket is not None:
            bucket = None
            continue
        if bucket is not None and 8 <= len(stripped) <= 300:
            bucket.append(stripped.strip(" •-*•"))

    return requirements[:20], preferred[:20]


def _find_salary(text: str) -> Optional[str]:
    match = re.search(
        r"([€$£]\s?\d[\d.,]*\s?(?:k|K)?\s?(?:-|–|to)\s?[€$£]?\s?\d[\d.,]*\s?(?:k|K)?"
        r"|\d[\d.,]*\s?(?:-|–|to)\s?\d[\d.,]*\s?(?:€|EUR|USD|GBP)"
        r"|\d[\d.,]*\s?(?:€|EUR|USD|GBP)\s?(?:per year|/year|anual|bruto))",
        text,
    )
    return match.group(0).strip() if match else None
