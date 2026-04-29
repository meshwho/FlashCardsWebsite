from collections import defaultdict
from .models import Card
import re



GERMAN_LEADING_ARTICLES = {
    "der",
    "die",
    "das",
    "den",
    "dem",
    "des",
    "ein",
    "eine",
    "einen",
    "einem",
    "einer",
    "eines",
}


def normalize_card_text(value):
    """
    Normalize text for duplicate/ambiguity detection.

    Important:
    - This does not change the real card text.
    - It is only used for comparison.
    - Leading German articles are ignored:
      "die Bank" and "Bank" are treated as the same prompt.
    """
    text = " ".join((value or "").strip().lower().split())

    if not text:
        return ""

    # Remove simple punctuation around the text.
    text = text.strip(" .,:;!?()[]{}")

    parts = text.split(maxsplit=1)

    if len(parts) == 2 and parts[0] in GERMAN_LEADING_ARTICLES:
        text = parts[1].strip()

    return text


def get_ambiguous_cards_for_user(user):
    """
    Return only unresolved ambiguous cards.

    A card is ambiguous if:
    1. The same question is used with different answers.
    2. The same answer is used with different questions.

    Important:
    - Cards with context are still used for detecting ambiguity.
    - But cards with context are not returned on the page, because they are already resolved.
    """
    cards = list(
        Card.objects
        .filter(deck__owner=user)
        .select_related("deck")
        .order_by("deck__title", "question", "answer")
    )

    question_groups = defaultdict(list)
    answer_groups = defaultdict(list)

    for card in cards:
        question_norm = normalize_card_text(card.question)
        answer_norm = normalize_card_text(card.answer)

        if question_norm:
            question_groups[question_norm].append(card)

        if answer_norm:
            answer_groups[answer_norm].append(card)

    ambiguous_card_ids = set()
    reasons_by_card_id = defaultdict(list)

    for question_norm, group in question_groups.items():
        distinct_answers = {
            normalize_card_text(card.answer)
            for card in group
            if normalize_card_text(card.answer)
        }

        if len(distinct_answers) > 1:
            for card in group:
                ambiguous_card_ids.add(card.id)
                reasons_by_card_id[card.id].append(
                    "Same question is used with different answers."
                )

    for answer_norm, group in answer_groups.items():
        distinct_questions = {
            normalize_card_text(card.question)
            for card in group
            if normalize_card_text(card.question)
        }

        if len(distinct_questions) > 1:
            for card in group:
                ambiguous_card_ids.add(card.id)
                reasons_by_card_id[card.id].append(
                    "Same answer is used with different questions."
                )

    result = []

    for card in cards:
        if card.id not in ambiguous_card_ids:
            continue

        # If context already exists, the ambiguity is considered resolved.
        # The card should not appear on the Find duplicates page.
        if (card.context or "").strip():
            continue

        result.append({
            "card": card,
            "reasons": reasons_by_card_id[card.id],
        })

    return result