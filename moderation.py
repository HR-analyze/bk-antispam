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

# Recruitment / job-offer spam. Phrase based to avoid deleting ordinary
# discussion of work.
JOB_PHRASES = {
    "подработка", "подработку", "подработке", "подработки", "подработать",
    "шабашка", "шабашку", "шабашке", "шабашки", "хорошая подработка",
    "хорошо оплачиваемая подработка", "хорошо оплачиваемую подработку",
    "оплачиваемая подработка", "оплачиваемую подработку",
    "ищу кандидатов", "ищем кандидатов", "нужны кандидаты", "ищу сотрудников",
    "нужны сотрудники", "требуются сотрудники", "требуются люди", "нужны люди",
    "нужны мужчины", "нужны мужчина", "нужны женщины", "нужны женщина",
    "мужчины и женщины", "мужчины или женщины", "мужчины женщины",
    "парни и девушки", "парни или девушки", "парни девушки",
    "нужны парни", "нужны девушки", "нужен парень", "нужна девушка",
    "мужчины на работу", "женщины на работу", "мужчина на работу", "женщина на работу",
    "ребята на работу", "ребята для работы", "молодые люди на работу",
    "открыла магазин", "открыл магазин", "открыли магазин", "открываем магазин",
    "открыла точку", "открыл точку", "открыли точку", "новая схема", "новой схемы",
    "есть варианты", "есть вариант", "варианты работы", "вариант работы",
    "новая работа", "новые вакансии", "новая вакансия", "есть вакансия",
    "есть вакансии", "срочно нужны", "срочно требуются", "нужны на сегодня",
    "нужны на завтра", "работа на пару часов", "работы на пару часов",
    "работа на несколько часов", "на несколько часов", "на пару часов",
    "предоплата", "предоплата имеется", "предоплата есть", "оплата сразу",
    "выплата сразу", "деньги сразу", "легкий заработок", "лёгкий заработок",
    "легкие деньги", "лёгкие деньги", "заработок без опыта", "без опыта",
    "пишите в личку", "пишите в лс", "пишите мне", "кому интересно пишите",
}

JOB_SIGNALS = (
    "подработ", "шабаш", "кандидат", "сотрудник", "ваканс", "предоплат",
    "оплата", "выплата", "заработ", "схем", "магазин", "точк", "пару часов",
    "несколько часов", "мужчин", "женщин", "парни", "девушки", "парень", "девушка",
    "ребят", "пишите", "в личку", "в лс",
)

OBFUSCATED_JOB_PATTERNS = (
    r"\b[wv]абашк\w*\b",
    r"\bш[аa]б[аa]шк\w*\b",
    r"\bп[оo]д[рr][аa]б[оo]тк\w*\b",
)

# Manipulative requests for a fake/symbolic purchase, payment, receipt or
# proof of cooperation. These are intentionally combination-based so a normal
# message such as "купить продукты" is not removed.
FAKE_PURCHASE_PHRASES = {
    "купите у меня рекламу", "купить у меня рекламу", "закажите у меня рекламу",
    "купите у меня хоть", "купить у меня хоть", "сделайте заказ для отчета",
    "сделайте заказ для отчёта", "заказ ради отчета", "заказ ради отчёта",
    "покупка ради отчета", "покупка ради отчёта", "для доказательства покупки",
    "доказательство покупки", "подтвердить покупку", "подтвердите покупку",
    "доказательство оплаты", "подтвердить оплату", "подтвердите оплату",
    "скрин оплаты", "скрин оплаты", "скрин покупки", "скрин покупки",
    "чек для отчета", "чек для отчёта", "чек для доказательства",
    "я написал что вы купили", "я написал, что вы купили",
    "я написал что вы у меня купили", "я написал, что вы у меня купили",
    "написал у себя что вы купили", "написал у себя, что вы купили",
    "можете подтвердить что покупали", "можете подтвердить, что покупали",
    "можете подтвердить что покупали у меня", "можете подтвердить, что покупали у меня",
}

FAKE_PURCHASE_SIGNALS = (
    "купите у меня", "купить у меня", "закажите у меня", "реклам", "покупк",
    "заказ", "оплат", "чек", "скрин", "доказательств", "подтверд", "подтвержден",
    "для отчета", "для отчёта", "для кейса", "для портфолио", "для статистики",
    "для клиента", "я написал у себя", "я написала у себя", "в моем тгк",
    "в моём тгк", "в моем канале", "в моём канале", "посмотрите мой тгк",
    "посмотрите мой канал", "выручите", "хоть 10", "хоть 10р", "хоть 10 руб",
    "хоть 10 рублей", "хоть рубль", "символическую сумму",
)

FAKE_PURCHASE_AMOUNT_RE = re.compile(
    r"(?:хоть\s*)?(?:\d{1,3}\s*(?:₽|р\.?|руб(?:лей|ля)?\b)|руб(?:ль|ля|лей)\b)",
    re.IGNORECASE | re.UNICODE,
)


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


def _is_fake_purchase_spam(normalized: str, spaced: str) -> bool:
    """Detect requests to create a fake/symbolic purchase or proof of payment."""
    if any(normalize_spaced(phrase) in spaced for phrase in FAKE_PURCHASE_PHRASES):
        return True

    signal_count = sum(1 for signal in FAKE_PURCHASE_SIGNALS if normalize_spaced(signal) in spaced)
    has_small_amount = bool(FAKE_PURCHASE_AMOUNT_RE.search(spaced))
    has_purchase_context = any(
        token in normalized
        for token in ("куп", "заказ", "реклам", "оплат", "покупк")
    )
    has_proof_context = any(
        token in normalized
        for token in ("доказ", "подтверд", "скрин", "чек", "отчет", "отчёт", "кейса", "портфолио")
    )

    # Strong combination: purchase/payment + proof/report, optionally with a
    # tiny amount or emotional/Telegram-channel bait.
    if has_purchase_context and has_proof_context:
        return True
    if has_small_amount and signal_count >= 2:
        return True
    if has_small_amount and has_purchase_context and signal_count >= 1:
        return True

    return False


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

    if _is_fake_purchase_spam(normalized, spaced):
        return "fake_purchase_spam"

    for phrase in JOB_PHRASES:
        if normalize_spaced(phrase) in spaced:
            return "job_spam"

    job_signal_count = sum(1 for signal in JOB_SIGNALS if normalize_text(signal) in normalized)
    if job_signal_count >= 2:
        return "job_spam"

    if _matches_any(spaced, OBFUSCATED_JOB_PATTERNS):
        return "job_spam"

    return None
