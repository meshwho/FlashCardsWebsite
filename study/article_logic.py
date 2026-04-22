ARTICLES = ("der", "die", "das")


def normalize_text(text: str) -> str:
    return (text or "").strip().lower()


def split_article_and_word(question_text: str):
    """
    Example:
    'das Haus' -> ('das', 'Haus')
    'der Tisch' -> ('der', 'Tisch')
    """
    text = (question_text or "").strip()
    if not text:
        return "", ""

    parts = text.split(" ", 1)
    if len(parts) == 1:
        return "", parts[0]

    article = parts[0].strip().lower()
    word = parts[1].strip()

    if article in ARTICLES:
        return article, word

    return "", text


def has_supported_article(question_text: str) -> bool:
    article, _word = split_article_and_word(question_text)
    return article in ARTICLES


def is_correct_article_choice(question_text: str, chosen_article: str) -> bool:
    article, _word = split_article_and_word(question_text)
    return article == normalize_text(chosen_article)