import re


MAX_HINTS = 3


def normalize_answer(text: str) -> str:
    text = (text or "").strip().lower()
    text = re.sub(r"\s+", " ", text)
    return text


def get_accepted_answers(answer_text: str) -> list[str]:
    parts = [normalize_answer(part) for part in (answer_text or "").split(",")]
    return [part for part in parts if part]


def is_correct_answer(user_input: str, answer_text: str) -> bool:
    normalized_input = normalize_answer(user_input)
    accepted_answers = get_accepted_answers(answer_text)
    return normalized_input in accepted_answers


def get_primary_answer(answer_text: str) -> str:
    answers = get_accepted_answers(answer_text)
    return answers[0] if answers else ""


def build_hint_mask(answer_text: str, hints_used: int) -> str:
    """
    Reveal progressively more letters from the first accepted answer.
    Keeps spaces and punctuation visible.
    """
    primary = get_primary_answer(answer_text)
    if not primary:
        return ""

    hints_used = max(0, min(hints_used, MAX_HINTS))

    # How many letters to reveal for 1/2/3 hints
    reveal_map = {
        0: 0,
        1: 1,
        2: 2,
        3: 3,
    }
    reveal_letters = reveal_map[hints_used]

    result = []
    letters_revealed = 0

    for ch in primary:
        if ch.isalpha():
            if letters_revealed < reveal_letters:
                result.append(ch)
                letters_revealed += 1
            else:
                result.append("_")
        else:
            result.append(ch)

    return " ".join(result)


def get_rating_from_result(hints_used: int, knows_answer: bool) -> int:
    """
    FSRS rating mapping:
    4 = Easy
    3 = Good
    2 = Hard
    1 = Again
    """
    if not knows_answer:
        return 1  # Again

    if hints_used <= 0:
        return 4  # Easy

    if hints_used == 1:
        return 3  # Good

    return 2  # Hard for 2 or 3 hints