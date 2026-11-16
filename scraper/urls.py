from django.urls import path

from scraper import views

app_name = "scraper"

urlpatterns = [
    path("", views.home, name="home"),
    path("register/", views.RegisterView.as_view(), name="register"),
    path("login/", views.ScraperLoginView.as_view(), name="login"),
    path("logout/", views.ScraperLogoutView.as_view(), name="logout"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path(
        "dashboard/search/<int:query_id>/toggle/",
        views.toggle_search_query,
        name="toggle_search_query",
    ),
    path(
        "dashboard/search/<int:query_id>/delete/",
        views.delete_search_query,
        name="delete_search_query",
    ),
    path(
        "dashboard/export.csv",
        views.export_user_jobs_csv,
        name="export_user_jobs_csv",
    ),
    path("jobs/export.csv", views.export_jobs_csv, name="export_jobs_csv"),
]
