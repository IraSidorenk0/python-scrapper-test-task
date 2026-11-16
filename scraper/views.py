import csv

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.views import LoginView, LogoutView
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_POST
from django.views.generic import CreateView

from scraper.forms import SearchQueryForm
from scraper.models import JobPosting, SearchQuery


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
            messages.success(
                request,
                "Search saved and queued. Run the search command to collect its results.",
            )
            return redirect("scraper:dashboard")
    else:
        form = SearchQueryForm()

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

    postings = _user_postings(
        request.user,
        search_term=search_term,
        country=country,
        search_query=search_query,
    )
    page = Paginator(postings, 25).get_page(request.GET.get("page"))
    queries = SearchQuery.objects.filter(user=request.user).order_by("-created_at")
    return render(
        request,
        "dashboard.html",
        {
            "form": form,
            "page": page,
            "queries": queries,
            "search_term": search_term,
            "country": country,
            "selected_query": search_query,
        },
    )


@login_required
@require_POST
def toggle_search_query(request, query_id):
    query = get_object_or_404(SearchQuery, pk=query_id, user=request.user)
    query.enabled = not query.enabled
    query.save(update_fields=("enabled", "updated_at"))
    messages.success(
        request,
        f"Search {'enabled' if query.enabled else 'paused'}.",
    )
    return redirect("scraper:dashboard")


@login_required
@require_POST
def delete_search_query(request, query_id):
    query = get_object_or_404(SearchQuery, pk=query_id, user=request.user)
    query.delete()
    messages.success(
        request,
        "Search removed. Collected job postings remain in the database.",
    )
    return redirect("scraper:dashboard")


class _CsvEcho:
    def write(self, value):
        return value


def _csv_value(value):
    value = "" if value is None else str(value)
    if value.startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + value
    return value


def _jobs_csv_response(postings, filename):
    fields = (
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
    writer = csv.writer(_CsvEcho())

    def rows():
        yield "\ufeff"
        yield writer.writerow(fields)
        for posting in postings.select_related("company").order_by("pk").iterator(
            chunk_size=1000
        ):
            company = posting.company
            values = (
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
            yield writer.writerow([_csv_value(value) for value in values])

    response = StreamingHttpResponse(
        rows(),
        content_type="text/csv; charset=utf-8",
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@login_required
def export_user_jobs_csv(request):
    query_id = request.GET.get("query_id", "").strip()
    search_query = None
    if query_id:
        search_query = get_object_or_404(
            SearchQuery,
            pk=query_id,
            user=request.user,
        )
    postings = _user_postings(
        request.user,
        search_term=request.GET.get("q", "").strip(),
        country=request.GET.get("country", "").strip(),
        search_query=search_query,
    )
    return _jobs_csv_response(postings, "my-job-postings.csv")


@staff_member_required
def export_jobs_csv(request):
    return _jobs_csv_response(JobPosting.objects.all(), "job-postings.csv")
