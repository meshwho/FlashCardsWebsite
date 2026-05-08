import json
import random
import re

from .card_duplicates import normalize_card_text
from .models import Card


WORDS_CONTEXT_SESSION_KEY = "words_context_session"
EXTRA_DISTRACTOR_OPTIONS_COUNT = 24

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


def build_words_context_prompt(selected_cards, distractor_cards, text_level):
    lines = []

    lines.append("Создай интересный связный немецкий учебный текст.")
    lines.append("")
    lines.append(f"Уровень текста: {text_level}.")
    lines.append("")
    lines.append("MAIN WORDS нужно обязательно использовать в тексте.")
    lines.append("DISTRACTOR WORDS используй только как неправильные варианты ответа.")
    lines.append("")
    lines.append("Требования к тексту:")
    lines.append("- Это должен быть один связный текст, а не набор отдельных предложений.")
    lines.append("- У текста должен быть простой сюжет: ситуация, проблема, действие, небольшой финал.")
    lines.append("- Текст должен быть естественным и интересным для чтения.")
    lines.append("- Можно писать столько предложений, сколько нужно для нормального текста.")
    lines.append("- Грамматика и лексика должны соответствовать указанному уровню.")
    lines.append("")
    lines.append("Требования к упражнениям:")
    lines.append("- Для каждого MAIN WORD создай одно задание с пропуском.")
    lines.append("- blank_text должен содержать 2–3 связанные предложения из текста.")
    lines.append("- В blank_text должен быть ровно один пропуск: ____")
    lines.append("- Для каждого задания дай ровно 4 варианта ответа.")
    lines.append("- Только один вариант должен быть правильным.")
    lines.append("- Остальные варианты должны быть грамматически возможными, но неправильными по смыслу.")
    lines.append("- Если слово с артиклем, вариант ответа должен быть с артиклем.")
    lines.append("- Если нужен другой падеж, измени артикль и слово правильно.")
    lines.append("- Все варианты в одном задании должны быть в подходящей форме для пропуска.")
    lines.append("- Не допускай дубликатов вариантов.")
    lines.append("")
    lines.append("Верни только валидный JSON.")
    lines.append("Не используй markdown.")
    lines.append("Не используй ```json.")
    lines.append("Используй только обычные двойные кавычки: \"")
    lines.append("Ответ должен начинаться с { и заканчиваться }.")
    lines.append("")
    lines.append("Формат JSON:")
    lines.append("{")
    lines.append('  "title": "Название текста",')
    lines.append(f'  "level": "{text_level}",')
    lines.append('  "full_text": "Полный немецкий текст без пропусков.",')
    lines.append('  "summary": "Короткое summary на русском языке.",')
    lines.append('  "items": [')
    lines.append("    {")
    lines.append('      "card_id": "id основной карточки",')
    lines.append('      "word": "исходное слово из MAIN WORDS",')
    lines.append('      "translation": "перевод",')
    lines.append('      "context": "context или пустая строка",')
    lines.append('      "sentence": "полное предложение без пропуска",')
    lines.append('      "blank_text": "2–3 предложения с одним пропуском ____",')
    lines.append('      "correct_option": "правильный вариант",')
    lines.append('      "options": ["вариант 1", "вариант 2", "вариант 3", "вариант 4"]')
    lines.append("    }")
    lines.append("  ]")
    lines.append("}")
    lines.append("")
    lines.append("MAIN WORDS:")

    for index, card in enumerate(selected_cards, start=1):
        lines.append("")
        lines.append(f"{index}.")
        lines.append(f'card_id: {card["id"]}')
        lines.append(f'word: {card["word"]}')
        lines.append(f'translation: {card["translation"]}')
        lines.append(f'context: {card["context"] or ""}')

    lines.append("")
    lines.append("DISTRACTOR WORDS:")

    for index, card in enumerate(distractor_cards, start=1):
        lines.append("")
        lines.append(f"{index}.")
        lines.append(f'word: {card["word"]}')
        lines.append(f'translation: {card["translation"]}')
        lines.append(f'context: {card["context"] or ""}')

    return "\n".join(lines)


def extract_json_from_ai_response(raw_text):
    text = (raw_text or "").strip()

    if not text:
        raise ValueError("AI response is empty.")

    # Remove markdown code fences if ChatGPT returns them anyway.
    text = re.sub(r"^```(?:json)?", "", text.strip(), flags=re.IGNORECASE).strip()
    text = re.sub(r"```$", "", text.strip()).strip()

    # ChatGPT or mobile keyboards may sometimes produce typographic quotes.
    # JSON requires normal ASCII double quotes: "
    text = (
        text
        .replace("“", '"')
        .replace("”", '"')
        .replace("„", '"')
        .replace("«", '"')
        .replace("»", '"')
        .replace("‘", "'")
        .replace("’", "'")
        .replace("\u00a0", " ")
    )

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
        options = item.get("options")

        if card_id not in selected_ids:
            raise ValueError(f"Item {index} has unknown card_id: {card_id}")

        if "____" not in blank_text:
            raise ValueError(f"Item {index} blank_text must contain ____.")

        if not correct_option:
            raise ValueError(f"Item {index} correct_option is required.")

        if not isinstance(options, list):
            raise ValueError(f"Item {index} options must be a list.")

        cleaned_options = []

        for option in options:
            option = (str(option) if option is not None else "").strip()

            if option:
                cleaned_options.append(option)

        if len(cleaned_options) != 4:
            raise ValueError(f"Item {index} options must contain exactly 4 options.")

        if not any(
            normalize_option_text(option) == normalize_option_text(correct_option)
            for option in cleaned_options
        ):
            raise ValueError(f"Item {index} options must include correct_option.")

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
                "options": cleaned_options,
            }
        )

    return {
        "title": title or "Words in context",
        "level": level or "",
        "full_text": full_text,
        "summary": summary,
        "items": cleaned_items,
    }


def build_options_for_item(items, current_index, extra_options=None):
    current_item = items[current_index]

    ai_options = current_item.get("options") or []

    if ai_options:
        return ai_options

    # Fallback на старую логику, если ИИ почему-то не вернул options.
    correct = (current_item["correct_option"] or "").strip()
    current_item["correct_option"] = correct

    extra_options = extra_options or []

    distractors = []
    seen = set()

    def add_distractor(option):
        option = (option or "").strip()

        if not option:
            return

        option_key = normalize_option_text(option)
        correct_key = normalize_option_text(correct)

        if not option_key:
            return

        if option_key == correct_key:
            return

        if option_key in seen:
            return

        seen.add(option_key)
        distractors.append(option)

    for item in items:
        add_distractor(item.get("correct_option", ""))

    for option in extra_options:
        add_distractor(option)

    random.shuffle(distractors)

    options = [correct] + distractors[:3]
    random.shuffle(options)

    current_item["options"] = options

    return options


def is_correct_context_answer(selected_answer, correct_answer):
    return normalize_option_text(selected_answer) == normalize_option_text(correct_answer)

def choose_random_distractor_cards_for_context(user, excluded_card_ids, count=EXTRA_DISTRACTOR_OPTIONS_COUNT):
    cards = list(
        Card.objects
        .filter(deck__owner=user)
        .select_related("deck")
        .exclude(id__in=excluded_card_ids)
        .exclude(question__exact="")
        .exclude(answer__exact="")
    )

    random.shuffle(cards)

    selected = []
    seen = set()

    for card in cards:
        key = normalize_card_text(card.question)

        if not key or key in seen:
            continue

        seen.add(key)
        selected.append(card)

        if len(selected) >= count:
            break

    return selected


def serialize_distractor_options(cards):
    options = []
    seen = set()

    for card in cards:
        option = (card.question or "").strip()
        key = normalize_option_text(option)

        if not option or not key or key in seen:
            continue

        seen.add(key)
        options.append(option)

    return options