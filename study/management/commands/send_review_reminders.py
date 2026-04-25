from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import IntegrityError, transaction
from django.utils import timezone

from pywebpush import WebPushException

from study.models import PushReminderLog, PushSubscription, ReviewSlot
from study.selectors import get_due_cards_for_user
from study.push_services import (
    describe_webpush_exception,
    send_push_notification,
    should_delete_failed_subscription,
)


class Command(BaseCommand):
    help = "Send push reminders to users at their configured review slots."

    def add_arguments(self, parser):
        parser.add_argument(
            "--window-minutes",
            type=int,
            default=5,
            help=(
                "How many minutes after a review slot the reminder may still be sent. "
                "Default: 5."
            ),
        )
        parser.add_argument(
            "--username",
            type=str,
            default="",
            help="Optional username filter for testing.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be sent without sending push notifications.",
        )

    def handle(self, *args, **options):
        window_minutes = max(1, options["window_minutes"])
        username_filter = options["username"]
        dry_run = options["dry_run"]

        now_utc = timezone.now()
        User = get_user_model()

        users = User.objects.filter(
            review_schedule__is_active=True,
        ).select_related(
            "review_schedule",
        )

        if username_filter:
            users = users.filter(username=username_filter)

        checked_users = 0
        sent_count = 0
        skipped_count = 0

        for user in users:
            checked_users += 1
            schedule = user.review_schedule

            try:
                user_tz = ZoneInfo(schedule.timezone)
            except ZoneInfoNotFoundError:
                self.stderr.write(
                    f'Skipping user "{user.username}": invalid timezone {schedule.timezone!r}.'
                )
                skipped_count += 1
                continue

            local_now = now_utc.astimezone(user_tz)
            local_date = local_now.date()

            slots = ReviewSlot.objects.filter(
                schedule=schedule,
            ).order_by("position", "time")

            if not slots.exists():
                skipped_count += 1
                continue

            due_count = get_due_cards_for_user(user).count()

            if due_count <= 0:
                self.stdout.write(
                    f'Skipping user "{user.username}": no due cards.'
                )
                skipped_count += 1
                continue

            subscriptions = list(
                PushSubscription.objects.filter(user=user).order_by("-updated_at")
            )

            if not subscriptions:
                self.stdout.write(
                    f'Skipping user "{user.username}": no push subscriptions.'
                )
                skipped_count += 1
                continue

            for slot in slots:
                if not self._is_slot_in_window(
                    local_now=local_now,
                    slot_time=slot.time,
                    window_minutes=window_minutes,
                ):
                    continue

                already_sent = PushReminderLog.objects.filter(
                    user=user,
                    schedule_date=local_date,
                    slot_position=slot.position,
                ).exists()

                if already_sent:
                    self.stdout.write(
                        f'Skipping user "{user.username}", slot {slot.position}: already sent.'
                    )
                    skipped_count += 1
                    continue

                title = "FlashCards"
                body = self._build_body(due_count)

                self.stdout.write(
                    f'Reminder due for "{user.username}" '
                    f'at {slot.time.strftime("%H:%M")} '
                    f'({schedule.timezone}), due cards: {due_count}.'
                )

                if dry_run:
                    self.stdout.write("Dry run: notification not sent.")
                    continue

                successful_sends = 0

                for subscription in subscriptions:
                    try:
                        response = send_push_notification(
                            subscription,
                            title=title,
                            body=body,
                            url="/study/",
                        )
                    except WebPushException as exc:
                        self.stderr.write(
                            f'Push failed for "{user.username}": '
                            f"{describe_webpush_exception(exc)}"
                        )

                        if should_delete_failed_subscription(exc):
                            subscription.delete()
                            self.stderr.write(
                                "Expired/invalid subscription deleted."
                            )

                        continue

                    successful_sends += 1

                    if response is not None:
                        self.stdout.write(
                            f"Push response status: {response.status_code}"
                        )

                if successful_sends > 0:
                    try:
                        with transaction.atomic():
                            PushReminderLog.objects.create(
                                user=user,
                                schedule_date=local_date,
                                slot_position=slot.position,
                                slot_time=slot.time,
                                due_count=due_count,
                            )
                    except IntegrityError:
                        self.stdout.write(
                            f'Reminder log already exists for "{user.username}", '
                            f"slot {slot.position}."
                        )
                        continue

                    sent_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Done. Checked users: {checked_users}, "
                f"sent reminders: {sent_count}, skipped: {skipped_count}."
            )
        )

    def _is_slot_in_window(self, *, local_now, slot_time, window_minutes):
        slot_datetime = datetime.combine(
            local_now.date(),
            slot_time,
            tzinfo=local_now.tzinfo,
        )

        window_end = slot_datetime + timedelta(minutes=window_minutes)

        return slot_datetime <= local_now < window_end

    def _build_body(self, due_count):
        if due_count == 1:
            return "You have 1 card ready to review."

        return f"You have {due_count} cards ready to review."