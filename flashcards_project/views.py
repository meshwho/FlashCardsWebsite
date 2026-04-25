from pathlib import Path

from django.conf import settings
from django.http import FileResponse, Http404


def service_worker_view(request):
    service_worker_path = (
        Path(settings.BASE_DIR)
        / "static"
        / "js"
        / "service-worker.js"
    )

    if not service_worker_path.exists():
        raise Http404("Service worker file not found.")

    response = FileResponse(
        open(service_worker_path, "rb"),
        content_type="application/javascript",
    )

    # Service worker should update reliably after deployment.
    response["Cache-Control"] = "no-cache"

    # Allow this service worker to control the whole site.
    response["Service-Worker-Allowed"] = "/"

    return response