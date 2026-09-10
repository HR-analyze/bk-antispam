import re
import unicodedata

PROFANITY_ROOTS = (
    "бляд", "еб", "заеб", "выеб", "наеб", "поеб", "отъеб",
    "пизд", "хуй", "хуес", "нахуй", "ниху", "охуе",
    "мудак", "мудач", "долбоеб", "долбаеб", "уеб", "ёб", "ебл",
    "шлюх", "суч", "сук", "говн", "дерьм", "пидор", "пидар",
    "пидарас", "пидорас", "педик", "пидр", "гандон", "мраз", "твар",
)

PROFANITY_EXACT = {
    "бля", "бляха", "сука", "суки", "сучка", "сучки", "сучар",
    "пидарас", "пидарасы", "пидорас", "пидорасы", "пидр", "педик",
}

SPAM_PHRASES = (
    # Набор людей / подработка / сторонняя работа
    "заработок от", "заработок в день", "заработок без вложений", "заработок на дому",
    "заработок на дому", "заработок в интернете", "заработок онлайн", "быстрый заработок",
    "легкий заработок", "лёгкий заработок", "пассивный доход", "гарантированный доход",
    "доход от", "доход в день", "подработка", "подработку", "подработки",
    "требуются мужчины", "требуются женщины", "требуются девочки", "требуются девушки",
    "требуются мальчики", "требуются парни", "нужны мужчины", "нужны женщины",
    "нужны девочки", "нужны девушки", "нужны мальчики", "нужны парни",
    "ищем сотрудников", "ищем работника", "ищем работников", "набираем сотрудников",
    "требуется персонал", "требуется сотрудник", "набор персонала", "вакансия", "вакансии",
    "вакансии для", "работа для", "работа на дому", "работа онлайн", "работа удаленно",
    "работа удалённо", "работа в интернете",

    # Казино / ставки / розыгрыши
    "казино", "онлайн казино", "букмекер", "ставки на спорт", "ставка на спорт",
    "ставки онлайн", "ставки на футбол", "прогнозы на спорт", "спортивные прогнозы",
    "ставочный", "ставочник", "джекпот", "выигрыш", "выиграй", "вы выиграли",
    "вы выиграли приз", "забери приз", "забери бонус", "бонус за регистрацию",
    "бонус за регу", "регистрация с бонусом", "приз за регистрацию",

    # Финансы / инвестиции / крипта
    "инвестиции с гарантией", "инвестиций с гарантией", "инвестиционный доход",
    "гарантия дохода", "гарантированная прибыль", "гарантированная доходность",
    "криптовалюта", "крипта", "биткоин", "bitcoin", "ethereum", "usdt",
    "обмен крипты", "арбитраж крипты", "сигналы крипто", "сигналы для торговли",
    "торговые сигналы", "заработок на инвестициях", "инвестируй", "инвестируйте",
    "удвойте депозит", "удвоение депозита", "быстрый доход", "легкие деньги", "лёгкие деньги",
    "деньги за регистрацию", "выплата за регистрацию",

    # Секс / эскорт / знакомства как коммерческая или навязчивая реклама
    "интимные услуги", "интимные услуги", "интим за деньги", "секс за деньги",
    "секс услуги", "секс-услуги", "эскорт", "эскорт услуги", "эротический массаж",
    "интимный массаж", "онлифанс", "onlyfans", "проститутка", "проститутки",
    "проституция", "секс знакомства", "знакомства за деньги", "встречи за деньги",

    # Прямые рекламные CTA
    "пиши в лс", "пишите в лс", "напиши в лс", "напишите в лс",
    "пиши в личку", "пишите в личку", "напиши в личку", "напишите в личку",
    "в личку", "в лс", "личные сообщения", "пишите мне", "пиши мне",
)

PROMO_ROOTS = (
    "заработ", "доход", "казино", "букмек", "ставк", "ваканс", "подработ",
    "знакомств", "познаком", "эскорт", "интим", "онлифанс", "крипт", "инвестиц",
    "депозит", "выигрыш", "джекпот", "лотере", "сигнал", "приз",
)

CONTACT_PHRASES = (
    "лс", "личку", "личные сообщения", "пишите", "пиши", "напишите", "напиши",
    "звоните", "звони", "позвоните", "телефон",
)

URL_RE = re.compile(
    r"(?i)(?:https?://|www\.|t\.me/|telegram\.me/|tg://|wa\.me/|viber://|mailto:)\S+"
)
BARE_DOMAIN_RE = re.compile(
    r"(?i)(?<![@\w])(?:[a-zа-я0-9](?:[a-zа-я0-9-]{0,61}[a-zа-я0-9])?\.)+"
    r"(?:ru|рф|com|net|org|info|biz|me|cc|site|online|shop|store|pro|top|xyz|io|co|su|dev|app|link|live|world|vip|club|gg|bet|win)"
    r"(?:/\S*)?"
)

PHONE_RE = re.compile(
    r"(?<!\d)(?:\+?7|8)[\s().-]*\d{3}[\s().-]*\d{3}[\s.-]*\d{2}[\s.-]*\d{2}(?!\d)"
    r"|(?<!\d)\+?\d{10,15}(?!\d)"
)

RECRUITMENT_RE = re.compile(
    r"\b(?:нужн(?:ы|а|о)|требуютс[яь]|ищем|набор|набираем)\b\s+"
    r"\b(?:девоч\w*|девуш\w*|парн\w*|мужчин\w*|женщин\w*|мальчик\w*|сотрудник\w*|персонал)\b"
)

DATING_RE = re.compile(
    r"\b(?:знакомлюсь|познакомлюсь|знакомства|знакомств)\b.*"
    r"\b(?:девуш\w*|женщин\w*|парн\w*|мужчин\w*)\b"
    r"|\b(?:девуш\w*|женщин\w*|парн\w*|мужчин\w*)\b.*"
    r"\b(?:знакомлюсь|познакомлюсь|знакомства|знакомств)\b"
)


def normalize(text):
    text = unicodedata.normalize("NFKC", text or "").lower()
    text = text.translate(str.maketrans({
        "0": "о", "1": "и", "3": "з", "4": "ч", "5": "с",
        "6": "б", "7": "т", "8": "в", "9": "д", "@": "а", "$": "с", "!": "и",
    }))
    text = text.translate(str.maketrans({
        "a": "а", "e": "е", "o": "о", "p": "р", "c": "с", "x": "х",
        "y": "у", "k": "к", "m": "м", "t": "т",
    }))
    text = re.sub(r"(.)\1{2,}", r"\1\1", text)
    return text


def compact(text):
    return re.sub(r"[^a-zа-яё0-9]", "", normalize(text))


def contains_link(text):
    return bool(text and (URL_RE.search(text) or BARE_DOMAIN_RE.search(text)))


def contains_profanity(text):
    if not text:
        return False
    normalized = normalize(text)
    compacted = compact(text)
    cleaned = re.sub(r"[^a-zа-яё0-9]+", " ", normalized)
    padded = " " + cleaned + " "

    for word in PROFANITY_EXACT:
        if re.search(r"(?<![а-яёa-z])" + re.escape(word) + r"(?![а-яёa-z])", padded):
            return True

    for root in PROFANITY_ROOTS:
        if root in compacted:
            return True
        if len(root) >= 4:
            root_pattern = r"[^а-яёa-z0-9]*".join(map(re.escape, root))
            if re.search(root_pattern, normalized):
                return True
    return False


def looks_like_spam(text):
    if not text:
        return False

    normalized = re.sub(r"\s+", " ", normalize(text)).strip()

    if any(phrase in normalized for phrase in SPAM_PHRASES):
        return True

    if RECRUITMENT_RE.search(normalized):
        return True

    job = re.search(r"\b(работ\w*|ваканс\w*|заработ\w*|доход\w*|подработ\w*)\b", normalized)
    contact = re.search(r"\b(лс|личк\w*|пишите|пиши|напишите|напиши|звоните|звони|телефон)\b", normalized)
    if job and contact:
        return True

    if DATING_RE.search(normalized):
        return True

    people = re.search(r"\b(девуш\w*|женщин\w*|парн\w*|мужчин\w*)\b", normalized)
    if people and any(phrase in normalized for phrase in CONTACT_PHRASES):
        return True

    # Коммерческий признак + телефон.
    if PHONE_RE.search(normalized) and any(root in normalized for root in PROMO_ROOTS):
        return True

    # Сильный рекламный капс.
    letters = [ch for ch in text if ch.isalpha()]
    if len(letters) >= 15:
        upper_ratio = sum(ch.isupper() for ch in letters) / float(len(letters))
        if upper_ratio >= 0.80 and any(root in normalized for root in PROMO_ROOTS):
            return True

    # Перегруженный символами короткий CTA.
    symbols = sum(1 for ch in text if not ch.isalnum() and not ch.isspace())
    if len(normalized) <= 180 and symbols >= 8 and any(
        phrase in normalized for phrase in CONTACT_PHRASES
    ):
        return True

    return False


def classify(text):
    if contains_link(text):
        return "link"
    if contains_profanity(text):
        return "profanity"
    if looks_like_spam(text):
        return "spam"
    return None
