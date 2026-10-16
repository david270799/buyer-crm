"""Product categories (the owner, 16.10.2026): set by Gemini from the photo,
changeable by the admin. «Часы» matters: watches have no size to check and
travel with their own delivery price."""

CATEGORIES: dict[str, str] = {
    "shoes": "Обувь",
    "clothes": "Одежда",
    "watch": "Часы",
    "bag": "Сумки",
    "accessory": "Аксессуары",
    "other": "Другое",
}

# Gemini answers the category in Russian, one or two words.
_WORDS = (
    ("watch", ("час", "watch")),
    ("shoes", ("кросс", "кед", "ботин", "обув", "туфл", "сапог", "сандал", "шлёп", "шлеп", "слип")),
    ("bag", ("сумк", "рюкзак", "кошел", "клатч")),
    (
        "clothes",
        (
            "одежд",
            "куртк",
            "брюк",
            "футбол",
            "худи",
            "толстов",
            "джинс",
            "свитер",
            "шорт",
            "пальто",
            "пухов",
            "кофт",
            "рубаш",
            "плать",
            "юбк",
            "костюм",
            "жилет",
            "ветровк",
        ),
    ),
    ("accessory", ("аксессуар", "кепк", "шапк", "ремен", "ремн", "очк", "носк", "перчат", "шарф")),
)


def category_from_text(text: str | None) -> str | None:
    """Gemini's word ("кроссовки", "куртка") → a category code, or None if unclear."""
    word = (text or "").strip().casefold()
    if not word:
        return None
    for code, stems in _WORDS:
        if any(stem in word for stem in stems):
            return code
    return None


def check_category(value: str | None) -> str | None:
    from crm.domain.errors import ValidationError

    if value is None or value == "":
        return None
    if value not in CATEGORIES:
        raise ValidationError(f"Неизвестная категория: {value}")
    return value
