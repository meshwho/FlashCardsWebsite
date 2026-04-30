import math
import re


MAX_HINTS = 3


def normalize_answer(text: str) -> str:
    text = (text or "").strip().lower()
    text = re.sub(r"\s+", " ", text)
    return text


def strip_article(text: str) -> str:
    """
    Remove the first word from the answer.

    Example:
    'der Tisch' -> 'tisch'

    This is used only for hint generation when has_article=True.
    It does not change the real stored answer.
    """
    text = normalize_answer(text)
    parts = text.split(" ", 1)

    if len(parts) == 2:
        return parts[1].strip()

    return text


def get_accepted_answers(answer_text: str) -> list[str]:
    parts = [normalize_answer(part) for part in (answer_text or "").split(",")]
    return [part for part in parts if part]


def is_correct_answer(user_input: str, answer_text: str) -> bool:
    normalized_input = normalize_answer(user_input)
    accepted_answers = get_accepted_answers(answer_text)
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


def _count_alpha_chars(text: str) -> int:
    return sum(1 for ch in text if ch.isalpha())


def _get_revealed_alpha_count(text: str, hints_used: int) -> int:
    """
    Split the alphabetic part of the answer into 4 progressive parts.

    hints_used = 0 -> reveal 0/4
    hints_used = 1 -> reveal 1/4
    hints_used = 2 -> reveal 2/4
    hints_used = 3 -> reveal 3/4

    We use ceil() so short words still reveal something useful.
    Example:
    'Haus' has 4 letters:
      1 hint  -> 1 letter
      2 hints -> 2 letters
      3 hints -> 3 letters

    'Auto' has 4 letters:
      1 hint  -> 1 letter
      2 hints -> 2 letters
      3 hints -> 3 letters

    'Universität' has 11 letters:
      1 hint  -> 3 letters
      2 hints -> 6 letters
      3 hints -> 9 letters
    """
    hints_used = max(0, min(hints_used, MAX_HINTS))

    if hints_used == 0:
        return 0

    alpha_count = _count_alpha_chars(text)

    if alpha_count <= 0:
        return 0

    return min(alpha_count, math.ceil(alpha_count * hints_used / 4))


def build_hint_mask(answer_text: str, hints_used: int, has_article: bool = False) -> str:
    """
    Reveal progressively larger parts of the first accepted answer.

    The answer is split into 4 equal logical parts:
    - 1 hint  -> reveal first 1/4
    - 2 hints -> reveal first 2/4
    - 3 hints -> reveal first 3/4

    If has_article=True, the first word is skipped only for hint generation.
    Example:
    answer = 'der Tisch', has_article=True
    hint is built from 'tisch', not from 'der tisch'.

    Non-letter characters are preserved but do not count as letters.
    """
    primary = get_primary_answer(answer_text, has_article=has_article)

    if not primary:
        return ""

    reveal_letters = _get_revealed_alpha_count(primary, hints_used)

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