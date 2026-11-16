import csv
import json
from io import BytesIO
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.views import LoginView, LogoutView
from django.core.exceptions import ImproperlyConfigured
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.views.decorators.http import require_POST
from django.views.generic import CreateView
from openpyxl import Workbook

from scraper.forms import SearchQueryForm
from scraper.models import JobPosting, SearchQuery
from scraper.services import SearchServiceError, run_search


def home(request):
    if request.user.is_authenticated:
        return redirect("scraper:dashboard")
    return render(request, "home.html")


class RegisterView(CreateView):
    form_class = UserCreationForm
    template_name = "registration/register.html"
    success_url = reverse_lazy("scraper:dashboard")

    def form_valid(self, form):
        response = super().form_valid(form)
        login(self.request, self.object)
        return response


class ScraperLoginView(LoginView):
    template_name = "registration/login.html"


class ScraperLogoutView(LogoutView):
    pass


def _user_postings(user, *, search_term="", country="", search_query=None):
    postings = (
        JobPosting.objects.filter(found_by__user=user)
        .select_related("company")
        .distinct()
    )
    if search_term:
        postings = postings.filter(
            Q(title__icontains=search_term)
            | Q(description__icontains=search_term)
            | Q(location__icontains=search_term)
            | Q(company__name__icontains=search_term)
        )
    if country:
        postings = postings.filter(found_by__country__icontains=country)
    if search_query is not None:
        postings = postings.filter(found_by=search_query)
    return postings.order_by("-first_seen_at")


@login_required
def dashboard(request):
    if request.method == "POST":
        form = SearchQueryForm(request.POST)
        if form.is_valid():
            query, created = SearchQuery.objects.get_or_create(
                user=request.user,
                query=form.cleaned_data["query"],
                country=form.cleaned_data["country"],
            )
            if not created and not query.enabled:
                query.enabled = True
                query.save(update_fields=("enabled", "updated_at"))
            try:
                report = run_search(query)
            except (SearchServiceError, ImproperlyConfigured, ValueError) as exc:
                messages.error(request, f"LinkedIn search failed: {exc}")
            else:
                total = report.created + report.updated
                if total == 0 and report.skipped:
                    messages.warning(
                        request,
                        "No valid job postings were returned. Check the search errors below.",
                    )
                elif total == 0:
                    messages.info(
                        request,
                        "No public vacancies were found for this search.",
                    )
                elif report.skipped:
                    messages.warning(
                        request,
                        f"Found {total} vacancies; skipped {report.skipped} invalid results.",
                    )
                else:
                    messages.success(
                        request,
                        f"Found {total} vacancies "
                        f"({report.created} new, {report.updated} updated).",
                    )
            return redirect(f"{reverse('scraper:dashboard')}?query_id={query.pk}")
    else:
        form = None

    search_term = request.GET.get("q", "").strip()
    country = request.GET.get("country", "").strip()
    search_query = None
    query_id = request.GET.get("query_id", "").strip()
    if query_id:
        search_query = get_object_or_404(
            SearchQuery,
            pk=query_id,
            user=request.user,
        )

    if form is None:
        initial = {}
        if search_query is not None:
            initial = {
                "query": search_query.query,
                "country": search_query.country,
            }
        form = SearchQueryForm(initial=initial)

    postings = _user_postings(
        request.user,
        search_term=search_term,
        country=country,
        search_query=search_query,
    )
    page = Paginator(postings, 25).get_page(request.GET.get("page"))
    page_range = list(
        page.paginator.get_elided_page_range(
            page.number,
            on_each_side=1,
            on_ends=1,
        )
    )
    return render(
        request,
        "dashboard.html",
        {
            "form": form,
            "page": page,
            "page_range": page_range,
            "search_term": search_term,
            "country": country,
            "selected_query": search_query,
        },
    )


def _dashboard_return_url(request):
    query_params = {
        key: value
        for key in ("q", "country", "query_id", "page")
        if (value := request.GET.get(key, "").strip())
    }
    dashboard_url = reverse("scraper:dashboard")
    if query_params:
        dashboard_url = f"{dashboard_url}?{urlencode(query_params)}"
    return dashboard_url


@login_required
@require_POST
def clear_search_error(request, query_id):
    search_query = get_object_or_404(
        SearchQuery,
        pk=query_id,
        user=request.user,
    )
    if search_query.last_error:
        search_query.last_error = ""
        search_query.save(update_fields=("last_error", "updated_at"))
        messages.success(request, "Saved search error cleared.")
    return redirect(_dashboard_return_url(request))


@login_required
def job_details(request, job_id):
    posting = get_object_or_404(
        JobPosting.objects.filter(found_by__user=request.user)
        .select_related("company")
        .distinct(),
        pk=job_id,
    )
    company = posting.company
    return render(
        request,
        "job_details.html",
        {
            "job": posting,
            "company": company,
            "back_url": _dashboard_return_url(request),
            "job_raw_data": json.dumps(
                posting.raw_data,
                ensure_ascii=False,
                indent=2,
            ),
            "company_raw_data": json.dumps(
                company.raw_data if company else {},
                ensure_ascii=False,
                indent=2,
            ),
        },
    )


@login_required
@require_POST
def remove_user_job(request, job_id):
    with transaction.atomic():
        posting = get_object_or_404(
            JobPosting.objects.filter(found_by__user=request.user).distinct(),
            pk=job_id,
        )
        user_query_ids = list(
            SearchQuery.objects.filter(user=request.user).values_list("pk", flat=True)
        )
        posting.found_by.remove(*user_query_ids)
        if not posting.found_by.exists():
            posting.delete()

    messages.success(request, "Job posting removed from your results.")
    return redirect(_dashboard_return_url(request))


class _CsvEcho:
    def write(self, value):
        return value


def _csv_value(value):
    value = "" if value is None else str(value)
    if value.startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + value
    return value


def _excel_value(value):
    if isinstance(value, str) and value.startswith(
        ("=", "+", "-", "@", "\t", "\r")
    ):
        return "'" + value
    return value


JOB_EXPORT_FIELDS = (
    "job_id",
    "title",
    "company",
    "company_website",
    "company_description",
    "company_industry",
    "company_employee_count",
    "company_headquarters",
    "company_profile_url",
    "location",
    "description",
    "job_url",
    "posted_at",
    "employment_type",
    "workplace_type",
    "salary_min",
    "salary_max",
    "salary_currency",
    "source",
    "external_id",
    "details_status",
)


def _job_export_values(posting):
    company = posting.company
    return (
        posting.pk,
        posting.title,
        company.name if company else "",
        company.website if company else "",
        company.description if company else "",
        company.industry if company else "",
        company.employee_count if company else "",
        company.headquarters if company else "",
        company.profile_url if company else "",
        posting.location,
        posting.description,
        posting.job_url,
        posting.posted_at,
        posting.employment_type,
        posting.workplace_type,
        posting.salary_min,
        posting.salary_max,
        posting.salary_currency,
        posting.source,
        posting.external_id,
        posting.get_details_status_display(),
    )


def _jobs_csv_response(postings, filename):
    writer = csv.writer(_CsvEcho())

    def rows():
        yield "\ufeff"
        yield writer.writerow(JOB_EXPORT_FIELDS)
        for posting in postings.select_related("company").order_by("pk").iterator(
            chunk_size=1000
        ):
            yield writer.writerow(
                [_csv_value(value) for value in _job_export_values(posting)]
            )

    response = StreamingHttpResponse(
        rows(),
        content_type="text/csv; charset=utf-8",
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def _user_export_postings(request):
    query_id = request.GET.get("query_id", "").strip()
    search_query = None
    if query_id:
        search_query = get_object_or_404(
            SearchQuery,
            pk=query_id,
            user=request.user,
        )
    return _user_postings(
        request.user,
        search_term=request.GET.get("q", "").strip(),
        country=request.GET.get("country", "").strip(),
        search_query=search_query,
    )


@login_required
def export_user_jobs_csv(request):
    return _jobs_csv_response(_user_export_postings(request), "my-job-postings.csv")


@login_required
def export_user_jobs_excel(request):
    postings = _user_export_postings(request)
    workbook = Workbook(write_only=True)
    worksheet = workbook.create_sheet(title="Job postings")
    worksheet.append(JOB_EXPORT_FIELDS)
    for posting in postings.select_related("company").order_by("pk").iterator(
        chunk_size=1000
    ):
        values = _job_export_values(posting)
        worksheet.append([_excel_value(value) for value in values])

    output = BytesIO()
    workbook.save(output)
    response = HttpResponse(
        output.getvalue(),
        content_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
    )
    response["Content-Disposition"] = 'attachment; filename="my-job-postings.xlsx"'
    return response


@staff_member_required
def export_jobs_csv(request):
    return _jobs_csv_response(JobPosting.objects.all(), "job-postings.csv")
