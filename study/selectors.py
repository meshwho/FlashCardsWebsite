from django.shortcuts import get_object_or_404
from django.utils import timezone

from .models import Card, Deck
from datetime import timedelta
from django.db.models import Count
from django.db.models.functions import TruncDate

def get_user_decks(user):
    return Deck.objects.filter(owner=user).order_by("title")


def get_user_deck_or_404(user, deck_id):
    return get_object_or_404(
        Deck.objects.prefetch_related("cards"),
        id=deck_id,
        owner=user,
    )


def get_user_cards(user):
    return (
        Card.objects.filter(deck__owner=user)
        .select_related("deck")
        .order_by("due", "created_at")
    )


def get_user_card_or_404(user, card_id):
    return get_object_or_404(
        Card.objects.select_related("deck"),
        id=card_id,
        deck__owner=user,
    )


def get_due_cards_for_user(user):
    return (
        Card.objects.filter(
            deck__owner=user,
            due__lte=timezone.now(),
        )
        .select_related("deck")
        .order_by("due", "created_at")
    )

def get_next_due_card_for_user(user):
    return (
        Card.objects.filter(
            deck__owner=user,
            due__lte=timezone.now(),
        )
        .select_related("deck")
        .order_by("due", "created_at")
        .first()
    )


def get_weekly_due_schedule_for_user(user, days=7):
    today = timezone.localdate()
    end_date = today + timedelta(days=days - 1)

    queryset = (
        Card.objects.filter(
            deck__owner=user,
            due__date__gte=today,
            due__date__lte=end_date,
        )
        .annotate(day=TruncDate("due"))
        .values("day")
        .annotate(count=Count("id"))
        .order_by("day")
    )

    counts_by_day = {item["day"]: item["count"] for item in queryset}

    schedule = []
    for offset in range(days):
        current_day = today + timedelta(days=offset)
        schedule.append(
            {
                "date": current_day,
                "weekday": current_day.strftime("%A"),
                "count": counts_by_day.get(current_day, 0),
                "is_today": current_day == today,
            }
        )

    return schedule