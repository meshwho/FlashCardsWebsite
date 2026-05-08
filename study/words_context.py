import json
import random
import re

from .card_duplicates import normalize_card_text
from .models import Card


WORDS_CONTEXT_SESSION_KEY = "words_context_session"

MIN_WORDS_IN_CONTEXT = 4
MAX_WORDS_IN_CONTEXT = 20

WORDS_CONTEXT_LEVELS = [
    "A1.1",
    "A1.2",
    "A2.1",
    "A2.2",
    "B1.1",
    "B1.2",
    "B2.1",
    "B2.2",
]

DEFAULT_WORDS_CONTEXT_LEVEL = "A2.2"


def normalize_option_text(value):
    return " ".join((value or "").strip().lower().split())


def choose_random_cards_for_context(user, count):
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
            normalize_card_text(card.answer),
        )

        if key in seen:
            continue

        seen.add(key)
        selected.append(card)

        if len(selected) >= count:
            break

    return selected


def serialize_card_for_context(card):
    return {
        "id": str(card.id),
        "word": card.question,
        "translation": card.answer,
        "context": card.context or "",
        "deck": card.deck.title,
    }


def build_words_context_prompt(selected_cards, text_level):
    lines = []

    lines.append("Ты — преподаватель немецкого языка и автор интересных учебных текстов.")
    lines.append("")
    lines.append(f"Создай один связный, интересный и естественный немецкий текст уровня {text_level}.")
    lines.append("Текст должен быть не сухим набором предложений, а маленькой историей, сценой из жизни или живой ситуацией.")
    lines.append("")
    lines.append("Задача:")
    lines.append("- Используй все немецкие слова/выражения из списка.")
    lines.append("- Каждое слово должно быть использовано в тексте естественно.")
    lines.append("- Для каждого слова подготовь одно упражнение с пропуском.")
    lines.append("- В упражнении замени только это слово или выражение на ____.")
    lines.append("- Не выделяй слова жирным.")
    lines.append("- Не добавляй markdown.")
    lines.append("")
    lines.append("Требования к уровню:")
    lines.append(f"- Уровень текста должен соответствовать именно {text_level}.")
    lines.append("- Не усложняй грамматику выше выбранного уровня.")
    lines.append("- Делай текст живым и интересным, но понятным для изучающего немецкий.")
    lines.append("- Если уровень A1–A2, используй короткие предложения и простую лексику.")
    lines.append("- Если уровень B1–B2, можно делать текст немного более насыщенным и естественным.")
    lines.append("")
    lines.append("Очень важно:")
    lines.append("- Если у слова есть context, обязательно учитывай его при создании текста.")
    lines.append("- Если слово с артиклем, используй его грамматически правильно в предложении.")
    lines.append("- correct_option должен быть точным вариантом, который нужно вставить вместо пропуска.")
    lines.append("- correct_option должен совпадать с формой слова в предложении, а не обязательно с исходной формой из списка.")
    lines.append("- Например, если в тексте нужно 'Universität', correct_option должен быть 'Universität', а не 'die Universität'.")
    lines.append("- В конце добавь короткий summary на русском языке: о чём был текст и какие слова потренированы.")
    lines.append("")
    lines.append("Верни ответ строго в JSON, без markdown, без ```json, без комментариев.")
    lines.append("")
    lines.append("Формат JSON:")
    lines.append("{")
    lines.append('  "title": "Название текста",')
    lines.append(f'  "level": "{text_level}",')
    lines.append('  "full_text": "Полный немецкий текст без пропусков.",')
    lines.append('  "summary": "Короткое summary на русском языке.",')
    lines.append('  "items": [')
    lines.append("    {")
    lines.append('      "card_id": "id карточки из списка",')
    lines.append('      "word": "исходное немецкое слово",')
    lines.append('      "translation": "перевод",')
    lines.append('      "context": "context или пустая строка",')
    lines.append('      "sentence": "предложение из текста без пропуска",')
    lines.append('      "blank_text": "кусочек текста или предложение с ____ вместо слова",')
    lines.append('      "correct_option": "точный ответ для пропуска"')
    lines.append("    }")
    lines.append("  ]")
    lines.append("}")
    lines.append("")
    lines.append("Слова:")

    for index, card in enumerate(selected_cards, start=1):
        lines.append("")
        lines.append(f"{index}.")
        lines.append(f'card_id: {card["id"]}')
        lines.append(f'word: {card["word"]}')
        lines.append(f'translation: {card["translation"]}')
        lines.append(f'context: {card["context"] or "—"}')
        lines.append(f'deck: {card["deck"]}')

    return "\n".join(lines)


def extract_json_from_ai_response(raw_text):
    text = (raw_text or "").strip()

    if not text:
        raise ValueError("AI response is empty.")

    text = re.sub(r"^```(?:json)?", "", text.strip(), flags=re.IGNORECASE).strip()
    text = re.sub(r"```$", "", text.strip()).strip()

    first_brace = text.find("{")
    last_brace = text.rfind("}")

    if first_brace == -1 or last_brace == -1 or last_brace <= first_brace:
        raise ValueError("Could not find JSON object in AI response.")

    json_text = text[first_brace:last_brace + 1]

    try:
        return json.loads(json_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON: {exc}") from exc


def validate_words_context_payload(payload, selected_cards):
    if not isinstance(payload, dict):
        raise ValueError("AI response must be a JSON object.")

    title = (payload.get("title") or "").strip()
    level = (payload.get("level") or "").strip()
    full_text = (payload.get("full_text") or "").strip()
    summary = (payload.get("summary") or "").strip()
    items = payload.get("items")

    if not full_text:
        raise ValueError("JSON field full_text is required.")

    if not summary:
        raise ValueError("JSON field summary is required.")

    if not isinstance(items, list) or not items:
        raise ValueError("JSON field items must be a non-empty list.")

    selected_ids = {card["id"] for card in selected_cards}
    cleaned_items = []

    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Item {index} must be an object.")

        card_id = str(item.get("card_id") or "").strip()
        word = (item.get("word") or "").strip()
        translation = (item.get("translation") or "").strip()
        context = (item.get("context") or "").strip()
        sentence = (item.get("sentence") or "").strip()
        blank_text = (item.get("blank_text") or "").strip()
        correct_option = (item.get("correct_option") or "").strip()

        if card_id not in selected_ids:
            raise ValueError(f"Item {index} has unknown card_id: {card_id}")

        if "____" not in blank_text:
            raise ValueError(f"Item {index} blank_text must contain ____.")

        if not correct_option:
            raise ValueError(f"Item {index} correct_option is required.")

        cleaned_items.append(
            {
                "card_id": card_id,
                "word": word,
                "translation": translation,
                "context": context,
                "sentence": sentence,
                "blank_text": blank_text,
                "correct_option": correct_option,
                "attempted_options": [],
                "options": [],
            }
        )

    return {
        "title": title or "Words in context",
        "level": level or "",
        "full_text": full_text,
        "summary": summary,
        "items": cleaned_items,
    }


def build_options_for_item(items, current_index):
    current_item = items[current_index]

    if current_item.get("options"):
        return current_item["options"]

    correct = current_item["correct_option"]

    distractors = []

    for item in items:
        option = item.get("correct_option", "").strip()

        if not option:
            continue

        if normalize_option_text(option) == normalize_option_text(correct):
            continue

        if option not in distractors:
            distractors.append(option)

    random.shuffle(distractors)

    options = [correct] + distractors[:3]
    random.shuffle(options)

    current_item["options"] = options

    return options


def is_correct_context_answer(selected_answer, correct_answer):
    return normalize_option_text(selected_answer) == normalize_option_text(correct_answer)