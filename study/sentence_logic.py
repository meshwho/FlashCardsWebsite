def sentence_count_for_rating(rating_value: int) -> int:
    """
    4 = Easy  -> 0
    3 = Good  -> 1
    2 = Hard  -> 2
    1 = Again -> 3
    """
    if rating_value == 4:
        return 0
    if rating_value == 3:
        return 1
    if rating_value == 2:
        return 2
    return 3


def should_require_sentences(
    *,
    had_wrong_attempt: bool,
    had_hint: bool,
    rating_value: int,
    feature_enabled: bool = True,
) -> bool:
    if not feature_enabled:
        return False

    if not (had_wrong_attempt or had_hint):
        return False

    return sentence_count_for_rating(rating_value) > 0