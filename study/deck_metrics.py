from django.utils import timezone

from .models import ReviewLog
from .services import FSRS_DESIRED_RETENTION

DESIRED_RETENTION = FSRS_DESIRED_RETENTION


def clamp(value: float, min_value: float, max_value: float) -> float:
    return max(min_value, min(value, max_value))


def get_memory_label(score: float) -> str:
    if score < 3.0:
        return "Weak"
    if score < 5.5:
        return "Growing"
    if score < 8.0:
        return "Strong"
    return "Excellent"


def get_memory_badge_class(score: float) -> str:
    if score < 3.0:
        return "badge-red"
    if score < 5.5:
        return "badge-amber"
    if score < 8.0:
        return "badge-green"
    return "badge-accent"


def estimate_card_retrievability(card, now=None) -> float:
    """
    Stricter estimate of current recall probability.

    Principles:
    - new/learning cards start low
    - relearning cards are penalized harder
    - overdue cards drop faster
    - review cards can score high, but not too easily
    """
    now = now or timezone.now()

    # New / never reviewed cards
    if not card.last_review:
        if card.state == "Review":
            return 0.60
        if card.state == "Learning":
            return 0.20
        if card.state == "Relearning":
            return 0.12
        return 0.18

    last_review = card.last_review
    due = card.due or now

    scheduled_seconds = (due - last_review).total_seconds()
    elapsed_seconds = (now - last_review).total_seconds()

    if scheduled_seconds <= 0:
        if now <= due:
            return 0.75
        return 0.30

    elapsed_ratio = max(elapsed_seconds / scheduled_seconds, 0.0)

    # Base FSRS-like decay
    retrievability = DESIRED_RETENTION ** elapsed_ratio

    # Stronger penalties for weaker states
    if card.state == "Learning":
        retrievability *= 0.72
    elif card.state == "Relearning":
        retrievability *= 0.58

    # Additional overdue penalty
    if now > due:
        overdue_seconds = (now - due).total_seconds()
        overdue_ratio = overdue_seconds / scheduled_seconds
        retrievability *= 0.85 ** max(overdue_ratio, 0.0)

    return clamp(retrievability, 0.0, 1.0)


def calculate_deck_memory_score(deck) -> float:
    cards = list(deck.cards.all())

    if not cards:
        return 1.0

    now = timezone.now()
    retrievabilities = [estimate_card_retrievability(card, now=now) for card in cards]
    avg_retrievability = sum(retrievabilities) / len(retrievabilities)

    total_cards = len(cards)
    due_now_count = sum(1 for card in cards if card.due and card.due <= now)
    learning_count = sum(1 for card in cards if card.state == "Learning")
    relearning_count = sum(1 for card in cards if card.state == "Relearning")

    due_penalty = due_now_count / total_cards
    learning_penalty = learning_count / total_cards
    relearning_penalty = relearning_count / total_cards

    recent_logs = list(
        ReviewLog.objects.filter(card__deck=deck).order_by("-reviewed_at")[:30]
    )

    if recent_logs:
        success_ratio = sum(1 for log in recent_logs if log.rating in (3, 4)) / len(recent_logs)
        fail_ratio = sum(1 for log in recent_logs if log.rating == 1) / len(recent_logs)
    else:
        success_ratio = 0.35
        fail_ratio = 0.35

    adjusted = avg_retrievability

    # Real review history correction
    adjusted = 0.75 * adjusted + 0.15 * success_ratio + 0.10 * (1.0 - fail_ratio)

    # Strong penalties
    adjusted -= 0.22 * due_penalty
    adjusted -= 0.18 * learning_penalty
    adjusted -= 0.22 * relearning_penalty

    adjusted = clamp(adjusted, 0.0, 1.0)

    # Nonlinear conversion: harder to get high scores
    score_10 = 1.0 + (adjusted ** 1.65) * 9.0
    score_10 = round(clamp(score_10, 1.0, 10.0), 1)

    return score_10


def enrich_deck_with_memory_score(deck):
    score = calculate_deck_memory_score(deck)
    deck.memory_score = score
    deck.memory_label = get_memory_label(score)
    deck.memory_badge_class = get_memory_badge_class(score)
    deck.memory_percent = round((score - 1.0) / 9.0 * 100.0)
    return deck


def enrich_decks_with_memory_scores(decks):
    return [enrich_deck_with_memory_score(deck) for deck in decks]