import re

# --- 1. СПИСКИ (БЕЛЫЕ И ЧЕРНЫЕ) ---

WHITELIST = {
    # Обычные слова
    'хлеб', 'употреб', 'треб', 'греб', 'колеб', 'оскорб', 'рубл', 'корабл',
    'истреб', 'реб', 'скреб', 'углуб', 'парикмахер', 'херсон', 'страх', 'трах',
    'сабля', 'ансамбля', 'граблей', 'рублей', 'стебля', 'оглобля', 'люб', 'влюб',
    'мандарин', 'кандидат', 'психуй', 'политика конфиденциальности', 'политика обработки',
    'инструкция по охране', 'инструкция по пожарной',
    # ВАЖНО: Слова-исключения для рабочих процессов
    'команда', 'командировка', 'командировк', 'рекомендаци', 'мандат', 'команду'
}

# --- 2. ПАТТЕРНЫ МАТА ---
MAT_PATTERNS = [
    r'х[уy]([ийяёeю]|ли|лe|лi|лu)', r'п[иeё][зс]д', r'[её]б[ауеио](?!(л\b|н\b|с\b))',
    r'м[ау]нд[аиу]', r'п[иe]д[аоэe]р', r'г[ао]вн', r'ж[оo]п', r'з[ао]л[уy]п',
    r'г[ао]нд[оа]н', r'шл[юу]х', r'м[уy]д[а]к', r'д[ао]лб[ао]', r'сук[аи]',
    r'чм[оэe]', r'д[еe]рьм', r'хер\b', r'ф[аa]к', r'ш[иы]т', r'б[иc]ч',
    r'пусси', r'к[уa]к[оa]лд', r'с[еe]кс', r'г[еe]й', r'л[еe]сб', r'н[ие]гг?[еа]р'
]

# --- 3. ПАТТЕРНЫ ПОЛИТИКИ ---
POLITICS_PATTERNS = [
    r'путин', r'зеленск', r'навальн', r'трамп', r'байден', r'лукашенк',
    r'росси', r'украин', r'сша', r'америк', r'нато', r'nato', r'ес', r'евросоюз',
    r'крым', r'донбасс', r'луганск', r'днр', r'лнр', r'херсон', r'запорож',
    r'войн', r'сво\b', r'спецопераци', r'фронт', r'мобилизаци',
    r'санкци', r'рубл', r'доллар', r'экономик', r'кризис',
    r'ватник', r'укроп', r'хохол', r'москаль', r'бандер', r'нацист', r'фашист',
    r'z', r'v', r'выбор', r'голосован', r'депутат', r'правительств', r'мид',
    r'взрыв', r'теракт', r'атак', r'бпла', r'дрон', r'ракет'
]

# --- 4. ПАТТЕРНЫ ВЗЛОМА ---
INJECTION_PATTERNS = [
    r'забудь.*инструкци', r'игнорируй.*инструкци', r'forget.*instruction',
    r'ignore.*instruction', r'system.*prompt', r'системн.*промпт',
    r'you.*are.*now', r'ты.*теперь.*робот', r'DAN.*mode', r'jailbreak',
    r'отключ.*ограничени', r'disable.*filter', r'never.*refuse',
    r'никогда.*не.*отказывай', r'role.*play', r'do.*anything.*now'
]

# Компиляция
MAT_COMPILED = re.compile(r'|'.join(MAT_PATTERNS), re.IGNORECASE | re.UNICODE)
POLITICS_COMPILED = re.compile(r'|'.join(POLITICS_PATTERNS), re.IGNORECASE | re.UNICODE)
INJECTION_COMPILED = re.compile(r'|'.join(INJECTION_PATTERNS), re.IGNORECASE | re.UNICODE)

def check_text(text):
    if not text or not isinstance(text, str): return None
    
    clean_text = re.sub(r'[^a-zA-Zа-яА-ЯёЁ\s]', '', text.lower())
    
    # Whitelist
    for word in clean_text.split():
        if word in WHITELIST: return None

    text_no_spaces = clean_text.replace(' ', '')
    replacements = {'a': 'а', 'o': 'о', 'e': 'е', 'p': 'р', 'c': 'с', 'y': 'у', 'x': 'х', 'k': 'к', 'b': 'в', 'm': 'м', 'h': 'н', 't': 'т'}
    for eng, rus in replacements.items():
        text_no_spaces = text_no_spaces.replace(eng, rus)

    if INJECTION_COMPILED.search(clean_text): return 'injection'
    if MAT_COMPILED.search(text_no_spaces) or MAT_COMPILED.search(clean_text): return 'mat'
    if POLITICS_COMPILED.search(clean_text): return 'politics'

    return None