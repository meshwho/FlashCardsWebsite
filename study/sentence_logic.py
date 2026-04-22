RATING_TO_SENTENCE_COUNT = {
    4: 0,  # Easy
    3: 1,  # Good
    2: 2,  # Hard
    1: 3,  # Again
}


def sentence_count_for_rating(rating_value: int) -> int:
    """
    4 = Easy  -> 0
    3 = Good  -> 1
    2 = Hard  -> 2
    1 = Again -> 3
    """
    return RATING_TO_SENTENCE_COUNT.get(rating_value, 3)


def should_require_sentences(
    *,
    had_wrong_attempt: bool,
    had_hint: bool,
    had_dont_know: bool = False,
    rating_value: int,
    feature_enabled: bool = True,
) -> bool:
    if not feature_enabled:
        return False

    had_struggle = had_wrong_attempt or had_hint or had_dont_know

    if not had_struggle:
        return False

    return sentence_count_for_rating(rating_value) > 0
