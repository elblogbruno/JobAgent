import json

import pytest

from packages.domain.enums import JobSourceType
from packages.domain.role_discovery import BrowserJobCapture
from packages.job_import.canonical import (
    extract_source_job_id,
    find_ats_urls,
    is_ats_url,
    resolve_canonical,
    source_for_url,
)
from packages.job_import.cleaning import clean_html, html_to_text, strip_tracking_params
from packages.job_import.extractor import BrowserJobExtractor
from packages.llm.base import LLMProvider, LLMResponse
from packages.llm.gateway import LLMGateway
from packages.normalizer.normalizer import JobNormalizer

JOB_POSTING_LD = {
    "@context": "https://schema.org",
    "@type": "JobPosting",
    "title": "Senior XR Software Engineer",
    "description": (
        "<p>Build <b>spatial computing</b> interfaces in Unity.</p>"
        "<ul><li>5 years Unity</li></ul>"
    ),
    "datePosted": "2026-08-01",
    "employmentType": "FULL_TIME",
    "jobLocationType": "TELECOMMUTE",
    "hiringOrganization": {"@type": "Organization", "name": "Company X"},
    "jobLocation": {
        "@type": "Place",
        "address": {
            "@type": "PostalAddress",
            "addressLocality": "Barcelona",
            "addressCountry": "ES",
        },
    },
    "baseSalary": {
        "@type": "MonetaryAmount",
        "currency": "EUR",
        "value": {
            "@type": "QuantitativeValue",
            "minValue": 60000,
            "maxValue": 80000,
            "unitText": "YEAR",
        },
    },
    "skills": "Unity, C#, OpenXR",
}


class StubLLMProvider(LLMProvider):
    def __init__(self, payload: str):
        self.payload = payload
        self.calls = 0

    async def generate(self, messages, temperature=0.2, max_tokens=4096, response_format=None):
        self.calls += 1
        return LLMResponse(content=self.payload, model="stub-provider")


def _capture(**kwargs) -> BrowserJobCapture:
    defaults = dict(
        url="https://www.linkedin.com/jobs/view/3912345678/?refId=abc&trackingId=xyz",
        title="Senior XR Software Engineer | Company X | LinkedIn",
        hostname="www.linkedin.com",
        visibleText="Senior XR Software Engineer\nCompany X\nBarcelona",
        cleanedHtml="",
        structuredData=[],
        extracted={},
    )
    defaults.update(kwargs)
    return BrowserJobCapture.model_validate(defaults)


# ---------------------------------------------------------------------------
# Cleaning
# ---------------------------------------------------------------------------


def test_clean_html_removes_scripts_navigation_and_recommendations():
    html = """
    <div>
      <script>window.track()</script>
      <style>.a{color:red}</style>
      <nav>Home Jobs Profile</nav>
      <div class="similar-jobs">Jobs you may be interested in</div>
      <div aria-hidden="true">hidden legal boilerplate</div>
      <section class="job-details" data-tracking-id="99" style="color:red">
        <h1>Senior XR Software Engineer</h1>
        <p>Build spatial computing interfaces.</p>
      </section>
      <footer>Cookie policy</footer>
    </div>
    """
    cleaned = clean_html(html)

    assert "window.track" not in cleaned
    assert "color:red" not in cleaned
    assert "Home Jobs Profile" not in cleaned
    assert "Jobs you may be interested in" not in cleaned
    assert "hidden legal boilerplate" not in cleaned
    assert "Cookie policy" not in cleaned
    assert "data-tracking-id" not in cleaned
    assert "Senior XR Software Engineer" in cleaned


def test_html_to_text_keeps_structure():
    text = html_to_text("<p>First line</p><ul><li>Bullet one</li><li>Bullet two</li></ul>")
    assert "First line" in text
    assert "Bullet one" in text
    assert "Bullet two" in text
    assert "<" not in text


def test_strip_tracking_params_keeps_the_meaningful_query():
    url = strip_tracking_params(
        "https://jobs.ashbyhq.com/company/123?utm_source=linkedin&refId=abc&gh_src=x&lang=en"
    )
    assert "utm_source" not in url
    assert "refId" not in url
    assert "gh_src" not in url
    assert "lang=en" in url


# ---------------------------------------------------------------------------
# Canonical resolution
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://jobs.ashbyhq.com/company/123", JobSourceType.ASHBY),
        ("https://boards.greenhouse.io/company/jobs/456", JobSourceType.GREENHOUSE),
        ("https://job-boards.greenhouse.io/company/jobs/456", JobSourceType.GREENHOUSE),
        ("https://jobs.lever.co/company/uuid", JobSourceType.LEVER),
        ("https://apply.workable.com/company/j/ABC", JobSourceType.WORKABLE),
        ("https://jobs.smartrecruiters.com/Company/123", JobSourceType.SMARTRECRUITERS),
        ("https://company.wd3.myworkdayjobs.com/en-US/careers/job/x", JobSourceType.WORKDAY),
        ("https://www.linkedin.com/jobs/view/123", JobSourceType.LINKEDIN),
        ("https://www.infojobs.net/barcelona/xr-engineer/of-i123", JobSourceType.INFOJOBS),
        ("https://es.indeed.com/viewjob?jk=abc123", JobSourceType.INDEED),
        ("https://careers.acme.com/jobs/xr-engineer", JobSourceType.COMPANY_CAREERS),
    ],
)
def test_source_detection_by_hostname(url, expected):
    assert source_for_url(url) == expected


def test_ats_urls_are_recognised_inside_page_markup():
    html = '<a href="https://jobs.ashbyhq.com/company/abc?utm_source=li">Apply</a>'
    assert find_ats_urls(html) == ["https://jobs.ashbyhq.com/company/abc?utm_source=li"]
    assert is_ats_url("https://www.linkedin.com/jobs/view/1") is False


def test_canonical_resolution_prefers_the_company_ats_over_the_aggregator():
    canonical, apply_url, source = resolve_canonical(
        page_url="https://www.linkedin.com/jobs/view/3912345678/?refId=abc",
        canonical_hint="https://www.linkedin.com/jobs/view/3912345678/",
        apply_url_hint="https://jobs.ashbyhq.com/company/xr-engineer?utm_source=linkedin",
        cleaned_html="",
        visible_text="",
    )
    assert canonical == "https://jobs.ashbyhq.com/company/xr-engineer"
    assert apply_url == canonical
    assert source == JobSourceType.ASHBY


def test_canonical_resolution_keeps_the_page_url_when_no_ats_is_found():
    canonical, apply_url, source = resolve_canonical(
        page_url="https://www.linkedin.com/jobs/view/3912345678/?refId=abc",
    )
    assert canonical == "https://www.linkedin.com/jobs/view/3912345678/"
    assert apply_url == canonical
    assert source == JobSourceType.LINKEDIN


def test_ats_page_is_its_own_canonical_url():
    canonical, _, source = resolve_canonical(
        page_url="https://boards.greenhouse.io/company/jobs/456",
        cleaned_html='<a href="https://jobs.lever.co/other/x">unrelated</a>',
    )
    assert canonical == "https://boards.greenhouse.io/company/jobs/456"
    assert source == JobSourceType.GREENHOUSE


@pytest.mark.parametrize(
    "url,source,expected",
    [
        ("https://www.linkedin.com/jobs/view/3912345678/", JobSourceType.LINKEDIN, "3912345678"),
        ("https://boards.greenhouse.io/acme/jobs/4567890", JobSourceType.GREENHOUSE, "4567890"),
        ("https://es.indeed.com/viewjob?jk=abc123def", JobSourceType.INDEED, "abc123def"),
        ("https://jobs.lever.co/acme/8ac2f1e0-uuid", JobSourceType.LEVER, "8ac2f1e0-uuid"),
    ],
)
def test_source_job_ids_are_extracted_for_deduplication(url, source, expected):
    assert extract_source_job_id(url, source) == expected


# ---------------------------------------------------------------------------
# Extraction ladder
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_json_ld_is_the_first_choice():
    extractor = BrowserJobExtractor(LLMGateway(provider=StubLLMProvider("{}")))
    raw = await extractor.extract(
        _capture(structuredData=[{"@type": "WebPage"}, JOB_POSTING_LD]), allow_llm=False
    )

    assert raw.role == "Senior XR Software Engineer"
    assert raw.company == "Company X"
    assert raw.location == "Barcelona, ES"
    assert raw.remote_policy == "remote"
    assert raw.employment_type == "FULL_TIME"
    assert raw.salary is not None and "60000" in raw.salary
    assert raw.currency == "EUR"
    assert "spatial computing" in raw.description
    assert "<b>" not in raw.description
    assert raw.published_at is not None and raw.published_at.year == 2026
    assert raw.technologies == ["Unity", "C#", "OpenXR"]
    assert "json-ld" in raw.raw_payload["extraction_strategies"]


@pytest.mark.asyncio
async def test_json_ld_inside_a_graph_is_found():
    extractor = BrowserJobExtractor(LLMGateway(provider=StubLLMProvider("{}")))
    raw = await extractor.extract(
        _capture(structuredData={"@context": "x", "@graph": [{"@type": "Person"}, JOB_POSTING_LD]}),
        allow_llm=False,
    )
    assert raw.role == "Senior XR Software Engineer"


@pytest.mark.asyncio
async def test_extension_dom_extraction_is_used_when_there_is_no_json_ld():
    extractor = BrowserJobExtractor(LLMGateway(provider=StubLLMProvider("{}")))
    raw = await extractor.extract(
        _capture(
            extracted={
                "role": "Spatial Computing Engineer",
                "company": "Studio Y",
                "location": "Remote, Europe",
                "description": "Long description of the role. " * 20,
                "requirements": ["Unity", "OpenXR"],
                "applyUrl": "https://jobs.lever.co/studio-y/uuid",
            }
        ),
        allow_llm=False,
    )

    assert raw.role == "Spatial Computing Engineer"
    assert raw.company == "Studio Y"
    assert raw.requirements == ["Unity", "OpenXR"]
    assert raw.canonical_url == "https://jobs.lever.co/studio-y/uuid"
    assert "extension-dom" in raw.raw_payload["extraction_strategies"]


@pytest.mark.asyncio
async def test_semantic_html_fills_gaps_the_extractor_missed():
    html = """
    <article>
      <h1>Mixed Reality Engineer</h1>
      <span itemprop="hiringOrganization">Acme Labs</span>
      <span itemprop="jobLocation">Munich, Germany</span>
      <time datetime="2026-07-15">15 July 2026</time>
      <div itemprop="description">
        <p>Work on passthrough perception and hand tracking.</p>
        <p>This description is intentionally long so the extractor keeps it.</p>
        <p>It repeats to pass the length threshold used to prefer real content.</p>
        <p>Perception, calibration and rendering across a mixed reality headset.</p>
      </div>
    </article>
    """
    extractor = BrowserJobExtractor(LLMGateway(provider=StubLLMProvider("{}")))
    raw = await extractor.extract(
        _capture(
            hostname="careers.acme.com", url="https://careers.acme.com/jobs/mr", cleanedHtml=html
        ),
        allow_llm=False,
    )

    assert raw.role == "Mixed Reality Engineer"
    assert raw.company == "Acme Labs"
    assert raw.location == "Munich, Germany"
    assert raw.published_at is not None and raw.published_at.month == 7
    assert "semantic-html" in raw.raw_payload["extraction_strategies"]


@pytest.mark.asyncio
async def test_the_model_is_the_last_resort_for_an_unknown_page():
    payload = json.dumps(
        {
            "role": "Creative Technologist",
            "company": "Studio Z",
            "location": "Barcelona",
            "description": "Interactive installations with Unity and computer vision. " * 6,
            "requirements": ["Unity", "TouchDesigner"],
            "technologies": ["Unity"],
            "salary": None,
        }
    )
    stub = StubLLMProvider(payload)
    extractor = BrowserJobExtractor(LLMGateway(provider=stub))
    raw = await extractor.extract(
        _capture(
            hostname="studio-z.example",
            url="https://studio-z.example/careers/creative-technologist",
            title="",
            visibleText="Some sparse page text about a job at a studio.",
        ),
        allow_llm=True,
    )

    assert stub.calls == 1
    assert raw.role == "Creative Technologist"
    assert raw.company == "Studio Z"
    assert "model" in raw.raw_payload["extraction_strategies"]


@pytest.mark.asyncio
async def test_the_model_is_not_called_when_the_page_is_already_complete():
    stub = StubLLMProvider("{}")
    extractor = BrowserJobExtractor(LLMGateway(provider=stub))
    await extractor.extract(
        _capture(
            structuredData=[JOB_POSTING_LD],
            visibleText="Senior XR Software Engineer at Company X. " * 20,
        ),
        allow_llm=True,
    )
    assert stub.calls == 0


@pytest.mark.asyncio
async def test_aggregator_titles_are_cleaned():
    extractor = BrowserJobExtractor(LLMGateway(provider=StubLLMProvider("{}")))
    raw = await extractor.extract(
        _capture(
            title="Company X hiring Senior XR Engineer in Barcelona | LinkedIn",
            visibleText="A short page.",
        ),
        allow_llm=False,
    )
    assert "LinkedIn" not in raw.role
    assert "hiring" not in raw.role


@pytest.mark.asyncio
async def test_capture_records_the_search_that_produced_the_job():
    extractor = BrowserJobExtractor(LLMGateway(provider=StubLLMProvider("{}")))
    raw = await extractor.extract(
        _capture(
            structuredData=[JOB_POSTING_LD], searchQueryId="search_123", searchProvider="linkedin"
        ),
        allow_llm=False,
    )
    assert raw.raw_payload["search_query_id"] == "search_123"
    assert raw.raw_payload["search_provider"] == "linkedin"


# ---------------------------------------------------------------------------
# Fingerprinting
# ---------------------------------------------------------------------------


def test_description_fingerprint_ignores_formatting():
    text_a = "We are looking for an XR engineer to build spatial interfaces in Unity. " * 3
    text_b = text_a.replace(" ", "\n").upper()
    assert JobNormalizer.description_fingerprint(text_a) == JobNormalizer.description_fingerprint(
        text_b
    )


def test_description_fingerprint_differs_for_different_postings():
    long_a = "XR engineer building spatial computing interfaces in Unity with OpenXR. " * 3
    long_b = "Backend engineer building payment services in Go with Postgres and Kafka. " * 3
    assert JobNormalizer.description_fingerprint(long_a) != JobNormalizer.description_fingerprint(
        long_b
    )


def test_short_descriptions_have_no_fingerprint():
    assert JobNormalizer.description_fingerprint("Too short to fingerprint") is None
    assert JobNormalizer.description_fingerprint("") is None
