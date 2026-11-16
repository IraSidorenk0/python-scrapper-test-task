from django.core.management.base import BaseCommand, CommandError

from scraper.services import run_details


class Command(BaseCommand):
    help = "Fetch details for saved job postings using the configured data provider."

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=500,
            help="Maximum number of postings to process in this run (default: 500).",
        )
        parser.add_argument(
            "--retry-failed",
            action="store_true",
            help="Also retry postings whose previous details request failed.",
        )

    def handle(self, *args, **options):
        try:
            report = run_details(
                limit=options["limit"],
                retry_failed=options["retry_failed"],
            )
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(
            self.style.SUCCESS(
                f"Details complete: {report.completed} succeeded, "
                f"{report.failed} failed."
            )
        )