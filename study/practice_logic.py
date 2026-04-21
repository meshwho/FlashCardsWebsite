from .review_logic import (
    MAX_HINTS,
    build_hint_mask,
    get_rating_from_result,
    is_correct_answer,
)


def get_prompt_and_expected(card, direction):
    if direction == "reverse":
        return {
            "prompt": card.answer,
            "expected": card.question,
            "direction_label": "Native → Foreign",
            "expected_side": "question",
        }

    return {
        "prompt": card.question,
        "expected": card.answer,
        "direction_label": "Foreign → Native",
        "expected_side": "answer",
    }


def get_typing_result(expected_text, user_answer, hints_used, dont_know=False):
    if dont_know:
        return {
            "is_correct": False,
            "rating_value": 1,
            "rating_label": "Again",
        }

    correct = is_correct_answer(user_answer, expected_text)

    if not correct:
        return {
            "is_correct": False,
            "rating_value": None,
            "rating_label": None,
        }

    rating_value = get_rating_from_result(hints_used, knows_answer=True)

    rating_map = {
        1: "Again",
        2: "Hard",
        3: "Good",
        4: "Easy",
    }

    return {
        "is_correct": True,
        "rating_value": rating_value,
        "rating_label": rating_map[rating_value],
    }


def get_hint_text(expected_text, hints_used, has_article=False):
    return build_hint_mask(expected_text, hints_used, has_article=has_article)

__all__ = [
    "MAX_HINTS",
    "get_prompt_and_expected",
    "get_typing_result",
    "get_hint_text",
]