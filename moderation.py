import re
import unicodedata


PROFANITY = {
    "блядь", "блять", "бляд", "бля", "блядина", "бляди",
    "ебать", "ебал", "ебан", "ебаный", "ебануто", "ебанул", "ебись", "ебло", "еблан",
    "заеб", "заебал", "заебись", "заебло", "выеб", "наеб", "поеб", "отъеб", "отъебись",
    "пизда", "пиздец", "пизде", "пизду", "пизд", "пиздануть",
    "хуй", "хуя", "хуйн", "хуесос", "нахуй", "нихуя", "охуеть", "охуел", "охуенно", "охуевший",
    "мудак", "мудач", "долбоеб", "долбаеб", "долбоёб", "уебок", "уёбок",
    "шлюха", "шлюш", "сучка", "сука", "сучар", "говно", "говнюк", "дерьмо", "дрянь",
}

SPAM_PHRASES = (
    "заработок от",
    "заработок в день",
    "заработок без вложений",
    "заработок на крипте",
    "легкий заработок",
    "лёгкий заработок",
    "быстрый заработок",
    "пассивный доход",
    "подработка",
    "требуются мужчины",
    "требуются женщины",
    "нужны мужчины",
    "нужны женщины",
    "нужны парни",
    "нужны девушки",
    "ищем сотрудников",
    "набираем сотрудников",
    "требуется персонал",
    "вакансия",
    "вакансии",
    "работа для",
    "ставки на спорт",
    "ставки",
    "букмекер",
    "казино",
    "бонус за регистрацию",
    "регистрируйся",
    "зарегистрируйся",
    "забери приз",
    "вы выиграли",
    "вы выиграли приз",
    "выигрыш",
    "криптовалюта",
    "инвестиции с гарантией",
    "гарантированный доход",
    "интимные услуги",
    "интим за деньги",
    "секс за деньги",
    "секс услуги",
    "эскорт",
    "онлифанс",
    "onlyfans",
}

CONTACT_PHRASES = (
    "пиши в лс",
    "пишите в лс",
    "пиши в личку",
    "пишите в личку",
    "в личку",
    "в лс",
    "личные сообщения",
    "звоните",
    "звони",
    "пишите мне",
    "пиши мне",
)

PROMO_WORDS = (
    "акция",
    "скидка",
    "приз",
    "заработ",
    "доход",
    "казино",
    "ставк",
    "букмекер",
    "ваканс",
    "подработ",
    "знакомств",
    "девушки",
    "мужчины",
    "крипт",
    "инвестиц",
    "эскорт",
    "интим",
    "онлифанс",
    "onlyfans",
)

URL_RE = re.compile(
    r"(?i)(?:https?://|www\.|t\.me/|telegram\.me/|tg://|wa\.me/|viber://|mailto:)\S+"
)

BARE_DOMAIN_RE = re.compile(
    r"(?i)(?<![@\w])(?:[a-zа-я0-9](?:[a-zа-я0-9-]{0,61}[a-zа-я0-9])?\.)+"
    r"(?:ru|рф|com|net|org|info|biz|me|cc|site|online|shop|store|pro|top|xyz|io|co|su|dev|app|link|live)"
    r"(?:/\S*)?"
)

PHONE_RE = re.compile(
    r"(?<!\d)(?:\+?7|8)[\s().-]*\d{3}[\s().-]*\d{3}[\s.-]*\d{2}[\s.-]*\d{2}(?!\d)"
    r"|(?<!\d)\+?\d{10,15}(?!\d)"
)


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "").lower()
    text = text.translate(str.maketrans({
        "0": "о", "1": "и", "3": "з", "4": "ч", "5": "с",
        "6": "б", "7": "т", "8": "в", "9": "д",
        "@": "а", "$": "с", "!": "и",
    }))
    text = text.translate(str.maketrans({
        "a": "а", "e": "е", "o": "о", "p": "р", "c": "с", "x": "х",
        "y": "у", "k": "к", "m": "м", "t": "т",
    }))
    text = re.sub(r"(.)\1{2,}", r"\1\1", text)
    return text


def compact(text: str) -> str:
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
    cleaned = re.sub(r"[^a-zа-яё0-9]+", " ", normalized)
    padded = f" {cleaned} "

    for word in PROFANITY:
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

    # Работа/заработок + призыв к контакту.
    job = re.search(r"\b(работ\w*|ваканс\w*|заработ\w*|доход\w*|подработ\w*)\b", normalized)
    contact = re.search(r"\b(лс|личк\w*|пишите|пиши|звоните|звони)\b", normalized)
    if job and contact:
        return True

    # Знакомства/сексуализированное предложение + контакт.
    dating = re.search(
        r"\b(знакомств\w*|познаком\w*|девуш\w*|парн\w*|мужчин\w*|женщин\w*|эскорт\w*|интим\w*)\b",
        normalized,
    )
    if dating and any(phrase in normalized for phrase in CONTACT_PHRASES):
        return True

    # Финансовый спам: телефон + коммерческий/рекламный признак.
    if PHONE_RE.search(normalized) and any(word in normalized for word in PROMO_WORDS):
        return True

    # Много капса + явный промо-маркер.
    alpha_original = [ch for ch in text if ch.isalpha()]
    if len(alpha_original) >= 15:
        upper_ratio = sum(ch.isupper() for ch in alpha_original) / len(alpha_original)
        if upper_ratio >= 0.80 and any(word in normalized for word in PROMO_WORDS):
            return True

    # Короткий агрессивный рекламный шаблон с большим количеством символов.
    symbols = sum(1 for ch in text if not ch.isalnum() and not ch.isspace())
    if len(normalized) <= 180 and symbols >= 8 and any(
        phrase in normalized for phrase in CONTACT_PHRASES
    ):
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
