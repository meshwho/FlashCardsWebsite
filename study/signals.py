from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Card, CardActiveState, UserActivePracticeSettings


@receiver(post_save, sender=Card)
def create_card_active_state(sender, instance, created, **kwargs):
    """
    Ensure every card has a separate active-use state.

    This must stay independent from the normal FSRS state stored on Card.
    """
    if not created:
        return

    CardActiveState.objects.get_or_create(
        card=instance,
        defaults={
            "stage": CardActiveState.STAGE_PASSIVE,
        },
    )


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_user_active_practice_settings(sender, instance, created, **kwargs):
    """
    Ensure every user has default active-practice settings.
    """
    if not created:
        return

    UserActivePracticeSettings.objects.get_or_create(user=instance)