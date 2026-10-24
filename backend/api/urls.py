from django.urls import path

from . import views


urlpatterns = [
    path("api/fixtures/", views.fixtures, name="fixtures"),
    path("api/verify/", views.verify_view, name="verify"),
    path("api/diagnose/", views.diagnose_view, name="diagnose"),
    path("api/fix/", views.fix_view, name="fix"),
    path("api/recorded/", views.recorded_view, name="recorded"),
]
