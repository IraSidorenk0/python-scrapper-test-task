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
        "dashboard/export.csv",
        views.export_user_jobs_csv,
        name="export_user_jobs_csv",
    ),
    path(
        "dashboard/export.xlsx",
        views.export_user_jobs_excel,
        name="export_user_jobs_excel",
    ),
    path("jobs/export.csv", views.export_jobs_csv, name="export_jobs_csv"),
]
