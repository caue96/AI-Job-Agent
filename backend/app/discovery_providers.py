"""Compliant job-source registry and provider adapters.

External payloads are untrusted data. Adapters only normalize data and never build AI prompts.
"""

from __future__ import annotations

import base64
import html
import json
import re
import time
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

from defusedxml import ElementTree as ET


@dataclass(frozen=True)
class ProviderRegistration:
    key: str
    name: str
    country_coverage: tuple[str, ...]
    access_type: str
    documentation: tuple[str, ...]
    implementation_status: str
    automated_search: bool
    authentication: str
    rate_limits: str
    fallback: str
    limitations: str
    allowed_hosts: tuple[str, ...]


PROVIDERS: dict[str, ProviderRegistration] = {
    "linkedin": ProviderRegistration(
        "linkedin",
        "LinkedIn Jobs",
        ("GLOBAL",),
        "MANUAL_URL_IMPORT",
        (
            "https://www.linkedin.com/legal/l/api-terms-of-use",
            "https://learn.microsoft.com/en-us/linkedin/talent/job-postings/api/overview",
        ),
        "FALLBACK_ONLY",
        False,
        "None",
        "Not applicable",
        "Manual URL plus description or imported alert",
        "The official API posts jobs for approved partners; it is not a vacancy-search API. "
        "Automated extraction is not implemented.",
        ("linkedin.com", "www.linkedin.com"),
    ),
    "tecnoempleo": ProviderRegistration(
        "tecnoempleo",
        "Tecnoempleo",
        ("ES",),
        "PUBLIC_FEED",
        ("https://www.tecnoempleo.com/ayuda.php",),
        "IMPLEMENTED_CONFIG_REQUIRED",
        True,
        "User-configured public/custom RSS URL",
        "Feed-defined; minimum 24-hour schedule enforced",
        "Manual description or CSV",
        "Only an RSS URL supplied by Tecnoempleo is queried; pages are not scraped.",
        ("tecnoempleo.com", "www.tecnoempleo.com", "feeds.tecnoempleo.com"),
    ),
    "itjobs": ProviderRegistration(
        "itjobs",
        "ITJobs.pt",
        ("PT",),
        "OFFICIAL_API",
        ("https://www.itjobs.pt/api", "https://www.itjobs.pt/api/docs/job"),
        "IMPLEMENTED_CONFIG_REQUIRED",
        True,
        "ITJOBS_API_KEY environment secret",
        "Provider response headers/policy; minimum 24-hour schedule enforced",
        "Manual description or CSV",
        "API access requires a key requested from ITJobs.pt.",
        ("api.itjobs.pt",),
    ),
    "landing_jobs": ProviderRegistration(
        "landing_jobs",
        "Landing.jobs",
        ("EU",),
        "EMAIL_ALERT_INGESTION",
        ("https://wp.landing.jobs/blog/what-we-shipped-in-the-new-landing-jobs/",),
        "FALLBACK_ONLY",
        False,
        "User-imported alert only",
        "Not applicable",
        "Imported .eml, CSV, or description",
        "No provider-documented public vacancy-search API was identified.",
        ("landing.jobs", "www.landing.jobs"),
    ),
    "irishjobs": ProviderRegistration(
        "irishjobs",
        "IrishJobs.ie",
        ("IE",),
        "EMAIL_ALERT_INGESTION",
        ("https://www.irishjobs.ie/about/help-and-support",),
        "FALLBACK_ONLY",
        False,
        "User-imported alert only",
        "Not applicable",
        "Imported .eml, CSV, or description",
        "Jobs-by-email is documented; personalized links must remain private.",
        ("irishjobs.ie", "www.irishjobs.ie"),
    ),
    "infojobs": ProviderRegistration(
        "infojobs",
        "InfoJobs",
        ("ES",),
        "OFFICIAL_API",
        (
            "https://developer.infojobs.net/documentation/operation/offer-list-9.xhtml",
            "https://developer.infojobs.net/documentation/app-auth/index.xhtml",
        ),
        "IMPLEMENTED_CONFIG_REQUIRED",
        True,
        "INFOJOBS_CLIENT_ID and INFOJOBS_CLIENT_SECRET environment secrets",
        "Provider headers/policy; minimum 24-hour schedule enforced",
        "Manual description or CSV",
        "Only documented public offer operations are used.",
        ("api.infojobs.net",),
    ),
    "eures": ProviderRegistration(
        "eures",
        "EURES",
        ("EU",),
        "DOCUMENTED_PARTNER_API",
        ("https://eures.europa.eu/employers/advertise-job_en",),
        "PARTNER_ACCESS_REQUIRED",
        False,
        "EURES member/partner authorization",
        "Partner agreement",
        "Manual URL plus description or CSV",
        "Vacancy exchange is partner-based; no public search API is assumed.",
        ("eures.europa.eu",),
    ),
    "indeed": ProviderRegistration(
        "indeed",
        "Indeed",
        ("GLOBAL",),
        "MANUAL_DESCRIPTION_IMPORT",
        ("https://docs.indeed.com/api-guides/", "https://www.indeed.com/legal"),
        "FALLBACK_ONLY",
        False,
        "None",
        "Not applicable",
        "Manual URL plus description, CSV, or imported alert",
        "Documented APIs cover approved partner workflows, not general vacancy aggregation.",
        ("indeed.com", "www.indeed.com"),
    ),
    "wellfound": ProviderRegistration(
        "wellfound",
        "Wellfound",
        ("GLOBAL",),
        "EMAIL_ALERT_INGESTION",
        ("https://wellfound.com/terms", "https://help.wellfound.com/article/782-saved-searches"),
        "FALLBACK_ONLY",
        False,
        "User-imported alert only",
        "Not applicable",
        "Imported .eml or manual description",
        "Terms prohibit automated scraping; saved-search email alerts are user controlled.",
        ("wellfound.com",),
    ),
    "welcome_to_the_jungle": ProviderRegistration(
        "welcome_to_the_jungle",
        "Welcome to the Jungle (formerly Otta)",
        ("GLOBAL",),
        "MANUAL_DESCRIPTION_IMPORT",
        (
            "https://solutions.welcometothejungle.com/en/otta-is-now-welcome-to-the-jungle",
            "https://www.welcometothejungle.com/en/pages/terms",
        ),
        "FALLBACK_ONLY",
        False,
        "None",
        "Not applicable",
        "Manual URL plus description or CSV",
        "Current terms prohibit scraping and automated copying.",
        ("welcometothejungle.com", "www.welcometothejungle.com"),
    ),
}


def provider_registry() -> list[dict[str, Any]]:
    return [asdict(item) for item in PROVIDERS.values()]


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def sanitize_text(value: Any, maximum: int = 50_000) -> str:
    extractor = _TextExtractor()
    extractor.feed(str(value or "")[: maximum * 2])
    return re.sub(r"\s+", " ", html.unescape(" ".join(extractor.parts))).strip()[:maximum]


def safe_url(value: Any, allowed_hosts: tuple[str, ...] | None = None) -> str | None:
    if not value:
        return None
    text = str(value).strip()[:2048]
    parsed = urlsplit(text)
    host = (parsed.hostname or "").casefold()
    if parsed.scheme != "https" or not host or parsed.username or parsed.password:
        return None
    if allowed_hosts and host not in {item.casefold() for item in allowed_hosts}:
        return None
    return text


class ProviderError(RuntimeError):
    def __init__(self, code: str, message: str, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.safe_message = message[:500]
        self.retryable = retryable


class HttpClient(Protocol):
    def get_json(self, url: str, headers: dict[str, str]) -> tuple[Any, dict[str, str]]: ...
    def get_text(self, url: str, headers: dict[str, str]) -> tuple[str, dict[str, str]]: ...


class BoundedHttpClient:
    def __init__(
        self, allowed_hosts: tuple[str, ...], timeout: float = 15, max_bytes: int = 2_000_000
    ) -> None:
        self.allowed_hosts = allowed_hosts
        self.timeout = timeout
        self.max_bytes = max_bytes

    def _get(self, url: str, headers: dict[str, str]) -> tuple[bytes, dict[str, str]]:
        checked = safe_url(url, self.allowed_hosts)
        if not checked:
            raise ProviderError(
                "UNSAFE_URL", "Provider URL is outside the approved HTTPS allowlist."
            )
        try:
            # safe_url above enforces HTTPS, exact provider hosts, and no embedded credentials.
            with urlopen(  # nosec B310
                Request(checked, headers=headers), timeout=self.timeout
            ) as response:
                content_length = int(response.headers.get("Content-Length", "0") or 0)
                if content_length > self.max_bytes:
                    raise ProviderError(
                        "RESPONSE_TOO_LARGE", "Provider response exceeds the configured limit."
                    )
                body = response.read(self.max_bytes + 1)
                if len(body) > self.max_bytes:
                    raise ProviderError(
                        "RESPONSE_TOO_LARGE", "Provider response exceeds the configured limit."
                    )
                return body, dict(response.headers.items())
        except HTTPError as exc:
            raise ProviderError(
                "HTTP_ERROR",
                f"Provider returned HTTP {exc.code}.",
                exc.code in {429, 500, 502, 503, 504},
            ) from exc
        except (TimeoutError, URLError) as exc:
            raise ProviderError(
                "NETWORK_ERROR", "Provider request failed or timed out.", True
            ) from exc

    def get_json(self, url: str, headers: dict[str, str]) -> tuple[Any, dict[str, str]]:
        body, response_headers = self._get(url, headers)
        try:
            return json.loads(body), response_headers
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProviderError("INVALID_RESPONSE", "Provider returned invalid JSON.") from exc

    def get_text(self, url: str, headers: dict[str, str]) -> tuple[str, dict[str, str]]:
        body, response_headers = self._get(url, headers)
        return body.decode("utf-8", errors="replace"), response_headers


class JobProvider(ABC):
    key: str

    def __init__(self, configuration: dict[str, Any], client: HttpClient | None = None) -> None:
        self.configuration = configuration
        self.registration = PROVIDERS[self.key]
        self.client = client or BoundedHttpClient(self.registration.allowed_hosts)

    @abstractmethod
    def validate_configuration(self) -> None: ...
    @abstractmethod
    def build_queries(self, search_profile: dict[str, Any]) -> list[dict[str, Any]]: ...
    @abstractmethod
    def search(
        self, query: dict[str, Any], cursor: dict[str, Any] | None
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None, dict[str, Any]]: ...
    @abstractmethod
    def normalize(self, raw_job: dict[str, Any]) -> dict[str, Any]: ...

    def fetch_job_details(self, external_job_id: str) -> dict[str, Any] | None:
        return None

    def health_check(self) -> dict[str, Any]:
        self.validate_configuration()
        return {"status": "CONFIGURED"}

    def get_rate_limit_status(self) -> dict[str, Any]:
        return {"minimum_interval_hours": 24}

    def search_with_retry(
        self, query: dict[str, Any], cursor: dict[str, Any] | None, retries: int = 2
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None, dict[str, Any], int]:
        for attempt in range(retries + 1):
            try:
                items, next_cursor, usage = self.search(query, cursor)
                return items, next_cursor, usage, attempt
            except ProviderError as exc:
                if not exc.retryable or attempt == retries:
                    raise
                time.sleep(0.05 * (2**attempt))
        raise AssertionError("unreachable")


def _queries(profile: dict[str, Any], country: str | None = None) -> list[dict[str, Any]]:
    terms = list(profile.get("generated_terms", []))[:30]
    countries = [country] if country else list(profile.get("preferred_countries", []))[:6]
    return [{"term": term, "country": place} for term in terms for place in (countries or [None])][
        :60
    ]


class ITJobsProvider(JobProvider):
    key = "itjobs"

    def validate_configuration(self) -> None:
        if not self.configuration.get("api_key"):
            raise ProviderError("CONFIGURATION", "ITJobs API key is not configured.")

    def build_queries(self, search_profile: dict[str, Any]) -> list[dict[str, Any]]:
        return _queries(search_profile, "PT")

    def search(
        self, query: dict[str, Any], cursor: dict[str, Any] | None
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None, dict[str, Any]]:
        self.validate_configuration()
        page = int((cursor or {}).get("page", 1))
        params = urlencode(
            {
                "api_key": self.configuration["api_key"],
                "q": query["term"],
                "limit": 50,
                "page": page,
            }
        )
        payload, headers = self.client.get_json(
            f"https://api.itjobs.pt/job/search.json?{params}",
            {"Accept": "application/json", "User-Agent": "AIJobAgent/1.0"},
        )
        items = (
            payload
            if isinstance(payload, list)
            else payload.get("results", payload.get("jobs", []))
        )
        next_cursor = {"page": page + 1} if len(items) == 50 else None
        return list(items), next_cursor, {"remaining": headers.get("X-RateLimit-Remaining")}

    def normalize(self, raw_job: dict[str, Any]) -> dict[str, Any]:
        locations = raw_job.get("locations") or []
        location = locations[0] if locations and isinstance(locations[0], dict) else {}
        company = raw_job.get("company") or {}
        raw_work_model = raw_job.get("workModel")
        work_model = (
            {0: "ONSITE", 1: "REMOTE", 2: "HYBRID"}.get(raw_work_model)
            if isinstance(raw_work_model, int)
            else None
        )
        url = safe_url(
            raw_job.get("url")
            or (
                f"https://www.itjobs.pt/oferta/{raw_job.get('slug')}"
                if raw_job.get("slug")
                else None
            ),
            ("www.itjobs.pt", "itjobs.pt"),
        )
        return {
            "source": self.key,
            "external_job_id": str(raw_job.get("id") or "") or None,
            "url": url,
            "application_url": url,
            "company": sanitize_text(
                company.get("name") if isinstance(company, dict) else company, 200
            ),
            "title": sanitize_text(raw_job.get("title"), 200),
            "description": sanitize_text(raw_job.get("body")),
            "country": "PT",
            "city": sanitize_text(location.get("name"), 120) or None,
            "workplace_type": work_model,
            "salary_min": raw_job.get("salaryMin"),
            "salary_max": raw_job.get("salaryMax"),
            "salary_currency": "EUR",
            "posted_at": raw_job.get("publishedAt"),
            "provider_metadata": {"updated_at": raw_job.get("updatedAt")},
        }


class InfoJobsProvider(JobProvider):
    key = "infojobs"

    def validate_configuration(self) -> None:
        if not self.configuration.get("client_id") or not self.configuration.get("client_secret"):
            raise ProviderError("CONFIGURATION", "InfoJobs client credentials are not configured.")

    def build_queries(self, search_profile: dict[str, Any]) -> list[dict[str, Any]]:
        return _queries(search_profile, "ES")

    def search(
        self, query: dict[str, Any], cursor: dict[str, Any] | None
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None, dict[str, Any]]:
        self.validate_configuration()
        page = int((cursor or {}).get("page", 1))
        params = urlencode(
            {"q": query["term"], "country": "espana", "page": page, "maxResults": 50}
        )
        token = base64.b64encode(
            f"{self.configuration['client_id']}:{self.configuration['client_secret']}".encode()
        ).decode()
        payload, headers = self.client.get_json(
            f"https://api.infojobs.net/api/9/offer?{params}",
            {
                "Accept": "application/json",
                "Authorization": f"Basic {token}",
                "User-Agent": "AIJobAgent/1.0",
            },
        )
        items = payload.get("items", []) if isinstance(payload, dict) else []
        next_cursor = {"page": page + 1} if len(items) == 50 else None
        return list(items), next_cursor, {"remaining": headers.get("X-RateLimit-Remaining")}

    def normalize(self, raw_job: dict[str, Any]) -> dict[str, Any]:
        province = raw_job.get("province") or {}
        company = raw_job.get("author") or raw_job.get("company") or {}
        url = safe_url(raw_job.get("link"), ("www.infojobs.net", "infojobs.net"))
        return {
            "source": self.key,
            "external_job_id": str(raw_job.get("id") or "") or None,
            "url": url,
            "application_url": url,
            "company": sanitize_text(
                company.get("name") if isinstance(company, dict) else company, 200
            ),
            "title": sanitize_text(raw_job.get("title"), 200),
            "description": sanitize_text(
                raw_job.get("description") or raw_job.get("requirementMin")
            ),
            "country": "ES",
            "city": sanitize_text(raw_job.get("city"), 120) or None,
            "region": sanitize_text(
                province.get("value") if isinstance(province, dict) else province, 120
            )
            or None,
            "workplace_type": sanitize_text(raw_job.get("teleworking"), 30) or None,
            "posted_at": raw_job.get("published"),
            "provider_metadata": {"category": raw_job.get("category")},
        }


class TecnoempleoFeedProvider(JobProvider):
    key = "tecnoempleo"

    def validate_configuration(self) -> None:
        if not safe_url(self.configuration.get("feed_url"), self.registration.allowed_hosts):
            raise ProviderError("CONFIGURATION", "A valid Tecnoempleo HTTPS RSS URL is required.")

    def build_queries(self, search_profile: dict[str, Any]) -> list[dict[str, Any]]:
        return [{"feed_url": self.configuration.get("feed_url")}]

    def search(
        self, query: dict[str, Any], cursor: dict[str, Any] | None
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None, dict[str, Any]]:
        self.validate_configuration()
        body, _ = self.client.get_text(
            str(query["feed_url"]),
            {"Accept": "application/rss+xml, application/xml", "User-Agent": "AIJobAgent/1.0"},
        )
        try:
            root = ET.fromstring(body)
        except ET.ParseError as exc:
            raise ProviderError(
                "INVALID_RESPONSE", "Tecnoempleo returned invalid RSS XML."
            ) from exc
        items = []
        for node in root.findall(".//item")[:500]:
            items.append({child.tag.rsplit("}", 1)[-1]: child.text for child in node})
        return items, None, {"items": len(items)}

    def normalize(self, raw_job: dict[str, Any]) -> dict[str, Any]:
        url = safe_url(raw_job.get("link"), self.registration.allowed_hosts)
        title = sanitize_text(raw_job.get("title"), 200)
        company, separator, role = title.partition(" - ")
        return {
            "source": self.key,
            "external_job_id": sanitize_text(raw_job.get("guid"), 200) or url,
            "url": url,
            "application_url": url,
            "company": company if separator else "Not specified",
            "title": role if separator else title,
            "description": sanitize_text(raw_job.get("description")),
            "country": "ES",
            "posted_at": raw_job.get("pubDate"),
            "provider_metadata": {},
        }


def build_provider(
    key: str, configuration: dict[str, Any], client: HttpClient | None = None
) -> JobProvider:
    provider_types: dict[str, type[JobProvider]] = {
        "itjobs": ITJobsProvider,
        "infojobs": InfoJobsProvider,
        "tecnoempleo": TecnoempleoFeedProvider,
    }
    if key not in provider_types or not PROVIDERS[key].automated_search:
        raise ProviderError(
            "UNSUPPORTED_AUTOMATION", "This provider supports compliant imports only."
        )
    return provider_types[key](configuration, client)


def parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    try:
        result = datetime.fromisoformat(text)
        return result.replace(tzinfo=result.tzinfo or UTC)
    except ValueError:
        return None
