from typing import Any, Iterable, Mapping, Protocol, TYPE_CHECKING

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils.module_loading import import_string

if TYPE_CHECKING:
    from scraper.models import JobPosting


class ProviderError(Exception):
    """Raised by a provider when its authorized data source cannot be reached."""


class JobDataProvider(Protocol):
    source: str

    def search(self, query: str, country: str) -> Iterable[Mapping[str, Any]]:
        """Yield normalized job dictionaries, following the source's pagination."""
        ...

    def get_details(self, posting: "JobPosting") -> Mapping[str, Any]:
        """Return normalized job and optional nested company fields."""
        ...


def get_data_provider() -> JobDataProvider:
    provider_path = getattr(settings, "JOB_DATA_PROVIDER", "")
    if not provider_path:
        raise ImproperlyConfigured(
            "Set JOB_DATA_PROVIDER to a provider class using an authorized, "
            "documented job-data API."
        )

    provider_class = import_string(provider_path)
    provider = provider_class()
    if not isinstance(getattr(provider, "source", None), str):
        raise ImproperlyConfigured("The configured provider must define a string 'source'.")
    if not callable(getattr(provider, "search", None)):
        raise ImproperlyConfigured("The configured provider must implement search().")
    if not callable(getattr(provider, "get_details", None)):
        raise ImproperlyConfigured("The configured provider must implement get_details().")
    return provider
