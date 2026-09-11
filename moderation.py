import re
import unicodedata

# NOTE: anti-spam rules are intentionally aggressive for the BK work chat.

PROFANITY_PATTERNS = [
    r"\bбля(?:дь|ть)?\w*\b", r"\bеб(?:ать|ан|лан|ло|лать)\w*\b",
    r"\b(?:вы|въ|за)еб\w*\b", r"\bхуй\w*\b", r"\bхуйн\w*\b",
    r"\bхуесос\w*\b", r"\bхуеплет\w*\b", r"\bхует\w*\b", r"\bхуят\w*\b",
    r"\bхерн\w*\b", r"\bпизд\w*\b", r"\bпидор\w*\b", r"\bпидар\w*\b",
    r"\bпидорас\w*\b", r"\bпетух\w*\b", r"\bпетушар\w*\b", r"\bговн\w*\b",
    r"\bдерьм\w*\b", r"\bссан\w*\b", r"\bшлюх\w*\b", r"\bшалав\w*\b",
    r"\bуеб\w*\b", r"\bуёб\w*\b", r"\bдолбоеб\w*\b",
    r"\bдолбоёб\w*\b", r"\bмудак\w*\b", r"\bмудил\w*\b", r"\bублюд\w*\b",
    r"\bжоп\w*\b",
    # Приставочные формы: \b перед "хуй" не даёт поймать "нахуй"/"похуй"/"нихуя".
    r"\bохуе\w*\b", r"\b(?:на|по|ни|до)ху[йяез]\w*\b",
    # "хрен" сам по себе — приправа, поэтому только ругательные обороты.
    r"\b(?:какого|каким|ни|до|по)\s+хрен\w*\b", r"\bхрен\s+(?:знает|тебе|вам|с\s+ним)\b",
    # Ниже — корни, которые совпадают с обычными словами. Без исключений фильтр
    # мата удалял "мандарин", "сукралозу" и подобное, причём ПЕРВЫМ правилом,
    # то есть подменял собой все остальные классификации.
    r"\bманд(?!ар|ат|ол|ув|ик)\w*\b",
    r"\bсук(?!ра|ла|ци|но|цес)\w*\b",
]
SPAM_PATTERNS = [r"\bзаработ\w*\b", r"\bинвестиц\w*\b", r"\bказино\b", r"\bставк\w*\b", r"\bкрипт\w*\b", r"\bнаркот\w*\b", r"\bспайс\w*\b", r"\bмефедрон\w*\b", r"\bпорн\w*\b", r"\bпроститут\w*\b", r"\bэскорт\w*\b", r"\bсекс\w*\b"]
NEGATIVE_PHRASES = {"обслуживание ужасное", "обслуживание ужасно", "ужасное обслуживание", "ужасный сервис", "ужасное место", "херня а не место", "говно а не", "скам проект", "скам-проект", "кто хочет денег", "легкий досуг", "лёгкий досуг", "легкий секс", "лёгкий секс", "детское порно", "детское порн", "кровь девственницы", "child porn", "child pornography", "sexual content involving minors"}
JOB_PHRASES = {"подработка", "подработку", "подработке", "подработки", "подработать", "шабашка", "шабашку", "шабашке", "шабашки", "хорошая подработка", "хорошо оплачиваемая подработка", "хорошо оплачиваемую подработку", "оплачиваемая подработка", "оплачиваемую подработку", "ищу кандидатов", "ищем кандидатов", "нужны кандидаты", "ищу сотрудников", "нужны сотрудники", "требуются сотрудники", "требуются люди", "нужны люди", "нужны мужчины", "нужны женщины", "мужчины и женщины", "мужчины или женщины", "мужчины женщины", "парни и девушки", "парни или девушки", "парни девушки", "нужны парни", "нужны девушки", "нужен парень", "нужна девушка", "нужны девочки", "нужна девочка", "ищу девочку", "ищу девочек", "требуется девочка", "требуются девочки", "ищу девушек", "требуется девушка", "требуются девушки", "мужчины на работу", "женщины на работу", "мужчина на работу", "женщина на работу", "ребята на работу", "ребята для работы", "молодые люди на работу", "варианты работы", "вариант работы", "новые вакансии", "новая вакансия", "есть вакансия", "есть вакансии", "срочно нужны", "срочно требуются", "нужны на сегодня", "нужны на завтра", "работа на пару часов", "работы на пару часов", "работа на несколько часов", "предоплата имеется", "предоплата есть", "легкий заработок", "лёгкий заработок", "легкие деньги", "лёгкие деньги", "заработок без опыта", "пишите в личку", "пишите в лс", "кому интересно пишите", "ищу работу"}
# Эти фразы однозначны только сами по себе. Как подстрока "работа есть"
# попадает в обычный отзыв ("над приложением ещё работа есть"), поэтому они
# проверяются лишь в коротком сообщении.
SHORT_JOB_PHRASES = ("работа есть", "есть работа", "нужна работа", "работа нужна", "ищу подработку", "подработка нужна")
SHORT_JOB_MAX_WORDS = 5

JOB_SIGNALS = ("подработ", "шабаш", "кандидат", "сотрудник", "ваканс", "предоплат", "оплата", "выплата", "заработ", "схем", "магазин", "точк", "пару часов", "несколько часов", "мужчин", "женщин", "парни", "девушки", "девушка", "девочк", "парень", "ребят", "в личку", "в лс")
OBFUSCATED_JOB_PATTERNS = (r"\b[wv]абашк\w*\b", r"\bш[аa]б[аa]шк\w*\b", r"\bп[оo]д[рr][аa]б[оo]тк\w*\b", r"\bпод\s*работ\w*\b")
PAID_TASK_SIGNALS = ("нужен человек", "нужна помощь", "ищу человека", "ищу кто", "нужен кто", "кто сможет", "кто сможет помочь", "кто сможет присмотреть", "присмотреть за", "присмотрит за", "посидеть с", "посидеть за", "помочь с", "нужно сделать", "нужен на", "нужна на", "ищу на завтра", "ищу на сегодня", "на постоянную основу", "на постоянной основе", "за 3 часа", "за 2 часа", "за час", "в день", "в сутки", "плачу", "оплачу", "оплата", "выплата")
PAID_AMOUNT_RE = re.compile(r"\b\d{2,6}\s*(?:₽|р\.?|руб(?:лей|ля)?\b)", re.IGNORECASE | re.UNICODE)
BARE_AMOUNT_RE = re.compile(r"\b\d{2,6}\b")
SPACED_DIGITS_RE = re.compile(r"(?<!\d)\d+(?:\s+\d+)+(?!\d)")
TASK_REQUEST_PHRASES = {"кто поможет с переездом", "кто может помочь с переездом", "кто сможет помочь с переездом", "кто поможет перевезти", "кто может перевезти", "кто сможет перевезти", "кто поможет с погрузкой", "кто может выгулять", "кто сможет выгулять", "кто может присмотреть за", "кто сможет присмотреть за", "ищу человека для переезда", "нужен человек для переезда"}
TASK_REQUEST_SIGNALS = ("кто сможет", "кто может", "кто-нибудь", "кто нибудь", "кто-нибудь знает", "кто нибудь знает", "кто знает", "есть кто", "нужен человек", "нужна помощь", "ищу человека", "ищу кто", "кто поможет", "кто сможет помочь", "кто может помочь")
TASK_ACTION_SIGNALS = ("помочь", "помощь", "поможет", "переезд", "перевезти", "перенести", "донести", "забрать", "отвезти", "привезти", "присмотреть", "посидеть", "выгул", "погулять", "убрать", "починить", "сделать", "собрать", "разобрать", "подменить", "присмотреть за")
FAKE_PURCHASE_PHRASES = {"купите у меня рекламу", "купить у меня рекламу", "закажите у меня рекламу", "купите у меня хоть", "купить у меня хоть", "сделайте заказ для отчета", "сделайте заказ для отчёта", "заказ ради отчета", "заказ ради отчёта", "покупка ради отчета", "покупка ради отчёта", "для доказательства покупки", "доказательство покупки", "подтвердить покупку", "подтвердите покупку", "доказательство оплаты", "подтвердить оплату", "подтвердите оплату", "скрин оплаты", "скрин покупки", "чек для отчета", "чек для отчёта", "чек для доказательства", "я написал что вы купили", "я написал, что вы купили", "я написал что вы у меня купили", "я написал, что вы у меня купили", "написал у себя что вы купили", "написал у себя, что вы купили", "можете подтвердить что покупали", "можете подтвердить, что покупали", "можете подтвердить что покупали у меня", "можете подтвердить, что покупали у меня"}
FAKE_PURCHASE_SIGNALS = ("купите у меня", "купить у меня", "закажите у меня", "реклам", "покупк", "заказ", "оплат", "чек", "скрин", "доказательств", "подтверд", "подтвержден", "для отчета", "для отчёта", "для кейса", "для портфолио", "для статистики", "для клиента", "я написал у себя", "я написала у себя", "в моем тгк", "в моём тгк", "в моем канале", "в моём канале", "посмотрите мой тгк", "посмотрите мой канал", "выручите", "хоть 10", "хоть 10р", "хоть 10 руб", "хоть 10 рублей", "хоть рубль", "символическую сумму")
FAKE_PURCHASE_AMOUNT_RE = re.compile(r"(?:хоть\s*)?(?:\d{1,3}\s*(?:₽|р\.?|руб(?:лей|ля)?\b)|руб(?:ль|ля|лей)\b)", re.IGNORECASE | re.UNICODE)

def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "").casefold()
    replacements = str.maketrans({"a": "а", "b": "б", "c": "с", "e": "е", "h": "х", "i": "и", "k": "к", "m": "м", "n": "н", "o": "о", "p": "п", "r": "р", "s": "с", "t": "т", "u": "у", "v": "в", "x": "х", "y": "у", "z": "з", "$": "с", "0": "о", "1": "и", "3": "з", "4": "ч", "6": "б"})
    return text.translate(replacements)

def normalize_spaced(text: str) -> str:
    text = normalize_text(text)
    text = re.sub(r"[^а-яёa-z0-9@]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()

def raw_spaced(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "").casefold()
    text = re.sub(r"[^а-яёa-z0-9₽@]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()

def compact_spaced(text: str) -> str:
    return re.sub(r"\s+", "", text)

def contains_link(text: str) -> bool:
    if not text: return False
    return bool(re.search(r"(?:https?://|www\.|t\.me/|telegram\.me/)", text, re.I))

def _matches_any(text: str, patterns) -> bool:
    return any(re.search(pattern, text, flags=re.IGNORECASE | re.UNICODE) for pattern in patterns)

def _has_spaced_number(raw: str, minimum: int = 100) -> bool:
    for match in SPACED_DIGITS_RE.finditer(raw):
        digits = re.sub(r"\s+", "", match.group(0))
        if len(digits) >= 3 and int(digits) >= minimum: return True
    return False

def _is_task_request_spam(normalized: str, spaced: str) -> bool:
    compact = compact_spaced(spaced)
    if any(normalize_spaced(phrase) in spaced or normalize_spaced(phrase).replace(" ", "") in compact for phrase in TASK_REQUEST_PHRASES): return True
    request_count = sum(1 for signal in TASK_REQUEST_SIGNALS if normalize_spaced(signal) in spaced)
    action_count = sum(1 for signal in TASK_ACTION_SIGNALS if normalize_spaced(signal) in spaced)
    has_task_target = any(token in normalized for token in ("переезд", "попуга", "собак", "кошк", "шкаф", "вещ", "машин", "квартир", "ребенк", "ребёнк"))
    has_payment = any(token in normalized for token in ("плачу", "оплачу", "оплата", "выплата", "за час", "в день", "в сутки", "денег", "деньги"))
    # Просьба + действие сама по себе — это обычный клиент ("кто может помочь
    # выбрать торт"). Спамом её делает бытовая задача или оплата.
    return request_count >= 1 and action_count >= 1 and (has_task_target or has_payment)

def _is_paid_task_spam(normalized: str, spaced: str, raw: str) -> bool:
    has_currency_amount = bool(PAID_AMOUNT_RE.search(raw)); has_spaced_amount = _has_spaced_number(raw)
    bare_amounts = [int(value) for value in BARE_AMOUNT_RE.findall(raw) if int(value) >= 100]
    has_bare_amount = bool(bare_amounts) or has_spaced_amount
    task_signal_count = sum(1 for signal in PAID_TASK_SIGNALS if normalize_spaced(signal) in spaced)
    has_people = any(token in normalized for token in ("человек", "людей", "кто", "ребят", "парень", "девуш", "девочк", "женщ", "мужчин"))
    has_time = any(token in normalized for token in ("завтра", "сегодня", "час", "дня", "день", "сутки", "постоянн"))
    has_work_word = any(token in normalized for token in ("работ", "подработ", "присмотр", "помощ", "помочь", "сделать", "посидет"))
    compact = compact_spaced(spaced)
    has_obfuscated_work = bool(re.search(r"подработ\w*|шабаш\w*|ваканс\w*", compact, re.IGNORECASE | re.UNICODE))
    has_duration = bool(re.search(r"\b\d{1,3}\s*(?:час(?:а|ов)?|дн(?:я|ей)?|сут(?:ки|ок)?)\b", raw, re.IGNORECASE | re.UNICODE))
    if (has_currency_amount or has_spaced_amount or (has_bare_amount and ("плачу" in raw or "оплата" in raw or has_duration))) and (task_signal_count >= 1 or has_obfuscated_work): return True
    if has_people and has_time and has_obfuscated_work and has_bare_amount: return True
    if has_currency_amount and has_people and has_time and has_work_word: return True
    return False

# Схема «купите у меня хоть на 10 рублей, мне нужен скрин для отчёта» отличается
# от обычной клиентской реплики именно выгодой автора. Без этого требования
# правило удаляло "подтвердите заказ пожалуйста" и "чек не дали при покупке".
FAKE_PURCHASE_SELF_INTEREST = ("у меня", "у себя", "мой тгк", "моем тгк", "моём тгк", "мой канал", "моем канале", "моём канале", "для отчета", "для отчёта", "ради отчета", "ради отчёта", "для кейса", "для портфолио", "для статистики", "для клиента", "что вы купили", "что вы у меня купили", "что покупали", "выручите", "символическую сумму")

def _count_signals(spaced: str, signals) -> int:
    """Считает сигналы по началу слова.

    Подстрочный подсчёт задваивал один смысл: "оплата" совпадала внутри
    "предоплата", и обычное "а предоплата нужна?" набирало два сигнала.
    """
    return sum(
        1 for signal in signals
        if re.search(rf"\b{re.escape(normalize_spaced(signal))}", spaced)
    )

def _is_short_job_message(spaced: str) -> bool:
    """Короткие фразы о работе — только если из них и состоит сообщение."""
    if len(spaced.split()) > SHORT_JOB_MAX_WORDS: return False
    return any(normalize_spaced(phrase) in spaced for phrase in SHORT_JOB_PHRASES)

def _is_fake_purchase_spam(normalized: str, spaced: str) -> bool:
    if any(normalize_spaced(phrase) in spaced for phrase in FAKE_PURCHASE_PHRASES): return True
    signal_count = sum(1 for signal in FAKE_PURCHASE_SIGNALS if normalize_spaced(signal) in spaced)
    has_small_amount = bool(FAKE_PURCHASE_AMOUNT_RE.search(spaced))
    has_purchase_context = any(token in normalized for token in ("куп", "заказ", "реклам", "оплат", "покупк"))
    has_proof_context = any(token in normalized for token in ("доказ", "подтверд", "скрин", "чек", "отчет", "отчёт", "кейса", "портфолио"))
    has_self_interest = any(normalize_spaced(token) in spaced for token in FAKE_PURCHASE_SELF_INTEREST)
    if not has_self_interest: return False
    if has_purchase_context and has_proof_context: return True
    if has_small_amount and signal_count >= 2: return True
    if has_small_amount and has_purchase_context and signal_count >= 1: return True
    return False

def classify(text: str):
    normalized = normalize_text(text)
    spaced = normalize_spaced(text)
    raw = raw_spaced(text)
    if _matches_any(normalized, PROFANITY_PATTERNS): return "profanity"
    if any(normalize_spaced(phrase) in spaced for phrase in NEGATIVE_PHRASES): return "negative"
    if _matches_any(normalized, SPAM_PATTERNS): return "spam"
    compact = compact_spaced(spaced)
    if any(re.search(pattern, compact, re.I | re.U) for pattern in OBFUSCATED_JOB_PATTERNS): return "job_spam"
    if any(normalize_spaced(phrase) in spaced for phrase in JOB_PHRASES): return "job_spam"
    job_signal_count = _count_signals(spaced, JOB_SIGNALS)
    if job_signal_count >= 2: return "job_spam"
    if _is_short_job_message(spaced): return "job_spam"
    if _is_fake_purchase_spam(normalized, spaced): return "fake_purchase"
    if _is_task_request_spam(normalized, spaced): return "paid_task"
    if _is_paid_task_spam(normalized, spaced, raw): return "paid_task"
    return None


# --------------------------------------------------------------------------- решение по сообщению

# Метки для логов, БД и дашборда. Ключи должны совпадать с тем, что возвращает
# classify() / classify_message().
REASONS = {
    "link": "ссылка",
    "profanity": "мат",
    "negative": "негатив",
    "spam": "спам/реклама",
    "job_spam": "предложение работы/подработки",
    "fake_purchase": "фиктивная покупка/доказательство оплаты",
    "paid_task": "платная просьба/бытовая подработка",
    "flood": "флуд/повтор",
}


def text_variants(text: str) -> tuple[str, ...]:
    """Исходный текст и вариант с заменой обхода фильтра: '$'/'s' -> 'с'.

    Раньше оба склеивались в одну строку. Из-за этого любая логика, зависящая
    от длины сообщения, видела двойной текст, поэтому теперь это два отдельных
    варианта, и каждая проверка прогоняется по обоим.
    """
    original = text or ""
    swapped = original.lower().translate(str.maketrans({"$": "с", "s": "с"}))
    return (original,) if swapped == original.lower() else (original, swapped)


def spaced_job_fallback(text: str) -> bool:
    """Ловит слова о работе, разбитые пробелами: 'подрабо тку'."""
    compact = re.sub(r"[^а-яёa-z]", "", (text or "").casefold())
    return bool(re.search(r"подработ|шабаш|ваканс", compact, re.IGNORECASE | re.UNICODE))


def direct_gender_job_fallback(text: str) -> bool:
    """Короткие гендерные запросы вида 'нужны девочки' — до общего классификатора."""
    normalized = " ".join((text or "").casefold().split())
    # Только именительный и винительный: \w* ловил дательный ("нужны девочкам
    # заколки", "нужны ребятам подарки") и удалял обычные сообщения.
    who = r"(?:девочк(?:а|и|у)|девушк(?:а|и|у)|девуш(?:ек|ку)|женщин(?:а|ы|у)|парн(?:и|я|ей)|парень|мужчин(?:а|ы|у)|мальчик(?:и|а)?|ребят(?:а)?)"
    return bool(re.search(rf"\b(?:нуж(?:ен|на|но|ны)|ищу|ищем|требуется|требуются|возьму)\s+{who}\b", normalized))


def direct_child_job_fallback(text: str) -> bool:
    """Явные запросы детей/подростков как работников."""
    normalized = " ".join((text or "").casefold().split())
    # Ни голого "дет", ни дательного "детям": из-за них правило удаляло
    # "нужны детям подарки" и "нужен детский торт".
    child = r"(?:дет(?:и|ей|ьми|ях)|реб[её]нок|ребят|подрост(?:ок|ка|ки|ков)|школьник\w*)"
    request = r"(?:нуж(?:ен|на|ны)|ищ(?:у|ем)|требу(?:ется|ются)|возьм(?:у|ём)|ищется)"
    work = r"(?:на\s+работу|для\s+работы|на\s+подработку|для\s+подработки|работать|подработать|на\s+съ[её]мку|для\s+съ[её]мки)"
    return bool(
        re.search(rf"\b{request}\s+{child}\b", normalized)
        or re.search(rf"\b{child}\s+{work}\b", normalized)
    )


def classify_message(text: str, has_link: bool = False):
    """Полное решение по одному сообщению. Возвращает ключ из REASONS или None.

    Порядок важен: жёсткие правила идут до общего классификатора, иначе общая
    классификация перекрывает явные запросы о работе.
    """
    if has_link or contains_link(text):
        return "link"
    variants = text_variants(text)
    if any(direct_gender_job_fallback(v) or direct_child_job_fallback(v) for v in variants):
        return "job_spam"
    for variant in variants:
        reason = classify(variant)
        if reason is not None:
            return reason
    if any(spaced_job_fallback(v) for v in variants):
        return "job_spam"
    return None
