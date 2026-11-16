# Job postings scraper

This Django project stores job search queries, collected postings, and company
details in PostgreSQL. Searching and detail enrichment are separate commands,
so either stage can be run or retried independently.

## Data provider

The application deliberately does not call LinkedIn's undocumented/private
endpoints. Configure a provider only for a documented API or data source you
are authorized to use. The provider is a Python class whose dotted import path
is set in the `JOB_DATA_PROVIDER` environment variable. It must expose:

- `source`: a stable short string identifying the data source.
- `search(query, country)`: an iterable yielding normalized job dictionaries.
  The provider is responsible for following the source's supported pagination.
- `get_details(posting)`: a normalized job dictionary, optionally including
  nested `company` details.

Each search result must include `external_id` and `title`. Supported job fields
are `location`, `description`, `job_url`, `posted_at`, `employment_type`,
`workplace_type`, `salary_min`, `salary_max`, and `salary_currency`. Company
objects may include `external_id`, `name`, `website`, `description`,
`industry`, `employee_count`, `headquarters`, and `profile_url`. Unrecognized
provider fields are retained in `raw_data`.

The provider should translate API/network failures into
`scraper.providers.ProviderError`, honor the API's published rate limits, and
return dates as ISO-8601 strings. Do not put credentials in source control.

## Setup

1. Create a PostgreSQL database and user, then set the database connection
   values in `config/settings.py` (or adapt that section to your deployment's
   environment-variable configuration).
2. Install dependencies: `python -m pip install -r requirements.txt`.
3. Configure `JOB_DATA_PROVIDER` to the dotted path of your authorized
   provider class and supply its credentials through environment variables.
4. Run `python manage.py migrate` and `python manage.py createsuperuser`.
5. Start the server with `python manage.py runserver`, create an account at
   `/register/`, and log in at `/login/`.

## Run the two stages

From the dashboard, submit a search term and country. Searches are saved for
the signed-in user and picked up by the search command; job results are scoped
to that user's saved searches. Use the dashboard to filter or export results,
pause searches, or remove a saved search. Removing a search does not delete
collected postings.

```powershell
python manage.py run_search
python manage.py run_search --query-id 1
python manage.py run_details --limit 500
python manage.py run_details --limit 500 --retry-failed
```

`run_search` processes all enabled queries by default and upserts records using
the provider source and external job ID. `run_details` processes pending
postings; `--retry-failed` includes failures from earlier runs. Both commands
can be run repeatedly. The commands make no network requests until a provider
is configured.

The home page at `/` provides login and registration links. The authenticated
dashboard at `/dashboard/` lists and filters a user's collected postings with
pagination. Signed-in users can export their own results and staff can export
all postings and company fields at `/jobs/export.csv`.

## Tests

The focused service tests use SQLite and fixture data; they do not call an
external API:

```powershell
python manage.py test scraper --settings=config.test_settings
```

For production-scale runs, use the authorized provider's documented page-size
and rate limits. The details command is bounded by `--limit` to support
repeatable batches.
