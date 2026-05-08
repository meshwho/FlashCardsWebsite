import random

from .card_duplicates import normalize_card_text
from .models import Card


TRANSLATION_TEST_SESSION_KEY = "translation_test_session"

TRANSLATION_TEST_MIN_WORDS = 4
TRANSLATION_TEST_MAX_WORDS = 50


def normalize_test_option(value):
    return " ".join((value or "").strip().lower().split())


def choose_random_cards_for_test(user, count):
    cards = list(
        Card.objects
        .filter(deck__owner=user)
        .select_related("deck")
        .exclude(question__exact="")
        .exclude(answer__exact="")
    )

    random.shuffle(cards)

    selected = []
    seen = set()

    for card in cards:
        key = (
            normalize_card_text(card.question),
            normalize_test_option(card.answer),
        )

        if key in seen:
            continue

        seen.add(key)
        selected.append(card)

        if len(selected) >= count:
            break

    return selected


def _get_option_value(card, option_side):
    if option_side == "question":
        return (card.question or "").strip()

    return (card.answer or "").strip()


def _collect_distractors(pool_cards, correct_option, option_side):
    correct_key = normalize_test_option(correct_option)

    distractors = []
    seen = set()

    for card in pool_cards:
        option = _get_option_value(card, option_side)
        option_key = normalize_test_option(option)

        if not option or not option_key:
            continue

        if option_key == correct_key:
            continue

        if option_key in seen:
            continue

        seen.add(option_key)
        distractors.append(option)

    random.shuffle(distractors)
    return distractors


def _build_options(pool_cards, correct_option, option_side):
    distractors = _collect_distractors(
        pool_cards=pool_cards,
        correct_option=correct_option,
        option_side=option_side,
    )

    if len(distractors) < 3:
        raise ValueError(
            "Not enough unique answer options to build the test. "
            "Add more cards with different questions and translations."
        )

    options = [correct_option] + distractors[:3]
    random.shuffle(options)

    return options


def _build_item_for_direction(card, pool_cards, direction):
    if direction == "reverse":
        prompt_text = (card.answer or "").strip()
        correct_option = (card.question or "").strip()
        option_side = "question"
        direction_label = "Translation → German"
    else:
        prompt_text = (card.question or "").strip()
        correct_option = (card.answer or "").strip()
        option_side = "answer"
        direction_label = "German → Translation"

    if not prompt_text or not correct_option:
        raise ValueError("Card has empty question or answer.")

    options = _build_options(
        pool_cards=pool_cards,
        correct_option=correct_option,
        option_side=option_side,
    )

    return {
        "card_id": str(card.id),
        "deck_title": card.deck.title,
        "question": card.question,
        "answer": card.answer,
        "context": card.context or "",
        "direction": direction,
        "direction_label": direction_label,
        "prompt_text": prompt_text,
        "correct_option": correct_option,
        "options": options,
    }


def build_translation_test_items(user, selected_cards):
    pool_cards = list(
        Card.objects
        .filter(deck__owner=user)
        .select_related("deck")
        .exclude(question__exact="")
        .exclude(answer__exact="")
    )

    items = []

    for card in selected_cards:
        directions = ["forward", "reverse"]
        random.shuffle(directions)

        built_item = None

        for direction in directions:
            try:
                built_item = _build_item_for_direction(
                    card=card,
                    pool_cards=pool_cards,
                    direction=direction,
                )
                break
            except ValueError:
                continue

        if built_item is None:
            raise ValueError(
                f'Could not build enough answer options for card "{card.question}".'
            )

        items.append(built_item)

    return items


def is_correct_translation_test_answer(selected_answer, correct_answer):
    return normalize_test_option(selected_answer) == normalize_test_option(correct_answer)