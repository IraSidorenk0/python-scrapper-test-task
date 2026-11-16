import json
import logging
import re
import time
from collections.abc import Mapping
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup
from django.conf import settings

from scraper.models import JobPosting
from scraper.providers import ProviderError

logger = logging.getLogger(__name__)

SEARCH_URL = "https://www.linkedin.com/jobs/search/"
REQUEST_TIMEOUT = 15
PAGE_SIZE = 25
USER_AGENT = "Jobpost/1.0"


def _element_text(element) -> str:
    return element.get_text(" ", strip=True) if element else ""


def _job_id(card, job_url: str) -> str:
    values = (card.get("data-entity-urn", ""), job_url)
    for value in values:
        match = re.search(r"(?:jobPosting:|/jobs/view/)(\d+)", value)
        if match:
            return match.group(1)
    return ""


def _search_cards(soup: BeautifulSoup):
    cards = soup.select(".jobs-search__results-list .base-card")
    if cards:
        return cards
    return soup.select("li.jobs-search-results__list-item")


def parse_linkedin_search_html(html: str | bytes) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    jobs = []
    for card in _search_cards(soup):
        title = _element_text(card.select_one(".base-search-card__title"))
        link_element = card.select_one("a.base-card__full-link")
        raw_url = link_element.get("href", "") if link_element else ""
        job_url = urljoin("https://www.linkedin.com", raw_url)
        external_id = _job_id(card, job_url)
        if not title or not external_id or not raw_url:
            logger.warning("Skipping a LinkedIn job card missing title, link, or ID.")
            continue

        company_element = card.select_one(".base-search-card__subtitle")
        company_name = _element_text(company_element)
        company_link = company_element.find("a", href=True) if company_element else None
        company = None
        if company_name:
            company = {"name": company_name}
            if company_link:
                company["profile_url"] = urljoin(
                    "https://www.linkedin.com",
                    company_link["href"],
                )

        job = {
            "external_id": external_id,
            "title": title,
            "job_url": job_url,
            "location": _element_text(
                card.select_one(".job-search-card__location")
            ),
        }
        time_element = card.select_one("time[datetime]")
        if time_element:
            job["posted_at"] = time_element.get("datetime")
        if company:
            job["company"] = company
        jobs.append(job)
    return jobs


def get_linkedin_vacancies(
    vacancy: str,
    location: str,
    *,
    start: int = 0,
    session: httpx.Client | None = None,
) -> list[dict[str, Any]]:
    if start < 0:
        raise ValueError("start must be zero or greater.")

    requester = session.get if session is not None else httpx.get
    try:
        response = requester(
            SEARCH_URL,
            params={
                "keywords": vacancy,
                "location": location,
                "start": start,
            },
            headers={"User-Agent": USER_AGENT},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise ProviderError(f"LinkedIn job search request failed: {exc}") from exc

    return parse_linkedin_search_html(response.content)


class LinkedInJobsProvider:
    source = "linkedin-public"

    def __init__(self):
        self._has_fetched_details = False

    def search(self, query: str, country: str):
        max_pages = getattr(settings, "LINKEDIN_MAX_PAGES", 20)
        page_delay = getattr(settings, "LINKEDIN_PAGE_DELAY_SECONDS", 1.0)
        if max_pages < 1:
            raise ValueError("LINKEDIN_MAX_PAGES must be at least one.")

        seen_ids = set()
        for page_number in range(max_pages):
            page_start = page_number * PAGE_SIZE
            jobs = get_linkedin_vacancies(query, country, start=page_start)
            if not jobs:
                break

            new_jobs = 0
            for job in jobs:
                if job["external_id"] in seen_ids:
                    continue
                seen_ids.add(job["external_id"])
                new_jobs += 1
                yield job

            if new_jobs == 0 or len(jobs) < PAGE_SIZE:
                break
            if page_number + 1 < max_pages and page_delay > 0:
                time.sleep(page_delay)

    def get_details(self, posting: JobPosting) -> Mapping[str, Any]:
        parsed_url = urlsplit(posting.job_url)
        hostname = (parsed_url.hostname or "").lower()
        if (
            parsed_url.scheme not in {"http", "https"}
            or hostname != "linkedin.com"
            and not hostname.endswith(".linkedin.com")
        ):
            raise ProviderError("Refusing to fetch a non-LinkedIn job URL.")

        page_delay = getattr(settings, "LINKEDIN_PAGE_DELAY_SECONDS", 1.0)
        if self._has_fetched_details and page_delay > 0:
            time.sleep(page_delay)
        self._has_fetched_details = True

        try:
            response = httpx.get(
                posting.job_url,
                headers={"User-Agent": USER_AGENT},
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ProviderError(f"LinkedIn job details request failed: {exc}") from exc

        soup = BeautifulSoup(response.content, "html.parser")
        job_data = _find_job_posting(soup)
        if job_data is None:
            description_element = soup.select_one(".show-more-less-html__markup")
            description = _element_text(description_element)
            if not description:
                raise ProviderError("No public job details were found on the page.")
            return {"description": description}

        details: dict[str, Any] = {}
        for source_key, destination_key in (
            ("title", "title"),
            ("datePosted", "posted_at"),
            ("employmentType", "employment_type"),
            ("jobLocationType", "workplace_type"),
        ):
            if job_data.get(source_key):
                value = job_data[source_key]
                details[destination_key] = (
                    ", ".join(str(item) for item in value)
                    if isinstance(value, list)
                    else value
                )

        description = job_data.get("description")
        if description:
            details["description"] = _element_text(
                BeautifulSoup(description, "html.parser")
            )

        job_location = _job_location(job_data.get("jobLocation"))
        if job_location:
            details["location"] = job_location

        company = _company_details(job_data.get("hiringOrganization"))
        if company:
            details["company"] = company

        salary = _salary_details(job_data.get("baseSalary"))
        details.update(salary)
        return details


def _find_job_posting(soup: BeautifulSoup) -> Mapping[str, Any] | None:
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.string or script.get_text())
        except (json.JSONDecodeError, TypeError):
            continue
        for candidate in _jsonld_objects(data):
            schema_type = candidate.get("@type", ())
            if isinstance(schema_type, str):
                schema_types = (schema_type,)
            elif isinstance(schema_type, (list, tuple)):
                schema_types = schema_type
            else:
                schema_types = ()
            if any(str(value).endswith("JobPosting") for value in schema_types):
                return candidate
    return None


def _jsonld_objects(value):
    if isinstance(value, list):
        for item in value:
            yield from _jsonld_objects(item)
    elif isinstance(value, dict):
        yield value
        for nested in value.values():
            if isinstance(nested, (dict, list)):
                yield from _jsonld_objects(nested)


def _job_location(value: Any) -> str:
    locations = value if isinstance(value, list) else [value]
    formatted = []
    for location in locations:
        if not isinstance(location, Mapping):
            continue
        address = location.get("address", {})
        if not isinstance(address, Mapping):
            continue
        country = address.get("addressCountry", "")
        if isinstance(country, Mapping):
            country = country.get("name", "")
        parts = (
            address.get("addressLocality"),
            address.get("addressRegion"),
            country,
        )
        text = ", ".join(str(part) for part in parts if part)
        if text and text not in formatted:
            formatted.append(text)
    return "; ".join(formatted)


def _company_details(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    name = value.get("name")
    if not name:
        return None
    company = {"name": name}
    profile_url = value.get("sameAs") or value.get("url")
    if isinstance(profile_url, list):
        profile_url = next((item for item in profile_url if isinstance(item, str)), "")
    if profile_url:
        company["profile_url"] = profile_url
        company["external_id"] = profile_url
    return company


def _salary_details(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    salary_value = value.get("value", {})
    details = {}
    if isinstance(salary_value, Mapping):
        minimum = salary_value.get("minValue")
        maximum = salary_value.get("maxValue")
        exact_value = salary_value.get("value")
        if minimum is None and maximum is None and exact_value is not None:
            minimum = maximum = exact_value
    elif isinstance(salary_value, (int, float, str)) and not isinstance(
        salary_value, bool
    ):
        minimum = maximum = salary_value
    else:
        minimum = maximum = None
    if minimum is not None:
        details["salary_min"] = minimum
    if maximum is not None:
        details["salary_max"] = maximum
    if value.get("currency"):
        details["salary_currency"] = value["currency"]
    return details


def getLinkedInVacancies(vacancy, location):
    return list(LinkedInJobsProvider().search(vacancy, location))
