import re
import unicodedata

PROFANITY_WORDS = {
    "бляд", "бля", "еб", "выеб", "въеб", "заеб", "хуйн", "хуй",
    "хуесос", "хуеплет", "хует", "хуят", "пизд", "пидор", "пидар",
    "пидорас", "петух", "петушар", "говн", "дерьм", "ссан", "ссы",
    "шлюх", "шалав", "манд", "уеб", "уёб", "долбоеб", "долбоёб",
    "мудак", "мудил", "ублюд", "сук", "жопа",
}

SPAM_WORDS = {
    "заработок", "заработать", "легкий заработок", "лёгкий заработок",
    "быстрый заработок", "легкие деньги", "лёгкие деньги", "легко и просто",
    "инвестиции", "инвестируй", "доход без вложений", "пассивный доход",
    "казино", "ставки", "ставка", "крипта", "криптовалюта",
    "наркот", "наркотики", "наркота", "спайс", "мефедрон",
}


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "").casefold()
    replacements = str.maketrans({
        "a": "а", "b": "в", "c": "с", "e": "е", "k": "к",
        "m": "м", "o": "о", "p": "р", "t": "т", "x": "х",
        "y": "у", "$": "с", "@": "а", "0": "о", "3": "з",
        "4": "ч", "6": "б", "1": "и",
    })
    text = text.translate(replacements)
    return re.sub(r"[\W_]+", "", text, flags=re.UNICODE)


def contains_link(text: str) -> bool:
    if not text:
        return False
    # @username is a normal Telegram mention and must NOT be treated as a link.
    return bool(re.search(r"(?:https?://|www\.|t\.me/|telegram\.me/)", text, re.I))


def _contains_term(normalized: str, term: str) -> bool:
    term_normalized = normalize_text(term)
    return bool(term_normalized and term_normalized in normalized)


def classify(text: str):
    normalized = normalize_text(text)

    for word in PROFANITY_WORDS:
        if _contains_term(normalized, word):
            return "profanity"

    spaced = unicodedata.normalize("NFKC", text or "").casefold()
    spaced = re.sub(r"[^\w\s]+", " ", spaced, flags=re.UNICODE)
    spaced = re.sub(r"\s+", " ", spaced).strip()
    for phrase in SPAM_WORDS:
        if phrase in spaced or _contains_term(normalized, phrase):
            return "spam"

    return None
