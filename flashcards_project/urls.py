from django.contrib import admin
from django.urls import include, path

from .views import service_worker_view


urlpatterns = [
    path("service-worker.js", service_worker_view, name="service_worker"),
    path("admin/", admin.site.urls),
    path("accounts/", include("django.contrib.auth.urls")),
    path("", include("study.urls")),
]