from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from pywebpush import WebPushException

from study.models import PushSubscription
from study.push_services import (
    describe_webpush_exception,
    send_push_notification,
    should_delete_failed_subscription,
)


class Command(BaseCommand):
    help = "Send a test push notification to a user's latest push subscription."

    def add_arguments(self, parser):
        parser.add_argument(
            "username",
            type=str,
            help="Username of the user who should receive the test push.",
        )

    def handle(self, *args, **options):
        username = options["username"]

        User = get_user_model()

        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            raise CommandError(f'User "{username}" does not exist.')

        subscription = (
            PushSubscription.objects
            .filter(user=user)
            .order_by("-updated_at")
            .first()
        )

        if subscription is None:
            raise CommandError(f'User "{username}" has no push subscriptions.')

        self.stdout.write(f'Sending test push to "{username}"...')
        self.stdout.write(f"Endpoint: {subscription.endpoint[:100]}...")

        try:
            response = send_push_notification(
                subscription,
                title="FlashCards test",
                body="Server push notification is working.",
                url="/",
            )
        except WebPushException as exc:
            if should_delete_failed_subscription(exc):
                subscription.delete()
                raise CommandError(
                    "Push subscription is expired or invalid. "
                    "It was deleted from the database."
                )

            raise CommandError(
                f"Push failed: {describe_webpush_exception(exc)}"
            ) from exc

        self.stdout.write(self.style.SUCCESS("Test push sent successfully."))

        if response is not None:
            self.stdout.write(f"Push service response status: {response.status_code}")
            self.stdout.write(f"Push service response headers: {dict(response.headers)}")