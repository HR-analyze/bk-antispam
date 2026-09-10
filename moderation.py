import re
import unicodedata

# Common profanity / abusive terms. Keep this list explicit so the filter is
# predictable and easy to maintain.
PROFANITY_WORDS = {
    "блядь", "блять", "бля", "ебать", "ебан", "ебаный", "ебаная",
    "еблан", "еблать", "ебло", "еблo", "выеб", "въеб", "заеб",
    "заебал", "заебись", "хуйн", "хуйню", "хуесос", "хуеплет",
    "хуйней", "хуйня", "хуня", "хуета", "хуетой", "хуятина", "хуй",
    "пизд", "пиздец", "пизда", "пизду", "пидор", "пидар", "пидорас",
    "петух", "петушар", "говно", "гавно", "дерьмо", "ссаный", "ссы",
    "шлюха", "шалава", "манда", "манд", "уеб", "уёб", "долбоеб",
    "долбоёб", "мудак", "мудила", "ублюдок", "сука", "сучка",
}

SPAM_WORDS = {
    "заработок", "заработать", "легкий заработок", "лёгкий заработок",
    "быстрый заработок", "легкие деньги", "лёгкие деньги", "легко и просто",
    "инвестиции", "инвестируй", "доход без вложений", "пассивный доход",
    "казино", "ставки", "ставка", "крипта", "криптовалюта",
    "наркота", "спайс", "мефедрон",
}


def normalize_text(text: str) -> str:
    """Normalize Cyrillic/Latin lookalikes and punctuation used to evade filters."""
    text = unicodedata.normalize("NFKC", text or "").casefold()
    replacements = str.maketrans({
        "a": "а", "b": "в", "c": "с", "e": "е", "k": "к",
        "m": "м", "o": "о", "p": "р", "t": "т", "x": "х",
        "y": "у", "$": "с", "@": "а", "0": "о", "3": "з",
        "4": "ч", "6": "б", "1": "и",
    })
    text = text.translate(replacements)
    # Remove separators between letters: х-у-й -> хуй, п и з д а -> пизда.
    text = re.sub(r"[\W_]+", "", text, flags=re.UNICODE)
    return text


def contains_link(text: str) -> bool:
    if not text:
        return False
    return bool(re.search(r"(?:https?://|www\.|t\.me/|telegram\.me/|@[a-zA-Z0-9_]{4,})", text, re.I))


def _contains_term(normalized: str, term: str) -> bool:
    term_normalized = normalize_text(term)
    return bool(term_normalized and term_normalized in normalized)


def classify(text: str):
    """Return a moderation reason or None."""
    normalized = normalize_text(text)

    for word in PROFANITY_WORDS:
        if _contains_term(normalized, word):
            return "profanity"

    # Match phrases against a lightly normalized version that preserves spaces.
    spaced = unicodedata.normalize("NFKC", text or "").casefold()
    spaced = re.sub(r"[^\w\s]+", " ", spaced, flags=re.UNICODE)
    spaced = re.sub(r"\s+", " ", spaced).strip()
    for phrase in SPAM_WORDS:
        if phrase in spaced or _contains_term(normalized, phrase):
            return "spam"

    return None
