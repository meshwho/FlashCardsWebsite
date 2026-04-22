def sentence_count_for_rating(rating_value: int) -> int:
    """
    Rating mapping:
    1 = Again -> 3 sentences
    2 = Hard  -> 2 sentences
    3 = Good  -> 1 sentence
    4 = Easy  -> 0 sentences
    """
    if rating_value == 1:
        return 3
    if rating_value == 2:
        return 2
    if rating_value == 3:
        return 1
    return 0


def should_require_sentences(was_wrong_before_correct: bool, rating_value: int) -> bool:
    if not was_wrong_before_correct:
        return False
    return sentence_count_for_rating(rating_value) > 0