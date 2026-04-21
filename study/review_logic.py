import re


MAX_HINTS = 3


def normalize_answer(text: str) -> str:
    text = (text or "").strip().lower()
    text = re.sub(r"\s+", " ", text)
    return text


def strip_article(text: str) -> str:
    """
    Remove the first word from the answer.
    Example: 'der Tisch' -> 'Tisch'
    """
    text = normalize_answer(text)
    parts = text.split(" ", 1)

    if len(parts) == 2:
        return parts[1].strip()

    return text


def get_accepted_answers(answer_text: str, has_article: bool = False) -> list[str]:
    parts = [normalize_answer(part) for part in (answer_text or "").split(",")]
    parts = [part for part in parts if part]

    accepted = set(parts)

    if has_article:
        for part in parts:
            accepted.add(strip_article(part))

    return list(accepted)


def is_correct_answer(user_input: str, answer_text: str, has_article: bool = False) -> bool:
    normalized_input = normalize_answer(user_input)
    accepted_answers = get_accepted_answers(answer_text, has_article=has_article)
    return normalized_input in accepted_answers


def get_primary_answer(answer_text: str, has_article: bool = False) -> str:
    answers = [normalize_answer(part) for part in (answer_text or "").split(",")]
    answers = [part for part in answers if part]

    if not answers:
        return ""

    primary = answers[0]

    if has_article:
        return strip_article(primary)

    return primary


def build_hint_mask(answer_text: str, hints_used: int, has_article: bool = False) -> str:
    """
    Reveal progressively more letters from the first accepted answer.
    If has_article=True, the first word is skipped for hint generation.
    """
    primary = get_primary_answer(answer_text, has_article=has_article)
    if not primary:
        return ""

    hints_used = max(0, min(hints_used, MAX_HINTS))

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
    if not knows_answer:
        return 1  # Again

    if hints_used <= 0:
        return 4  # Easy

    if hints_used == 1:
        return 3  # Good

    return 2  # Hard