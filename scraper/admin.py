from django.contrib import admin

from scraper.models import Company, JobPosting, SearchQuery


@admin.register(SearchQuery)
class SearchQueryAdmin(admin.ModelAdmin):
    list_display = ("query", "country", "user", "enabled", "last_run_at")
    list_filter = ("enabled", "country")
    search_fields = ("query", "country", "user__username")
    readonly_fields = ("created_at", "updated_at", "last_run_at", "last_error")


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ("name", "source", "external_id", "industry", "website")
    list_filter = ("source", "industry")
    search_fields = ("name", "external_id", "industry")


@admin.register(JobPosting)
class JobPostingAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "company",
        "location",
        "source",
        "details_status",
        "first_seen_at",
    )
    list_filter = ("details_status", "source", "employment_type", "workplace_type")
    search_fields = ("title", "company__name", "location", "external_id")
    readonly_fields = (
        "first_seen_at",
        "updated_at",
        "details_updated_at",
        "details_error",
        "raw_data",
    )
    filter_horizontal = ("found_by",)
