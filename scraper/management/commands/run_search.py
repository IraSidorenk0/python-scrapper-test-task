from django.core.management.base import BaseCommand, CommandError

from scraper.models import SearchQuery
from scraper.services import SearchServiceError, run_search


class Command(BaseCommand):
    help = "Search for jobs for saved queries using the configured data provider."

    def add_arguments(self, parser):
        parser.add_argument(
            "--query-id",
            type=int,
            help="Run a single query, including a disabled query.",
        )

    def handle(self, *args, **options):
        query_id = options["query_id"]
        if query_id is not None:
            queries = SearchQuery.objects.filter(pk=query_id)
            if not queries.exists():
                raise CommandError(f"Search query {query_id} does not exist.")
        else:
            queries = SearchQuery.objects.filter(enabled=True).order_by("pk")

        if not queries.exists():
            self.stdout.write("No enabled search queries to run.")
            return

        for search_query in queries:
            try:
                report = run_search(search_query)
            except SearchServiceError as exc:
                raise CommandError(
                    f"Search failed for query {search_query.pk}: {exc}"
                ) from exc
            self.stdout.write(
                self.style.SUCCESS(
                    f"{search_query}: created {report.created}, "
                    f"updated {report.updated}, skipped {report.skipped}"
                )
            )