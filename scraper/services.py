import hashlib
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from scraper.models import Company, JobPosting, SearchQuery
from scraper.providers import JobDataProvider, ProviderError, get_data_provider

logger = logging.getLogger(__name__)

JOB_TEXT_FIELDS = {
    "title": "title",
    "location": "location",
    "description": "description",
    "job_url": "job_url",
    "employment_type": "employment_type",
    "workplace_type": "workplace_type",
    "salary_currency": "salary_currency",
}
COMPANY_TEXT_FIELDS = {
    "name": "name",
    "website": "website",
    "description": "description",
    "industry": "industry",
    "employee_count": "employee_count",
    "headquarters": "headquarters",
    "profile_url": "profile_url",
}


@dataclass(frozen=True)
class SearchReport:
    created: int
    updated: int
    skipped: int


@dataclass(frozen=True)
class DetailsReport:
    completed: int
    failed: int


class SearchServiceError(Exception):
    pass


def _text(value: Any) -> str:
    return "" if value is None else str(value)


def _posted_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    parsed_date = parse_date(str(value))
    if parsed_date is not None:
        return parsed_date
    parsed_datetime = parse_datetime(str(value))
    if parsed_datetime is not None:
        return parsed_datetime.date()
    raise ValueError(f"Invalid posted_at value: {value!r}")


def _decimal(value: Any, field_name: str) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError(f"Invalid {field_name} value: {value!r}") from exc
    if not result.is_finite():
        raise ValueError(f"Invalid {field_name} value: {value!r}")
    return result


def _company_external_id(data: Mapping[str, Any]) -> str:
    external_id = _text(data.get("external_id") or data.get("id")).strip()
    if external_id:
        return external_id
    name = _text(data.get("name")).strip().casefold()
    if not name:
        raise ValueError("Company data must include an external_id or name.")
    digest = hashlib.sha256(name.encode("utf-8")).hexdigest()
    return f"name:{digest}"


def _upsert_company(source: str, data: Any) -> Company | None:
    if not data:
        return None
    if isinstance(data, str):
        data = {"name": data}
    if not isinstance(data, Mapping):
        raise ValueError("Company data must be an object or a company name.")

    external_id = _company_external_id(data)
    defaults = {
        field: _text(data[key])
        for key, field in COMPANY_TEXT_FIELDS.items()
        if key in data
    }
    company, created = Company.objects.get_or_create(
        source=source,
        external_id=external_id,
        defaults={**defaults, "raw_data": dict(data)},
    )
    if not created:
        for field, value in defaults.items():
            setattr(company, field, value)
        company.raw_data = {**company.raw_data, **data}
        company.save(update_fields=[*defaults, "raw_data"])
    return company


def _job_defaults(payload: Mapping[str, Any]) -> dict[str, Any]:
    title = _text(payload.get("title")).strip()
    if not title:
        raise ValueError("Job data must include a title.")

    defaults: dict[str, Any] = {"title": title, "raw_data": dict(payload)}
    for key, field in JOB_TEXT_FIELDS.items():
        if key in payload:
            defaults[field] = _text(payload[key])
    if "posted_at" in payload:
        defaults["posted_at"] = _posted_date(payload["posted_at"])
    for key in ("salary_min", "salary_max"):
        if key in payload:
            defaults[key] = _decimal(payload[key], key)
    return defaults


@transaction.atomic
def _save_search_result(
    search_query: SearchQuery,
    source: str,
    payload: Mapping[str, Any],
) -> bool:
    external_id = _text(payload.get("external_id") or payload.get("id")).strip()
    if not external_id:
        raise ValueError("Job data must include an external_id.")

    defaults = _job_defaults(payload)
    if "company" in payload:
        defaults["company"] = _upsert_company(source, payload["company"])

    posting, created = JobPosting.objects.get_or_create(
        source=source,
        external_id=external_id,
        defaults=defaults,
    )
    if not created:
        for field, value in defaults.items():
            if field == "raw_data":
                posting.raw_data = {**posting.raw_data, **value}
            else:
                setattr(posting, field, value)
        posting.save(update_fields=[*defaults, "updated_at"])
    posting.found_by.add(search_query)
    return created


def run_search(
    search_query: SearchQuery,
    provider: JobDataProvider | None = None,
) -> SearchReport:
    provider = provider or get_data_provider()
    source = provider.source.strip()
    if not source:
        raise ValueError("The configured provider's source must not be empty.")

    created = updated = skipped = 0
    errors: list[str] = []
    try:
        for payload in provider.search(search_query.query, search_query.country):
            try:
                if not isinstance(payload, Mapping):
                    raise ValueError("A search result must be an object.")
                was_created = _save_search_result(search_query, source, payload)
            except ValueError as exc:
                skipped += 1
                if len(errors) < 10:
                    errors.append(str(exc))
                logger.warning("Skipping invalid job result: %s", exc)
                continue
            if was_created:
                created += 1
            else:
                updated += 1
    except ProviderError as exc:
        search_query.last_run_at = timezone.now()
        search_query.last_error = str(exc)[:4000]
        search_query.save(update_fields=("last_run_at", "last_error", "updated_at"))
        raise SearchServiceError(str(exc)) from exc

    search_query.last_run_at = timezone.now()
    search_query.last_error = "\n".join(errors)
    search_query.save(update_fields=("last_run_at", "last_error", "updated_at"))
    return SearchReport(created=created, updated=updated, skipped=skipped)


def _apply_details(posting: JobPosting, source: str, details: Mapping[str, Any]) -> None:
    for key, field in JOB_TEXT_FIELDS.items():
        if key in details:
            setattr(posting, field, _text(details[key]))
    if "posted_at" in details:
        posting.posted_at = _posted_date(details["posted_at"])
    for key in ("salary_min", "salary_max"):
        if key in details:
            setattr(posting, key, _decimal(details[key], key))
    if "company" in details:
        company = _upsert_company(source, details["company"])
        if company is not None:
            posting.company = company
    posting.raw_data = {**posting.raw_data, **details}
    posting.details_status = JobPosting.DetailsStatus.COMPLETE
    posting.details_error = ""
    posting.details_updated_at = timezone.now()
    posting.save()


def run_details(
    *,
    limit: int = 500,
    retry_failed: bool = False,
    provider: JobDataProvider | None = None,
) -> DetailsReport:
    if limit < 1:
        raise ValueError("limit must be greater than zero.")
    provider = provider or get_data_provider()
    source = provider.source.strip()
    if not source:
        raise ValueError("The configured provider's source must not be empty.")

    statuses = [JobPosting.DetailsStatus.PENDING]
    if retry_failed:
        statuses.append(JobPosting.DetailsStatus.FAILED)
    postings = (
        JobPosting.objects.filter(details_status__in=statuses)
        .select_related("company")
        .order_by("pk")[:limit]
    )

    completed = failed = 0
    for posting in postings:
        try:
            details = provider.get_details(posting)
            if not isinstance(details, Mapping):
                raise ValueError("A details response must be an object.")
            with transaction.atomic():
                _apply_details(posting, source, details)
            completed += 1
        except ProviderError as exc:
            posting.details_status = JobPosting.DetailsStatus.FAILED
            posting.details_error = str(exc)[:4000]
            posting.save(update_fields=("details_status", "details_error", "updated_at"))
            logger.warning("Details fetch failed for job %s: %s", posting.pk, exc)
            failed += 1
        except ValueError as exc:
            posting.details_status = JobPosting.DetailsStatus.FAILED
            posting.details_error = str(exc)[:4000]
            posting.save(update_fields=("details_status", "details_error", "updated_at"))
            logger.warning("Invalid details for job %s: %s", posting.pk, exc)
            failed += 1

    return DetailsReport(completed=completed, failed=failed)
