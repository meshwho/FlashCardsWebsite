from .models import Card, CardActiveState, ReviewLog


MEMORY_SUCCESS_RATINGS = {
    3,  # Good
    4,  # Easy
}


def card_is_ready_for_active_candidate(card: Card) -> bool:
    """
    Decide whether an existing card is ready to enter the Active Use candidate pool.

    Important:
    - This does NOT put the card into active practice immediately.
    - It only marks the card as a candidate.
    - The future queue manager will decide when to start active practice.
    """

    if card.state != Card.STATE_REVIEW:
        return False

    recent_logs = list(
        ReviewLog.objects
        .filter(card=card)
        .order_by("-reviewed_at")[:2]
    )

    if len(recent_logs) < 2:
        return False

    return all(log.rating in MEMORY_SUCCESS_RATINGS for log in recent_logs)


def get_initial_active_stage_for_card(card: Card) -> str:
    """
    Initial stage for existing cards.

    Existing cards that are already stable in normal FSRS become candidates.
    Everything else remains passive.
    """

    if card_is_ready_for_active_candidate(card):
        return CardActiveState.STAGE_CANDIDATE

    return CardActiveState.STAGE_PASSIVE