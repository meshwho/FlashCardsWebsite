from django.db import transaction

from .models import Card
from .selectors import get_user_review_slots, get_or_create_user_review_schedule
from .scheduling import snap_due_to_next_slot


@transaction.atomic
def reschedule_all_user_cards(user):
    schedule = get_or_create_user_review_schedule(user)
    slot_times = get_user_review_slots(user)
    tz_name = schedule.timezone if schedule else "Europe/Zaporozhye"

    cards = Card.objects.filter(deck__owner=user).select_related("deck")

    updated_cards = []
    for card in cards:
        snapped_due = snap_due_to_next_slot(card.due, slot_times, tz_name=tz_name)

        if snapped_due != card.due:
            card.due = snapped_due
            updated_cards.append(card)

    if updated_cards:
        Card.objects.bulk_update(updated_cards, ["due"])

    return len(updated_cards)