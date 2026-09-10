import re
import unicodedata

# Obvious profanity. The filter also catches common obfuscation such as * / spaces / digits.
PROFANITY = {
    "блядь", "блять", "бля", "бляд", "блядина", "бляди",
    "ебать", "ебал", "ебаный", "ебаный", "ебануто", "ебанул",
    "ебись", "ебло", "еблан", "ебатьс", "заебал", "заебись",
    "заебло", "выеб", "наеб", "поеб", "отъеб", "отъебись",
    "пизда", "пиздец", "пизде", "пизду", "пизд", "пиздануть",
    "хуй", "хуя", "хуйн", "хуесос", "хуесос", "нахуй", "нихуя",
    "охуеть", "охуел", "охуенно", "охуевший",
    "мудак", "мудач", "долбоеб", "долбаеб", "долбоёб", "уебок", "уёбок",
    "шлюха", "шлюш", "сучка", "сука", "сучар",
    "говно", "говнюк", "дерьмо", "дрянь",
}

# Words/phrases that are strong indicators of unsolicited advertising or spam.
SPAM_PHRASES = (
    "заработок от",
    "заработок в день",
    "заработок без вложений",
    "доход от",
    "доход в день",
    "легкий заработок",
    "лёгкий заработок",
    "быстрый заработок",
    "пассивный доход",
    "подработка",
    "требуются мужчины",
    "требуются женщины",
    "нужны мужчины",
    "нужны женщины",
    "ищем сотрудников",
    "набираем сотрудников",
    "вакансия",
    "вакансии",
    "работа для",
    "пиши в лс",
    "пишите в лс",
    "пиши в личку",
    "пишите в личку",
    "в личку",
    "в лс",
    "ставки",
    "казино",
    "букмекер",
    "бонус за регистрацию",
    "регистрируйся",
    "зарегистрируйся",
    "забери приз",
    "вы выиграли",
    "вы выиграли приз",
)

URL_RE = re.compile(
    r"(?i)(?:https?://|www\.|t\.me/|telegram\.me/|tg://|wa\.me/|mailto:)\S+"
)
# Bare domains, including common Cyrillic/Latin TLDs, without requiring http://.
BARE_DOMAIN_RE = re.compile(
    r"(?i)(?<![@\w])(?:[a-zа-я0-9](?:[a-zа-я0-9-]{0,61}[a-zа-я0-9])?\.)+(?:ru|рф|com|net|org|info|biz|me|cc|site|online|shop|store|pro|top|xyz|io|co|su)(?:/\S*)?"
)


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "").lower()
    replacements = str.maketrans({
        "0": "о", "1": "и", "3": "з", "4": "ч", "5": "с",
        "6": "б", "7": "т", "8": "в", "9": "д",
        "@": "а", "$": "с", "!": "и",
    })
    text = text.translate(replacements)
    # Cyrillic/Latin lookalikes.
    text = text.translate(str.maketrans({
        "a": "а", "e": "е", "o": "о", "p": "р", "c": "с",
        "x": "х", "y": "у", "k": "к", "m": "м", "t": "т",
    }))
    return text


def compact(text: str) -> str:
    # Keep only letters/digits. This catches variants like "б л я т ь".
    return re.sub(r"[^a-zа-яё0-9]", "", normalize(text))


def contains_link(text: str) -> bool:
    if not text:
        return False
    return bool(URL_RE.search(text) or BARE_DOMAIN_RE.search(text))


def contains_profanity(text: str) -> bool:
    if not text:
        return False
    normalized = normalize(text)
    compacted = compact(text)
    padded = f" {re.sub(r"[^a-zа-яё0-9]+", " ", normalized)} "

    for word in PROFANITY:
        # Exact-ish token check catches normal words; compact check catches spacing/symbol obfuscation.
        if re.search(rf"(?<![а-яёa-z]){re.escape(word)}(?![а-яёa-z])", padded):
            return True
        if len(word) >= 4 and word in compacted:
            return True
    return False


def looks_like_spam(text: str) -> bool:
    if not text:
        return False
    normalized = re.sub(r"\s+", " ", normalize(text)).strip()
    if any(phrase in normalized for phrase in SPAM_PHRASES):
        return True

    # Strong combination: employment/earning language + a contact invitation.
    job = re.search(r"\b(работа|подработка|ваканс\w*|заработ\w*|доход)\b", normalized)
    contact = re.search(r"\b(лс|личку|личные сообщения|пишите|пиши|звоните|звони)\b", normalized)
    if job and contact:
        return True

    # Excessive shouting + promotional markers.
    letters = re.findall(r"[а-яёa-z]", normalized)
    if len(letters) >= 12:
        upper_ratio = sum(1 for ch in text if ch.isalpha() and ch.isupper()) / max(1, sum(1 for ch in text if ch.isalpha()))
        if upper_ratio >= 0.75 and any(x in normalized for x in ("акция", "заработ", "приз", "скидка", "казино", "ставк")):
            return True
    return False


def classify(text: str) -> str | None:
    if contains_link(text):
        return "link"
    if contains_profanity(text):
        return "profanity"
    if looks_like_spam(text):
        return "spam"
    return None
