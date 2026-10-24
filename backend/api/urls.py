from django.urls import path

from . import views


urlpatterns = [
    path("api/fixtures/", views.fixtures, name="fixtures"),
    path("api/verify/", views.verify_view, name="verify"),
    path("api/diagnose/", views.diagnose_view, name="diagnose"),
    path("api/analyze/", views.analyze_view, name="analyze"),
    path("api/fix/", views.fix_view, name="fix"),
    path("api/recorded/", views.recorded_view, name="recorded"),
    path("api/health/", views.health_view, name="health"),
    path("api/project/scan", views.project_scan_view, name="project-scan"),
    path("api/project/fix", views.project_fix_view, name="project-fix"),
    path("api/project/apply", views.project_apply_view, name="project-apply"),
]
