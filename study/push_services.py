import json

from django.conf import settings
from pywebpush import WebPushException, webpush


def build_push_subscription_info(subscription):
    return {
        "endpoint": subscription.endpoint,
        "keys": {
            "p256dh": subscription.p256dh,
            "auth": subscription.auth,
        },
    }


def build_push_headers(endpoint):
    headers = {
        "TTL": "600",
    }

    endpoint_lower = endpoint.lower()

    # Microsoft Edge / Windows uses WNS endpoints.
    # WNS requires X-WNS-Type for raw push messages.
    if "notify.windows.com" in endpoint_lower:
        headers.update({
            "X-WNS-Type": "wns/raw",
            "Content-Type": "application/octet-stream",
        })

    return headers


def send_push_notification(subscription, *, title, body, url="/"):
    private_key_path = getattr(settings, "WEB_PUSH_VAPID_PRIVATE_KEY_PATH", "")
    admin_email = getattr(settings, "WEB_PUSH_VAPID_ADMIN_EMAIL", "")

    if not private_key_path:
        raise ValueError("WEB_PUSH_VAPID_PRIVATE_KEY_PATH is not configured.")

    if not admin_email:
        raise ValueError("WEB_PUSH_VAPID_ADMIN_EMAIL is not configured.")

    payload = {
        "title": title,
        "body": body,
        "url": url,
    }

    return webpush(
        subscription_info=build_push_subscription_info(subscription),
        data=json.dumps(payload),
        vapid_private_key=private_key_path,
        vapid_claims={
            "sub": admin_email,
        },
        headers=build_push_headers(subscription.endpoint),
    )


def should_delete_failed_subscription(exception):
    response = getattr(exception, "response", None)

    if response is None:
        return False

    return response.status_code in (404, 410)


def describe_webpush_exception(exception):
    response = getattr(exception, "response", None)

    if response is None:
        return str(exception)

    return (
        f"status={response.status_code}, "
        f"headers={dict(response.headers)}, "
        f"body={response.text}"
    )