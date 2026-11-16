from django.conf import settings
from django.db import models


class SearchQuery(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="search_queries",
        null=True,
        blank=True,
    )
    query = models.CharField(max_length=255)
    country = models.CharField(max_length=128)
    enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_run_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)

    class Meta:
        ordering = ("query", "country")
        constraints = [
            models.UniqueConstraint(
                fields=("user", "query", "country"),
                name="unique_user_search_query_country",
            ),
        ]
        verbose_name_plural = "search queries"

    def __str__(self):
        return f"{self.query} ({self.country})"


class Company(models.Model):
    source = models.CharField(max_length=64)
    external_id = models.CharField(max_length=255)
    name = models.CharField(max_length=255, blank=True)
    website = models.URLField(max_length=500, blank=True)
    description = models.TextField(blank=True)
    industry = models.CharField(max_length=255, blank=True)
    employee_count = models.CharField(max_length=128, blank=True)
    headquarters = models.CharField(max_length=255, blank=True)
    profile_url = models.URLField(max_length=500, blank=True)
    raw_data = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ("name",)
        constraints = [
            models.UniqueConstraint(
                fields=("source", "external_id"),
                name="unique_company_source_external_id",
            ),
        ]

    def __str__(self):
        return self.name or self.external_id


class JobPosting(models.Model):
    class DetailsStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        COMPLETE = "complete", "Complete"
        FAILED = "failed", "Failed"

    source = models.CharField(max_length=64)
    external_id = models.CharField(max_length=255)
    title = models.CharField(max_length=500)
    company = models.ForeignKey(
        Company,
        on_delete=models.SET_NULL,
        related_name="job_postings",
        null=True,
        blank=True,
    )
    location = models.CharField(max_length=500, blank=True)
    description = models.TextField(blank=True)
    job_url = models.URLField(max_length=1000, blank=True)
    posted_at = models.DateField(null=True, blank=True)
    employment_type = models.CharField(max_length=128, blank=True)
    workplace_type = models.CharField(max_length=128, blank=True)
    salary_min = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    salary_max = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    salary_currency = models.CharField(max_length=8, blank=True)
    found_by = models.ManyToManyField(SearchQuery, related_name="job_postings", blank=True)
    details_status = models.CharField(
        max_length=16,
        choices=DetailsStatus.choices,
        default=DetailsStatus.PENDING,
    )
    details_error = models.TextField(blank=True)
    details_updated_at = models.DateTimeField(null=True, blank=True)
    first_seen_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    raw_data = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ("-first_seen_at",)
        constraints = [
            models.UniqueConstraint(
                fields=("source", "external_id"),
                name="unique_job_source_external_id",
            ),
        ]

    def __str__(self):
        return self.title
