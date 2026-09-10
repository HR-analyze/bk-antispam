import re
import unicodedata

PROFANITY_ROOTS = {
    "бляд", "блят", "еб", "выеб", "въеб", "заеб", "хуйн", "хуес",
    "хуеп", "хует", "хуят", "херн", "хер", "пизд", "пидор", "пидар",
    "пидорас", "петух", "петушар", "говн", "дерьм", "ссан", "шлюх",
    "шалав", "манд", "уеб", "уёб", "долбоеб", "долбоёб", "мудак",
    "мудил", "ублюд", "сук", "жоп",
}

SPAM_ROOTS = {
    "заработок", "заработа", "инвестиц", "казино", "ставк", "крипт",
    "наркотик", "наркот", "спайс", "мефедрон",
    "порн", "проститут", "эскорт", "секс",
}

NEGATIVE_PHRASES = {
    "обслуживание ужасное", "обслуживание ужасно", "ужасное обслуживание",
    "ужасный сервис", "ужасное место", "херня а не место", "говно а не",
    "скам проект", "скам-проект", "кто хочет денег", "легкий досуг",
    "лёгкий досуг", "легкий секс", "лёгкий секс",
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
    text = text.translate(replacements)
    return re.sub(r"[^а-яё]+", "", text)


def normalize_spaced(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "").casefold()
    text = re.sub(r"[^а-яёa-z0-9@]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def contains_link(text: str) -> bool:
    if not text:
        return False
    return bool(re.search(r"(?:https?://|www\.|t\.me/|telegram\.me/)", text, re.I))


def classify(text: str):
    normalized = normalize_text(text)
    spaced = normalize_spaced(text)

    for root in PROFANITY_ROOTS:
        if normalize_text(root) in normalized:
            return "profanity"

    for phrase in NEGATIVE_PHRASES:
        if normalize_spaced(phrase) in spaced:
            return "negative"

    for root in SPAM_ROOTS:
        if normalize_text(root) in normalized:
            return "spam"

    return None
