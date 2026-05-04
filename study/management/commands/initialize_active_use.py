from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from study.active_initialization import get_initial_active_stage_for_card
from study.models import Card, CardActiveState, UserActivePracticeSettings


class Command(BaseCommand):
    help = (
        "Initialize Active Use Layer for existing cards and users. "
        "Creates missing CardActiveState and UserActivePracticeSettings records. "
        "Existing stable review cards become active candidates."
    )

    def handle(self, *args, **options):
        created_active_states = 0
        updated_to_candidates = 0
        created_user_settings = 0

        for card in Card.objects.all().iterator():
            initial_stage = get_initial_active_stage_for_card(card)

            active_state, created = CardActiveState.objects.get_or_create(
                card=card,
                defaults={
                    "stage": initial_stage,
                    "is_active_pipeline": False,
                },
            )

            if created:
                created_active_states += 1

                if initial_stage == CardActiveState.STAGE_CANDIDATE:
                    updated_to_candidates += 1

                continue

            # If the active state already exists and is still passive,
            # we may safely upgrade it to candidate based on existing FSRS history.
            # We do NOT downgrade anything here.
            # We also do NOT put it into active pipeline here.
            if (
                active_state.stage == CardActiveState.STAGE_PASSIVE
                and initial_stage == CardActiveState.STAGE_CANDIDATE
            ):
                active_state.stage = CardActiveState.STAGE_CANDIDATE
                active_state.is_active_pipeline = False
                active_state.save(update_fields=["stage", "is_active_pipeline"])
                updated_to_candidates += 1

        User = get_user_model()

        for user in User.objects.all().iterator():
            _, created = UserActivePracticeSettings.objects.get_or_create(user=user)

            if created:
                created_user_settings += 1

        self.stdout.write(
            self.style.SUCCESS(
                "Active Use initialization completed. "
                f"Created active states: {created_active_states}. "
                f"Marked candidates: {updated_to_candidates}. "
                f"Created user settings: {created_user_settings}."
            )
        )