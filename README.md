# Job postings scraper

This Django project stores job search queries, collected postings, and company
details in PostgreSQL. Searching and detail enrichment are independent stages,
so either can be run or retried separately.

## Data provider

The application deliberately does not call LinkedIn's undocumented/private
endpoints. Configure a provider only for a documented API or data source you
are authorized to use. The provider is a Python class whose dotted import path
is configured by the `JOB_DATA_PROVIDER` environment variable (defaulting to
the included LinkedIn provider). It must expose:

- `source`: a stable short string identifying the data source.
- `search(query, country)`: an iterable yielding normalized job dictionaries.
  The provider is responsible for following the source's supported pagination.
- `get_details(posting)`: a normalized job dictionary, optionally including
  nested `company` details.
- optional `get_company_details(profile_url)`: normalized company fields for
  providers that support a separate company-profile enrichment step.

Each search result must include `external_id` and `title`. Supported job fields
are `location`, `description`, `job_url`, `posted_at`, `employment_type`,
`workplace_type`, `salary_min`, `salary_max`, and `salary_currency`. Company
objects may include `external_id`, `name`, `website`, `description`,
`industry`, `employee_count`, `headquarters`, and `profile_url`. Unrecognized
provider fields are retained in `raw_data`.

The provider should translate API/network failures into
`scraper.providers.ProviderError`, honor the API's published rate limits, and
return dates as ISO-8601 strings. Do not put credentials in source control.

The included `scraper.parsers.LinkedInJobsProvider` parses the publicly
available LinkedIn jobs search and job-detail HTML pages. Use it only if your
use of that data source is permitted. It uses ordinary HTTP requests, a
15-second timeout, sequential pagination, and a one-second default delay
between search pages; it does not log in or bypass access controls. Search
pages are capped at 20 by default. You can reduce that cap or set it to the
limit allowed by your data source with `LINKEDIN_MAX_PAGES`. The details stage
also enriches known LinkedIn company profiles with public organization data;
each company profile is fetched once per details run. If LinkedIn redirects a
later page back to the first page, pagination stops rather than failing or
processing duplicate results.

## Setup

1. Create a PostgreSQL database and user, then set the database connection
   values in `config/settings.py` (or adapt that section to your deployment's
   environment-variable configuration).
2. Install dependencies: `python -m pip install -r requirements.txt`.
3. The dashboard uses `scraper.parsers.LinkedInJobsProvider` by default.
   To use a different authorized provider, set `JOB_DATA_PROVIDER` to its
   dotted class path and supply any credentials through environment variables.
4. Run `python manage.py migrate` and `python manage.py createsuperuser`.
5. Start the server with `python manage.py runserver`, create an account at
   `/register/`, and log in at `/login/`.

## Run the two stages

From the dashboard, submit a search term and country to fetch postings
immediately. Results are associated with your account so you can view, filter,
and export them. Search definitions are kept internally to scope results and
allow command-line reruns; there is no saved-search management UI.

```powershell
# Optional: replace the default provider with an authorized implementation.
# $env:JOB_DATA_PROVIDER = "your_package.YourProvider"
python manage.py run_search
python manage.py run_search --query-id 1
python manage.py run_details --limit 500
python manage.py run_details --limit 500 --retry-failed
python manage.py run_details --refresh --limit 10000
```

`run_search` processes all enabled query definitions by default and upserts
records using the provider source and external job ID. It can also be run for
one query with `--query-id`. `run_details` processes pending postings;
`--retry-failed` includes failures from earlier runs, and `--refresh` also
reprocesses completed postings so newly extracted job or company fields are
saved. Adjust `--limit` to cover the number of records you want to refresh.
Both commands can be rerun independently. Dashboard searches and commands make
network requests only when explicitly submitted or run.

The home page at `/` provides login and registration links. The authenticated
dashboard at `/dashboard/` lists and filters a user's collected postings with
pagination. Each posting's Details page displays its saved job and company
information and collection status. Search errors are stored on their search
query and can be cleared independently of collected postings. Users can remove
postings from their own results; shared postings remain available to other
users. Signed-in users can export their filtered results as CSV or Excel, and
staff can export all postings and company fields at `/jobs/export.csv`.

## Tests

The focused service tests use SQLite and fixture data; they do not call an
external API:

```powershell
python manage.py test scraper --settings=config.test_settings
```

For production-scale runs, use the authorized provider's documented page-size
and rate limits. The details command is bounded by `--limit` to support
repeatable batches.
