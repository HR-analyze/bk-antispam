import re
import unicodedata

PROFANITY_PATTERNS = [
    r"\bбля(?:дь|ть)?\w*\b", r"\bеб(?:ать|ан|лан|ло|лать)\w*\b",
    r"\b(?:вы|въ|за)еб\w*\b", r"\bхуй\w*\b", r"\bхуйн\w*\b",
    r"\bхуесос\w*\b", r"\bхуеплет\w*\b", r"\bхует\w*\b", r"\bхуят\w*\b",
    r"\bхерн\w*\b", r"\bпизд\w*\b", r"\bпидор\w*\b", r"\bпидар\w*\b",
    r"\bпидорас\w*\b", r"\bпетух\w*\b", r"\bпетушар\w*\b", r"\bговн\w*\b",
    r"\bдерьм\w*\b", r"\bссан\w*\b", r"\bшлюх\w*\b", r"\bшалав\w*\b",
    r"\bманд\w*\b", r"\bуеб\w*\b", r"\bуёб\w*\b", r"\bдолбоеб\w*\b",
    r"\bдолбоёб\w*\b", r"\bмудак\w*\b", r"\bмудил\w*\b", r"\bублюд\w*\b",
    r"\bсук\w*\b", r"\bжоп\w*\b",
]

SPAM_PATTERNS = [
    r"\bзаработ\w*\b", r"\bинвестиц\w*\b", r"\bказино\b", r"\bставк\w*\b",
    r"\bкрипт\w*\b", r"\bнаркот\w*\b", r"\bспайс\w*\b", r"\bмефедрон\w*\b",
    r"\bпорн\w*\b", r"\bпроститут\w*\b", r"\bэскорт\w*\b", r"\bсекс\w*\b",
]

NEGATIVE_PHRASES = {
    "обслуживание ужасное", "обслуживание ужасно", "ужасное обслуживание",
    "ужасный сервис", "ужасное место", "херня а не место", "говно а не",
    "скам проект", "скам-проект", "кто хочет денег", "легкий досуг",
    "лёгкий досуг", "легкий секс", "лёгкий секс",
    "детское порно", "детское порн", "кровь девственницы",
    "child porn", "child pornography", "sexual content involving minors",
}


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "").casefold()
    replacements = str.maketrans({
        "a": "а", "b": "б", "c": "с", "e": "е", "h": "х",
        "i": "и", "k": "к", "m": "м", "n": "н", "o": "о",
        "p": "п", "r": "р", "s": "с", "t": "т", "u": "у",
        "v": "в", "x": "х", "y": "у", "z": "з", "$": "с",
        "0": "о", "1": "и", "3": "з", "4": "ч", "6": "б",
    })
    return text.translate(replacements)


def normalize_spaced(text: str) -> str:
    text = normalize_text(text)
    text = re.sub(r"[^а-яёa-z0-9@]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def contains_link(text: str) -> bool:
    if not text:
        return False
    return bool(re.search(r"(?:https?://|www\.|t\.me/|telegram\.me/)", text, re.I))


def _matches_any(text: str, patterns) -> bool:
    return any(re.search(pattern, text, flags=re.IGNORECASE | re.UNICODE) for pattern in patterns)


def classify(text: str):
    normalized = normalize_text(text)
    spaced = normalize_spaced(text)

    if _matches_any(normalized, PROFANITY_PATTERNS):
        return "profanity"

    for phrase in NEGATIVE_PHRASES:
        if normalize_spaced(phrase) in spaced:
            return "negative"

    if _matches_any(normalized, SPAM_PATTERNS):
        return "spam"

    return None
